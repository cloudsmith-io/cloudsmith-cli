# Copyright 2026 Cloudsmith Ltd
"""Local stand-in for a Cloudsmith NuGet feed and the custom-domains API.

Used by the NuGet credential provider workflow to exercise the provider end to
end with a real ``dotnet restore`` and no live Cloudsmith account:

* ``GET /orgs/<workspace>/custom-domains/`` answers like the Cloudsmith API,
  listing ``--custom-domain`` as an enabled, validated NuGet custom domain.
  It requires the ``X-Api-Key`` header to equal ``--api-key``.
* ``/<workspace>/<repo>/v3/...`` is a minimal NuGet v3 feed (service index and
  flat container) serving the ``.nupkg`` files in ``--packages-dir``.  Every
  feed request requires HTTP Basic auth whose password equals ``--api-key``,
  and is otherwise answered with 401 like a private Cloudsmith repository.
* ``GET /__stats`` reports request counters so the workflow can assert which
  paths were exercised.
"""

import argparse
import base64
import json
import re
import socket
import sys
import threading
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class IPv6Server(ThreadingHTTPServer):
    """Loopback IPv6 listener, so ``localhost`` works if it resolves to ``::1``."""

    address_family = socket.AF_INET6


def read_packages(packages_dir: Path) -> dict:
    """Map lower-cased package id -> {lower-cased version: nupkg path}."""
    packages: dict = {}
    for path in sorted(packages_dir.glob("*.nupkg")):
        with zipfile.ZipFile(path) as archive:
            nuspec = next(n for n in archive.namelist() if n.endswith(".nuspec"))
            text = archive.read(nuspec).decode("utf-8-sig")
        package_id = re.search(r"<id>([^<]+)</id>", text).group(1)
        version = re.search(r"<version>([^<]+)</version>", text).group(1)
        packages.setdefault(package_id.lower(), {})[version.lower()] = path
    return packages


def make_handler(args, packages, stats, lock):
    """Build the request handler bound to this run's configuration."""
    feed_prefix = f"/{args.workspace}/{args.repo}/v3/"
    api_paths = {
        f"/orgs/{args.workspace}/custom-domains/",
        f"/v1/orgs/{args.workspace}/custom-domains/",
    }

    def count(key):
        with lock:
            stats[key] = stats.get(key, 0) + 1

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *a):
            sys.stderr.write(f"[mock] {format % a}\n")

        def _send(self, status, body=b"", content_type="application/json"):
            self.send_response(status)
            if status == HTTPStatus.UNAUTHORIZED:
                self.send_header("WWW-Authenticate", 'Basic realm="Cloudsmith"')
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, payload, status=HTTPStatus.OK):
            self._send(status, json.dumps(payload).encode("utf-8"))

        def _feed_authorized(self):
            header = self.headers.get("Authorization", "")
            scheme, _, encoded = header.partition(" ")
            if scheme.lower() != "basic":
                return False
            try:
                decoded = base64.b64decode(encoded).decode("utf-8")
            except ValueError:
                return False
            return decoded.partition(":")[2] == args.api_key

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = self.path.split("?", 1)[0]

            if path == "/__stats":
                self.log_message = lambda *a: None
                with lock:
                    self._json(dict(stats))
                return

            if path in api_paths:
                if self.headers.get("X-Api-Key") != args.api_key:
                    count("api_unauthorized")
                    self._json({"detail": "Invalid token."}, HTTPStatus.UNAUTHORIZED)
                    return
                count("api_custom_domains")
                self._json(
                    [
                        {
                            "host": args.custom_domain,
                            "backend_kind": 10,
                            "domain_type": 3,
                            "enabled": True,
                            "validated": True,
                            "primary": True,
                            "repository": {"name": args.repo, "slug": args.repo},
                            "slug_perm": "ciNuGetDomain",
                            "created_at": datetime(
                                2026, 1, 1, tzinfo=timezone.utc
                            ).isoformat(),
                        }
                    ]
                )
                return

            if not path.startswith(feed_prefix):
                self._json({"detail": "Not found."}, HTTPStatus.NOT_FOUND)
                return

            if not self._feed_authorized():
                count("feed_unauthorized")
                self._json({"detail": "Unauthorized."}, HTTPStatus.UNAUTHORIZED)
                return
            count("feed_authorized")

            base = f"http://{self.headers.get('Host')}{feed_prefix}"
            rest = path[len(feed_prefix) :]
            parts = rest.split("/")

            if rest == "index.json":
                self._json(
                    {
                        "version": "3.0.0",
                        "resources": [
                            {
                                "@id": f"{base}flatcontainer/",
                                "@type": "PackageBaseAddress/3.0.0",
                            }
                        ],
                    }
                )
                return

            if (
                parts[0] == "flatcontainer"
                and len(parts) == 3
                and parts[2] == "index.json"
            ):
                versions = packages.get(parts[1].lower())
                if not versions:
                    self._json({"detail": "Not found."}, HTTPStatus.NOT_FOUND)
                    return
                self._json({"versions": sorted(versions)})
                return

            if parts[0] == "flatcontainer" and len(parts) == 4:
                nupkg = packages.get(parts[1].lower(), {}).get(parts[2].lower())
                if nupkg is None or not parts[3].lower().endswith(".nupkg"):
                    self._json({"detail": "Not found."}, HTTPStatus.NOT_FOUND)
                    return
                count("feed_downloads")
                self._send(
                    HTTPStatus.OK, nupkg.read_bytes(), "application/octet-stream"
                )
                return

            self._json({"detail": "Not found."}, HTTPStatus.NOT_FOUND)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--port-file", type=Path, required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--packages-dir", type=Path, required=True)
    parser.add_argument("--custom-domain", default="localhost")
    args = parser.parse_args()

    packages = read_packages(args.packages_dir)
    if not packages:
        parser.error(f"no .nupkg files found in {args.packages_dir}")

    handler = make_handler(args, packages, {}, threading.Lock())

    # Loopback only: listen on 127.0.0.1, and on ::1 with the same port when
    # the host has IPv6, since clients may resolve `localhost` to either.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    port = server.server_address[1]
    try:
        server6 = IPv6Server(("::1", port), handler)
    except OSError:
        pass
    else:
        threading.Thread(target=server6.serve_forever, daemon=True).start()

    args.port_file.write_text(str(port), encoding="utf-8")
    sys.stderr.write(f"[mock] serving {sorted(packages)} on port {port}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
