"""Tests for the files API upload helpers."""

from functools import partial
from unittest.mock import Mock, patch

import httpretty
import httpretty.core
import pytest
import requests
from cloudsmith_api.rest import ApiException as SdkApiException

from ..api.exceptions import ApiException
from ..api.files import multi_part_upload_file, upload_file
from ..credentials.models import CredentialResult
from ..session import create_requests_session


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


@httpretty.activate(allow_net_connect=False)
def test_upload_retries_a_gateway_error(tmp_path, monkeypatch):
    """A second upload of the same file is safe, so the CLI retries it."""
    # urllib3 2.x calls shutdown() on a retry, and httpretty does not fake it.
    monkeypatch.setattr(
        httpretty.core.fakesock.socket,
        "shutdown",
        lambda self, how: None,
        raising=False,
    )
    filepath = tmp_path / "package.raw"
    filepath.write_bytes(b"payload")
    upload_url = "http://upload.example.invalid/"
    requests_seen = []

    def respond(request, uri, response_headers):
        requests_seen.append(uri)
        return [504, response_headers, ""]

    httpretty.register_uri(httpretty.POST, upload_url, body=respond)
    files_api = Mock(**{"api_client.user_agent": "cloudsmith-cli"})

    with (
        patch(
            "cloudsmith_cli.core.api.files.create_requests_session",
            partial(create_requests_session, retries=2, backoff_factor=0),
        ),
        patch("cloudsmith_cli.core.api.files.get_files_api", return_value=files_api),
        pytest.raises(ApiException),
    ):
        upload_file(upload_url, {}, str(filepath))

    assert len(requests_seen) == 3
