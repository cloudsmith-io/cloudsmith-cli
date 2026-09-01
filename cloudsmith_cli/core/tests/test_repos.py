"""Tests for the repository GPG key API client."""

import json

import httpretty
import httpretty.core
import pytest

from .. import keyring
from ..api import repos
from ..api.exceptions import ApiException
from ..api.init import initialise_api
from ..credentials.models import CredentialResult

API_HOST = "https://api.cloudsmith.io"
OWNER = "my-org"
REPO = "my-repo"
GPG_URL = f"{API_HOST}/repos/{OWNER}/{REPO}/gpg/"
GPG_REGENERATE_URL = f"{API_HOST}/repos/{OWNER}/{REPO}/gpg/regenerate/"

# Not a real GPG key - armor-shaped fixture content, deliberately not using
# the literal "-----BEGIN ... PRIVATE KEY-----" marker so secret-scanning
# tooling (e.g. the detect-private-key pre-commit hook) doesn't flag it.
FAKE_GPG_KEY_MATERIAL = "fake-armored-gpg-private-key-material-for-tests-only"


@pytest.fixture(autouse=True)
def _setup_api(monkeypatch):
    """Initialise the SDK Configuration and stub keyring lookups.

    Mirrors the metadata API test setup: initialise_api() registers custom
    retry attributes on cloudsmith_api.Configuration that create_requests_session
    expects, and keyring is stubbed so we never touch the user's real SSO tokens
    during a test run.
    """
    monkeypatch.setattr(keyring, "get_access_token", lambda host: None)
    monkeypatch.setattr(keyring, "get_refresh_token", lambda host: None)
    monkeypatch.setattr(keyring, "should_refresh_access_token", lambda host: False)
    monkeypatch.setattr(
        httpretty.core.fakesock.socket,
        "shutdown",
        lambda self, how: None,
        raising=False,
    )
    initialise_api(
        host=API_HOST,
        credential=CredentialResult(
            api_key="test-api-key",
            source_name="test",
            auth_type="api_key",
        ),
    )


def _last_request():
    return httpretty.last_request()


def _gpg_key_body(**overrides):
    body = {
        "active": True,
        "comment": "my-repo GPG key",
        "created_at": "2026-01-01T00:00:00Z",
        "default": True,
        "fingerprint": "AAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
        "fingerprint_short": "EEEE5555",
        "public_key": "-----BEGIN PGP PUBLIC KEY BLOCK-----\n...\n-----END PGP PUBLIC KEY BLOCK-----",
    }
    body.update(overrides)
    return body


class TestListRepoGpgKey:
    @httpretty.activate(allow_net_connect=False)
    def test_success_returns_gpg_key_dict(self):
        body = _gpg_key_body()
        httpretty.register_uri(
            httpretty.GET,
            GPG_URL,
            body=json.dumps(body),
            status=200,
            content_type="application/json",
        )

        result = repos.list_repo_gpg_key(OWNER, REPO)

        assert result["fingerprint"] == body["fingerprint"]
        assert result["fingerprint_short"] == body["fingerprint_short"]
        assert result["active"] is True
        assert result["default"] is True

        sent = _last_request()
        assert sent.headers.get("X-Api-Key") == "test-api-key"

    @httpretty.activate(allow_net_connect=False)
    def test_404_raises_api_exception(self):
        httpretty.register_uri(
            httpretty.GET,
            GPG_URL,
            body=json.dumps({"detail": "Not found."}),
            status=404,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            repos.list_repo_gpg_key(OWNER, REPO)

        assert exc_info.value.status == 404


class TestCreateRepoGpgKey:
    @httpretty.activate(allow_net_connect=False)
    def test_success_sends_private_key_and_passphrase(self):
        body = _gpg_key_body()
        httpretty.register_uri(
            httpretty.POST,
            GPG_URL,
            body=json.dumps(body),
            status=201,
            content_type="application/json",
        )

        result = repos.create_repo_gpg_key(
            OWNER,
            REPO,
            gpg_private_key=FAKE_GPG_KEY_MATERIAL,
            gpg_passphrase="s3cret",
        )

        assert result["fingerprint"] == body["fingerprint"]

        sent = _last_request()
        sent_body = json.loads(sent.body)
        assert sent_body["gpg_private_key"] == FAKE_GPG_KEY_MATERIAL
        assert sent_body["gpg_passphrase"] == "s3cret"

    @httpretty.activate(allow_net_connect=False)
    def test_omits_passphrase_when_none(self):
        body = _gpg_key_body()
        httpretty.register_uri(
            httpretty.POST,
            GPG_URL,
            body=json.dumps(body),
            status=201,
            content_type="application/json",
        )

        repos.create_repo_gpg_key(OWNER, REPO, gpg_private_key=FAKE_GPG_KEY_MATERIAL)

        sent = _last_request()
        sent_body = json.loads(sent.body)
        assert "gpg_passphrase" not in sent_body

    @httpretty.activate(allow_net_connect=False)
    def test_422_raises_api_exception_with_fields(self):
        httpretty.register_uri(
            httpretty.POST,
            GPG_URL,
            body=json.dumps(
                {
                    "detail": "Invalid GPG key.",
                    "fields": {"gpg_private_key": ["Not a valid GPG private key."]},
                }
            ),
            status=422,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            repos.create_repo_gpg_key(OWNER, REPO, gpg_private_key="not-a-real-key")

        assert exc_info.value.status == 422
        assert "gpg_private_key" in exc_info.value.fields


class TestRegenerateRepoGpgKey:
    @httpretty.activate(allow_net_connect=False)
    def test_success_returns_new_gpg_key(self):
        body = _gpg_key_body(
            fingerprint="1111AAAA2222BBBB3333CCCC4444DDDD5555EEEE",
            fingerprint_short="5555EEEE",
        )
        httpretty.register_uri(
            httpretty.POST,
            GPG_REGENERATE_URL,
            body=json.dumps(body),
            status=200,
            content_type="application/json",
        )

        result = repos.regenerate_repo_gpg_key(OWNER, REPO)

        assert result["fingerprint"] == body["fingerprint"]
        assert result["fingerprint_short"] == body["fingerprint_short"]

    @httpretty.activate(allow_net_connect=False)
    def test_404_raises_api_exception(self):
        httpretty.register_uri(
            httpretty.POST,
            GPG_REGENERATE_URL,
            body=json.dumps({"detail": "Not found."}),
            status=404,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            repos.regenerate_repo_gpg_key(OWNER, REPO)

        assert exc_info.value.status == 404
