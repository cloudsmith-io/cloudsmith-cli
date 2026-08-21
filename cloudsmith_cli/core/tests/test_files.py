"""Tests for the files API upload helpers."""

from unittest.mock import Mock, patch

import pytest
import requests

from ..api.exceptions import ApiException
from ..api.files import _s3_error_detail, multi_part_upload_file
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


class TestS3ErrorDetail:
    """A pre-signed S3 upload failure is an XML body, not the JSON
    catch_raise_api_exception() parses, so ApiException.detail stayed unset
    and the CLI could only ever show the generic HTTP status phrase.
    """

    def test_extracts_message_from_s3_error_xml(self):
        body = (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b"<Error><Code>ExpiredToken</Code>"
            b"<Message>The provided token has expired.</Message>"
            b"<Token-0>...</Token-0></Error>"
        )

        assert _s3_error_detail(body) == "The provided token has expired."

    @pytest.mark.parametrize("body", [None, b"", b"not xml at all", b"<Error/>"])
    def test_returns_none_when_no_message_present(self, body):
        assert _s3_error_detail(body) is None

    def test_multi_part_upload_failure_carries_s3_message_as_detail(self, tmp_path):
        filepath = tmp_path / "package.raw"
        filepath.write_bytes(b"payload")

        response = Mock(
            status_code=400,
            content=b"<Error><Message>The provided token has expired.</Message></Error>",
            headers={},
        )
        response.raise_for_status.side_effect = requests.HTTPError(response=response)

        session = Mock()
        session.put.return_value = response

        with (
            patch(
                "cloudsmith_cli.core.api.files.create_requests_session",
                return_value=session,
            ),
            patch("cloudsmith_cli.core.api.files.get_files_api"),
            pytest.raises(ApiException) as exc_info,
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

        assert exc_info.value.detail == "The provided token has expired."
