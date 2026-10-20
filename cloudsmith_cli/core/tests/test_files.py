"""Tests for the files API upload helpers."""

from unittest.mock import Mock, patch

import pytest
import requests
from cloudsmith_api.rest import ApiException as SdkApiException

from ..api.exceptions import ApiException
from ..api.files import multi_part_upload_file, upload_file
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
    rather than opts.api_key, which OIDC and SSO never populate.
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


class TestUploadTransportErrors:
    """A request that never reaches the upload host fails like an API call."""

    @staticmethod
    def upload(tmp_path, send):
        filepath = tmp_path / "package.raw"
        filepath.write_bytes(b"payload")
        error = requests.ConnectionError("offline")
        session = Mock(**{"post.side_effect": error, "put.side_effect": error})
        with (
            patch(
                "cloudsmith_cli.core.api.files.create_requests_session",
                return_value=session,
            ),
            patch("cloudsmith_cli.core.api.files.get_files_api"),
            pytest.raises(ApiException) as raised,
        ):
            send(str(filepath))
        return raised.value, error

    def test_single_upload(self, tmp_path):
        exc, error = self.upload(
            tmp_path,
            lambda path: upload_file("https://upload.example.invalid/", {}, path),
        )

        assert exc.status == 0
        assert exc.detail == "ConnectionError\noffline"
        assert exc.__cause__ is error

    def test_multi_part_upload(self, tmp_path):
        exc, error = self.upload(
            tmp_path,
            lambda path: multi_part_upload_file(
                Mock(credential=None),
                upload_url="https://upload.example.invalid/parts",
                owner="owner",
                repo="repo",
                filepath=path,
                callback=lambda: None,
                upload_id="upload-id",
            ),
        )

        assert exc.status == 0
        assert exc.__cause__ is error

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
