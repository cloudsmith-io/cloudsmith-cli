"""Tests for the repository privileges API client."""

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
OWNER = "test-org"
REPO = "test-repo"
PRIVILEGES_URL = f"{API_HOST}/repos/{OWNER}/{REPO}/privileges"


@pytest.fixture(autouse=True)
def _setup_api(monkeypatch):
    """Initialise the SDK Configuration and stub keyring lookups.

    See ``core/tests/test_metadata.py`` for why each of these is required:
    initialise_api() registers retry attributes the REST client expects, and
    keyring is stubbed so tests never touch the real OS keyring.
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


class TestListRepoPrivileges:
    @httpretty.activate(allow_net_connect=False)
    def test_success_returns_privileges(self):
        body = {
            "privileges": [
                {"privilege": "Admin", "team": None, "user": None, "service": "ci"},
                {"privilege": "Read", "team": "eng", "user": None, "service": None},
            ]
        }
        httpretty.register_uri(
            httpretty.GET,
            PRIVILEGES_URL,
            body=json.dumps(body),
            status=200,
            content_type="application/json",
        )

        privileges = repos.list_repo_privileges(OWNER, REPO)

        assert privileges == body["privileges"]

        sent = _last_request()
        assert sent.headers.get("X-Api-Key") == "test-api-key"
        assert sent.path == f"/repos/{OWNER}/{REPO}/privileges"

    @httpretty.activate(allow_net_connect=False)
    def test_empty_privileges_list(self):
        httpretty.register_uri(
            httpretty.GET,
            PRIVILEGES_URL,
            body=json.dumps({"privileges": []}),
            status=200,
            content_type="application/json",
        )

        privileges = repos.list_repo_privileges(OWNER, REPO)

        assert privileges == []

    @httpretty.activate(allow_net_connect=False)
    def test_404_raises_api_exception(self):
        httpretty.register_uri(
            httpretty.GET,
            PRIVILEGES_URL,
            body=json.dumps({"detail": "Not found."}),
            status=404,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            repos.list_repo_privileges(OWNER, REPO)

        assert exc_info.value.status == 404
        assert exc_info.value.detail == "Not found."


class TestUpdateRepoPrivileges:
    @httpretty.activate(allow_net_connect=False)
    def test_success_sends_patch_with_privileges_body(self):
        httpretty.register_uri(
            httpretty.PATCH,
            PRIVILEGES_URL,
            body="",
            status=204,
        )

        result = repos.update_repo_privileges(
            OWNER, REPO, [{"privilege": "Write", "team": "eng"}]
        )

        assert result is None

        sent = _last_request()
        assert sent.method == "PATCH"
        assert json.loads(sent.body) == {
            "privileges": [{"privilege": "Write", "team": "eng"}]
        }

    @httpretty.activate(allow_net_connect=False)
    def test_422_raises_api_exception_with_fields(self):
        message = "bogus is not valid for privilege - must be one of ['Admin', 'Write', 'Read']"
        body = {
            "detail": "Invalid data.",
            "fields": {"privilege": [message]},
        }
        httpretty.register_uri(
            httpretty.PATCH,
            PRIVILEGES_URL,
            body=json.dumps(body),
            status=422,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            repos.update_repo_privileges(
                OWNER, REPO, [{"privilege": "bogus", "team": "eng"}]
            )

        assert exc_info.value.status == 422
        assert exc_info.value.fields == {"privilege": [message]}


class TestReplaceRepoPrivileges:
    @httpretty.activate(allow_net_connect=False)
    def test_success_sends_put_with_privileges_body(self):
        httpretty.register_uri(
            httpretty.PUT,
            PRIVILEGES_URL,
            body="",
            status=204,
        )

        result = repos.replace_repo_privileges(
            OWNER, REPO, [{"privilege": "Write", "team": "eng"}]
        )

        assert result is None

        sent = _last_request()
        assert sent.method == "PUT"
        assert json.loads(sent.body) == {
            "privileges": [{"privilege": "Write", "team": "eng"}]
        }

    @httpretty.activate(allow_net_connect=False)
    def test_empty_list_revokes_everything(self):
        httpretty.register_uri(
            httpretty.PUT,
            PRIVILEGES_URL,
            body="",
            status=204,
        )

        repos.replace_repo_privileges(OWNER, REPO, [])

        assert json.loads(_last_request().body) == {"privileges": []}

    @httpretty.activate(allow_net_connect=False)
    def test_422_raises_api_exception_with_fields(self):
        message = "Invalid team(s) specified ['no-such-team']"
        httpretty.register_uri(
            httpretty.PUT,
            PRIVILEGES_URL,
            body=json.dumps(
                {"detail": "Invalid input.", "fields": {"privileges": message}}
            ),
            status=422,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            repos.replace_repo_privileges(
                OWNER, REPO, [{"privilege": "Read", "team": "no-such-team"}]
            )

        assert exc_info.value.status == 422
        assert exc_info.value.fields == {"privileges": message}
