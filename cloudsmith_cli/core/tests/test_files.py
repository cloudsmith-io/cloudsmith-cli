"""Tests for the files API upload helpers."""

import contextlib
import hashlib
import tracemalloc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from cloudsmith_api.rest import ApiException as SdkApiException

from ..api import files as files_api
from ..api.exceptions import ApiException
from ..api.files import CHUNK_SIZE, multi_part_upload_file, upload_file
from ..credentials.models import CredentialResult


class _RetryUploadHandler(BaseHTTPRequestHandler):
    """Return one redirect and one retryable error while recording requests."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_PUT(self):
        query = parse_qs(urlparse(self.path).query)
        part_number = int(query["part_number"][0])
        attempt = self.server.attempts.get(part_number, 0) + 1
        self.server.attempts[part_number] = attempt
        length = int(self.headers["Content-Length"])
        self.connection.settimeout(2)
        body = self.rfile.read(length)
        if len(body) != length:
            self.close_connection = True
            return

        if part_number == 1 and attempt == 1:
            status = 307
            location = f"http://127.0.0.1:{self.server.server_port}/redirected?{self.path.partition('?')[2]}"
        elif part_number == 2 and attempt == 1:
            status = 503
            location = None
        else:
            status = 200
            location = None

        self.server.records.append(
            {
                "path": self.path,
                "part_number": part_number,
                "attempt": attempt,
                "content_length": length,
                "received": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "auth": self.headers.get("X-Api-Key"),
                "transfer_encoding": self.headers.get("Transfer-Encoding"),
                "status": status,
            }
        )
        self.server.events.append(("part", part_number, attempt, status))
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()


@contextlib.contextmanager
def _retry_upload_server():
    """Run the small local server used to check Requests body replay."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RetryUploadHandler)
    server.daemon_threads = True
    server.records = []
    server.events = []
    server.attempts = {}
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _configure_upload_session(monkeypatch):
    """Use one quick status retry and bypass ambient proxies for loopback tests."""
    config = SimpleNamespace(
        error_retry_max=1,
        error_retry_backoff=0,
        error_retry_codes=[503],
        verify_ssl=True,
        ssl_verify_strict=True,
        cert_file=None,
        key_file=None,
        proxy=None,
    )
    monkeypatch.setattr(
        "cloudsmith_cli.core.session._sdk_configuration", lambda: config
    )
    monkeypatch.setattr("cloudsmith_cli.core.session.get_default_proxy", lambda: None)
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def _sha256_zeros(size):
    digest = hashlib.sha256()
    block = b"\0" * (64 * 1024)
    while size:
        count = min(size, len(block))
        digest.update(block[:count])
        size -= count
    return digest.hexdigest()


def upload_and_capture_headers(tmp_path, credential, api_key=None):
    """Run a single-chunk multi-part upload and return the headers it sent."""
    filepath = tmp_path / "package.raw"
    filepath.write_bytes(b"payload")

    opts = Mock(credential=credential, api_key=api_key)
    session = Mock()
    session.put.return_value = Mock(raise_for_status=Mock(return_value=None))

    with (
        patch(
            "cloudsmith_cli.core.api.files.create_requests_session",
            return_value=session,
        ),
        patch("cloudsmith_cli.core.api.files.get_files_api"),
    ):
        multi_part_upload_file(
            opts,
            upload_url="https://upload.example.invalid/parts",
            owner="owner",
            repo="repo",
            filepath=str(filepath),
            callback=lambda: None,
            upload_id="upload-id",
        )

    return session.put.call_args.kwargs["headers"]


class TestMultiPartUploadAuth:
    """The multi-part upload endpoint answers 404 for an unauthenticated
    request, so credentials must come from the resolved credential chain
    rather than opts.api_key, which OIDC and SAML never populate.
    """

    def test_uses_resolved_credential_not_opts_api_key(self, tmp_path):
        credential = CredentialResult(api_key="csa_resolved", source_name="oidc")

        headers = upload_and_capture_headers(tmp_path, credential, api_key="csa_stale")

        assert headers == {"X-Api-Key": "csa_resolved"}

    def test_invents_no_header_without_a_credential(self, tmp_path):
        """No credential means no credentials at all, and the preceding
        files_create call would already have failed.
        """
        headers = upload_and_capture_headers(
            tmp_path, credential=None, api_key="csa_stale"
        )

        assert headers == {}

    def test_sends_sso_token_as_bearer_authorization(self, tmp_path):
        credential = CredentialResult(
            api_key="sso-token", source_name="keyring", auth_type="bearer"
        )

        headers = upload_and_capture_headers(tmp_path, credential)

        assert headers == {"Authorization": "Bearer sso-token"}


class TestUploadErrors:
    """A request that fails before the API replies is reported like an API error."""

    def test_transport_error(self, tmp_path):
        filepath = tmp_path / "package.raw"
        filepath.write_bytes(b"payload")
        error = requests.ConnectionError("offline")
        with (
            patch(
                "cloudsmith_cli.core.api.files.create_requests_session",
                return_value=Mock(**{"post.side_effect": error}),
            ),
            patch("cloudsmith_cli.core.api.files.get_files_api"),
            pytest.raises(ApiException) as raised,
        ):
            upload_file("https://upload.example.invalid/", {}, str(filepath))

        assert raised.value.status == 0
        assert raised.value.__cause__ is error

    def test_failed_multi_part_completion(self, tmp_path):
        filepath = tmp_path / "package.raw"
        filepath.write_bytes(b"payload")
        files_api = Mock(
            **{"files_complete.side_effect": SdkApiException(status=0, reason="SSL")}
        )
        with (
            patch("cloudsmith_cli.core.api.files.create_requests_session"),
            patch(
                "cloudsmith_cli.core.api.files.get_files_api", return_value=files_api
            ),
            pytest.raises(ApiException) as raised,
        ):
            multi_part_upload_file(
                Mock(credential=None),
                upload_url="https://upload.example.invalid/parts",
                owner="owner",
                repo="repo",
                filepath=str(filepath),
                callback=lambda: None,
                upload_id="upload-id",
            )

        assert raised.value.status == 0


class TestMultiPartUploadReplay:
    """Multipart request bodies remain replayable after redirects and retries."""

    def test_exact_parts_replay_after_redirect_and_retry(self, tmp_path, monkeypatch):
        filepath = tmp_path / "package.raw"
        filepath.write_bytes(b"abcdefgh")
        monkeypatch.setattr(files_api, "CHUNK_SIZE", 4)
        _configure_upload_session(monkeypatch)

        with _retry_upload_server() as server:
            files_client = Mock()
            files_client.files_complete.side_effect = lambda *args, **kwargs: (
                server.events.append(("complete",))
            )
            callbacks = []

            def callback():
                callbacks.append(None)
                server.events.append(("callback", len(callbacks)))

            credential = CredentialResult(api_key="csa_test", source_name="oidc")
            with patch.object(files_api, "get_files_api", return_value=files_client):
                multi_part_upload_file(
                    Mock(credential=credential),
                    f"http://127.0.0.1:{server.server_port}/parts",
                    "owner",
                    "repo",
                    str(filepath),
                    callback,
                    "upload-id",
                )

        expected_bodies = [b"abcd", b"abcd", b"efgh", b"efgh"]
        assert [record["part_number"] for record in server.records] == [1, 1, 2, 2]
        assert [record["attempt"] for record in server.records] == [1, 2, 1, 2]
        assert [record["status"] for record in server.records] == [307, 200, 503, 200]
        assert [record["content_length"] for record in server.records] == [4, 4, 4, 4]
        assert [record["sha256"] for record in server.records] == [
            hashlib.sha256(body).hexdigest() for body in expected_bodies
        ]
        assert all(record["auth"] == "csa_test" for record in server.records)
        assert all(record["transfer_encoding"] is None for record in server.records)
        assert callbacks == [None, None]
        assert server.events == [
            ("part", 1, 1, 307),
            ("part", 1, 2, 200),
            ("callback", 1),
            ("part", 2, 1, 503),
            ("part", 2, 2, 200),
            ("callback", 2),
            ("complete",),
        ]
        files_client.files_complete.assert_called_once_with(
            "owner",
            "repo",
            identifier="upload-id",
            data={"upload_id": "upload-id", "complete": True},
        )


class TestMultiPartUploadMemory:
    """A regression guard for overlapping multipart request bodies."""

    def test_peak_traced_memory_stays_below_two_parts(self, tmp_path):
        filepath = tmp_path / "package.raw"
        with filepath.open("wb") as output:
            output.truncate(2 * CHUNK_SIZE + 1)

        records = []
        events = []
        files_client = Mock()
        files_client.files_complete.side_effect = lambda *args, **kwargs: events.append(
            ("complete",)
        )

        class RecordingSession:
            def put(self, url, *, headers, data, params):
                request = requests.PreparedRequest()
                request.prepare(
                    method="PUT", url=url, headers=headers, data=data, params=params
                )
                records.append(
                    {
                        "part_number": params["part_number"],
                        "content_length": int(request.headers["Content-Length"]),
                        "sha256": hashlib.sha256(request.body).hexdigest(),
                    }
                )
                response = requests.Response()
                response.status_code = 200
                response.request = request
                return response

        callbacks = []

        def callback():
            callbacks.append(None)
            events.append(("callback", len(callbacks)))

        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            with (
                patch.object(
                    files_api,
                    "create_requests_session",
                    return_value=RecordingSession(),
                ),
                patch.object(files_api, "get_files_api", return_value=files_client),
            ):
                multi_part_upload_file(
                    Mock(credential=None),
                    "https://upload.example.invalid/parts",
                    "owner",
                    "repo",
                    str(filepath),
                    callback,
                    "upload-id",
                )
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        expected_sizes = [CHUNK_SIZE, CHUNK_SIZE, 1]
        assert [record["part_number"] for record in records] == [1, 2, 3]
        assert [record["content_length"] for record in records] == expected_sizes
        assert [record["sha256"] for record in records] == [
            _sha256_zeros(size) for size in expected_sizes
        ]
        assert callbacks == [None, None, None]
        assert events[-1] == ("complete",)
        assert peak < 2 * CHUNK_SIZE
        files_client.files_complete.assert_called_once()
