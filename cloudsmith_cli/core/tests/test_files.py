"""Tests for the files API upload helpers."""

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


class TestMultiPartUploadMemory:
    """A regression guard for overlapping multipart request bodies."""

    def test_peak_traced_memory_stays_below_two_parts(self, tmp_path):
        filepath = tmp_path / "package.raw"
        with filepath.open("wb") as output:
            output.truncate(2 * CHUNK_SIZE + 1)
        files_client = Mock()

        def put(url, data, **kwargs):
            response = requests.Response()
            response.status_code = 200
            response.request = SimpleNamespace(body=data)
            return response

        session = SimpleNamespace(put=put)
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            with (
                patch.object(
                    files_api, "create_requests_session", return_value=session
                ),
                patch.object(files_api, "get_files_api", return_value=files_client),
            ):
                multi_part_upload_file(
                    Mock(credential=None),
                    "https://upload.example.invalid/parts",
                    "owner",
                    "repo",
                    str(filepath),
                    lambda: None,
                    "upload-id",
                )
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert peak < 2 * CHUNK_SIZE
        files_client.files_complete.assert_called_once()
