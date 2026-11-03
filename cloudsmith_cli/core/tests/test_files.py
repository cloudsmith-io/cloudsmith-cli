"""Tests for the files API upload helpers."""

import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import pytest
import requests
from cloudsmith_api.rest import ApiException as SdkApiException

from ..api.exceptions import ApiException
from ..api.files import (
    UPLOAD_TIMEOUT_SECONDS,
    _RewindableMultipartBody,
    multi_part_upload_file,
    upload_file,
)
from ..credentials.models import CredentialResult


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

    def test_missing_file(self, tmp_path):
        with pytest.raises(ApiException) as raised:
            upload_file("https://upload.example.invalid/", {}, str(tmp_path / "gone"))

        assert raised.value.status == 0

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


class FailOnceHandler(BaseHTTPRequestHandler):
    """Answer the first upload with first_status and record each body."""

    timeout = 1
    first_status = 503
    bodies = []

    def do_POST(self):
        expected = int(self.headers["Content-Length"])
        try:
            body = self.rfile.read(expected)
        except TimeoutError:
            body = b""
        self.bodies.append((expected, body))
        status = self.first_status if len(self.bodies) == 1 else 204
        if len(body) < expected:
            status = 400
        self.send_response(status)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


class TestUploadRetry:
    @pytest.mark.parametrize("first_status", [503, 307])
    def test_retry_resends_the_whole_body(self, tmp_path, first_status):
        filepath = tmp_path / "package.raw"
        filepath.write_bytes(b"payload" * 1000)
        FailOnceHandler.first_status = first_status
        FailOnceHandler.bodies = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), FailOnceHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        files_api = Mock(**{"api_client.user_agent": "cloudsmith-cli-test"})
        try:
            with patch(
                "cloudsmith_cli.core.api.files.get_files_api", return_value=files_api
            ):
                upload_file(
                    f"http://127.0.0.1:{server.server_port}/",
                    {"key": "value"},
                    str(filepath),
                )
        finally:
            server.shutdown()
            server.server_close()

        assert FailOnceHandler.bodies[1] == FailOnceHandler.bodies[0]
        assert b"payload" * 1000 in FailOnceHandler.bodies[1][1]

    def test_body_rewinds_only_to_the_start(self, tmp_path):
        filepath = tmp_path / "package.raw"
        filepath.write_bytes(b"payload")
        with filepath.open("rb") as file_obj:
            body = _RewindableMultipartBody(
                [("file", ("package.raw", file_obj))], file_obj, callback=None
            )

            with pytest.raises(io.UnsupportedOperation):
                body.seek(1)

    def test_upload_sends_a_timeout(self, tmp_path):
        filepath = tmp_path / "package.raw"
        filepath.write_bytes(b"payload")
        session = Mock(**{"post.return_value.raise_for_status.return_value": None})
        with (
            patch(
                "cloudsmith_cli.core.api.files.create_requests_session",
                return_value=session,
            ),
            patch("cloudsmith_cli.core.api.files.get_files_api"),
        ):
            upload_file("https://upload.example.invalid/", {}, str(filepath))

        assert session.post.call_args.kwargs["timeout"] == UPLOAD_TIMEOUT_SECONDS
