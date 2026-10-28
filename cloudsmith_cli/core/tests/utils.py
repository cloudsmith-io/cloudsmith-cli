"""Local HTTP support for multipart upload tests and benchmarks."""

import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

READ_SIZE = 64 * 1024


class _UploadHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_PUT(self):
        query = parse_qs(urlparse(self.path).query)
        part_number = int(query["part_number"][0])
        content_length = int(self.headers["Content-Length"])
        attempt = self.server.attempts.get(part_number, 0) + 1
        self.server.attempts[part_number] = attempt
        digest = hashlib.sha256()
        received = 0
        self.connection.settimeout(self.server.read_timeout)
        while received < content_length:
            try:
                block = self.rfile.read(min(READ_SIZE, content_length - received))
            except TimeoutError:
                self.server.events.append(
                    ("body_timeout", part_number, attempt, received)
                )
                self.close_connection = True
                return
            if not block:
                self.server.events.append(("body_eof", part_number, attempt, received))
                self.close_connection = True
                return
            digest.update(block)
            received += len(block)

        record = {
            "path": self.path,
            "part_number": part_number,
            "attempt": attempt,
            "content_length": content_length,
            "received": received,
            "sha256": digest.hexdigest(),
            "auth": self.headers.get("X-Api-Key"),
            "transfer_encoding": self.headers.get("Transfer-Encoding"),
        }
        response = self.server.response_for_request
        status, headers, body = response(record) if response else (200, {}, b"")
        record["status"] = status
        self.server.records.append(record)
        self.server.events.append(("part", part_number, attempt, status))

        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        if "Content-Length" not in headers:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


@contextlib.contextmanager
def upload_server():
    """Run a local receiver that records each PUT without retaining its body."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UploadHandler)
    server.daemon_threads = True
    server.records = []
    server.events = []
    server.attempts = {}
    server.read_timeout = 2
    server.response_for_request = None
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
