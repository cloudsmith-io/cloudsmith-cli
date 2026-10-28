"""Tests for the files API upload helpers."""

import hashlib
import tracemalloc
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests
from cloudsmith_api.rest import ApiException as SdkApiException

from ..api import files as files_api
from ..api.exceptions import ApiException
from ..api.files import CHUNK_SIZE, multi_part_upload_file, upload_file
from ..credentials.models import CredentialResult
from .utils import upload_server


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


class TestMultiPartUploadStreaming:
    """Part bodies stay bounded and remain replayable by Requests."""

    def test_exact_parts_replay_after_redirect_and_retry(self, tmp_path, monkeypatch):
        filepath = tmp_path / "package.raw"
        filepath.write_bytes(b"abcdefgh")
        monkeypatch.setattr(files_api, "CHUNK_SIZE", 4)
        _configure_upload_session(monkeypatch)

        with upload_server() as server:

            def respond(record):
                if record["part_number"] == 1 and record["attempt"] == 1:
                    query = record["path"].partition("?")[2]
                    return (
                        307,
                        {
                            "Location": (
                                f"http://127.0.0.1:{server.server_port}"
                                f"/redirected?{query}"
                            )
                        },
                        b"",
                    )
                if record["part_number"] == 2 and record["attempt"] == 1:
                    return 503, {}, b"retry"
                return 200, {}, b""

            server.response_for_request = respond
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

    def test_short_source_aborts_without_completing(self, tmp_path, monkeypatch):
        filepath = tmp_path / "package.raw"
        filepath.write_bytes(b"x" * 43)
        monkeypatch.setattr(files_api, "CHUNK_SIZE", 43)

        with upload_server() as server:
            server.read_timeout = 0.5
            files_client = Mock()
            files_client.files_complete.side_effect = lambda *args, **kwargs: (
                server.events.append(("complete",))
            )
            session = requests.Session()
            session.trust_env = False

            class TruncatingSession:
                def put(self, url, *, data, **kwargs):
                    with filepath.open("r+b") as source:
                        source.truncate(7)
                    return session.put(url, data=data, **kwargs)

            try:
                with (
                    patch.object(
                        files_api,
                        "create_requests_session",
                        return_value=TruncatingSession(),
                    ),
                    patch.object(files_api, "get_files_api", return_value=files_client),
                    pytest.raises(ApiException) as raised,
                ):
                    multi_part_upload_file(
                        Mock(credential=None),
                        f"http://127.0.0.1:{server.server_port}/parts",
                        "owner",
                        "repo",
                        str(filepath),
                        lambda: None,
                        "upload-id",
                    )
            finally:
                session.close()

        assert raised.value.status == 0
        assert "upload source ended before the current part" in raised.value.detail
        assert not any(event[0] == "body_timeout" for event in server.events)
        assert not any(event[0] == "complete" for event in server.events)
        files_client.files_complete.assert_not_called()


class TestMultiPartUploadMemory:
    """A native pytest heap benchmark guards against whole-part buffering."""

    def test_streaming_keeps_peak_memory_below_one_part(self, tmp_path, monkeypatch):
        filepath = tmp_path / "package.raw"
        with filepath.open("wb") as output:
            output.truncate(CHUNK_SIZE + 1)
        _configure_upload_session(monkeypatch)

        with upload_server() as server:
            files_client = Mock()
            files_client.files_complete.side_effect = lambda *args, **kwargs: (
                server.events.append(("complete",))
            )
            callbacks = []

            def callback():
                callbacks.append(None)
                server.events.append(("callback", len(callbacks)))

            tracemalloc.start()
            try:
                tracemalloc.reset_peak()
                with patch.object(
                    files_api, "get_files_api", return_value=files_client
                ):
                    multi_part_upload_file(
                        Mock(credential=None),
                        f"http://127.0.0.1:{server.server_port}/parts",
                        "owner",
                        "repo",
                        str(filepath),
                        callback,
                        "upload-id",
                    )
                _current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()

        assert [record["part_number"] for record in server.records] == [1, 2]
        assert [record["content_length"] for record in server.records] == [
            CHUNK_SIZE,
            1,
        ]
        assert [record["received"] for record in server.records] == [CHUNK_SIZE, 1]
        assert [record["status"] for record in server.records] == [200, 200]
        assert [record["sha256"] for record in server.records] == [
            _sha256_zeros(CHUNK_SIZE),
            _sha256_zeros(1),
        ]
        assert all(record["transfer_encoding"] is None for record in server.records)
        assert callbacks == [None, None]
        assert server.events[-1] == ("complete",)
        print(f"peak traced memory: {peak} bytes")
        assert peak < CHUNK_SIZE
        files_client.files_complete.assert_called_once()
