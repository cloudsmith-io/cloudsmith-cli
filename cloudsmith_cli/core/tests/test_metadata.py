"""Tests for the v2 package metadata API client."""

import json

import cloudsmith_api
import httpretty
import httpretty.core
import pytest

from .. import keyring
from ..api import metadata
from ..api.exceptions import ApiException
from ..api.init import initialise_api

API_HOST = "https://api.cloudsmith.io"
PKG = "pkg-slug"
META = "meta-slug"
LIST_URL = f"{API_HOST}/v2/packages/{PKG}/metadata/"
DETAIL_URL = f"{API_HOST}/v2/packages/{PKG}/metadata/{META}/"


@pytest.fixture(autouse=True)
def _setup_api(monkeypatch):
    """Initialise the SDK Configuration and stub keyring lookups.

    initialise_api() registers custom retry attributes on cloudsmith_api.Configuration
    that create_requests_session expects, and the metadata module reads host/auth
    off the same Configuration singleton. Keyring is stubbed so we never touch the
    user's real SSO tokens during a test run.
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
    initialise_api(host=API_HOST, key="test-api-key")


def _last_request():
    return httpretty.last_request()


class TestNormalisers:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (3, 3),
            ("3", 3),
            ("customer", 3),
            ("CUSTOMER", 3),
            ("Third-Party", 4),
            ("third_party", 4),
        ],
    )
    def test_source_kind(self, value, expected):
        assert metadata.normalise_source_kind(value) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (6, 6),
            ("generic", 6),
            ("GENERIC", 6),
            ("PROVENANCE", 4),
        ],
    )
    def test_classification(self, value, expected):
        assert metadata.normalise_classification(value) == expected

    def test_invalid_source_kind_name(self):
        with pytest.raises(ValueError, match="Invalid source_kind"):
            metadata.normalise_source_kind("not-a-kind")

    def test_invalid_classification_name(self):
        with pytest.raises(ValueError, match="Invalid classification"):
            metadata.normalise_classification("nope")

    def test_invalid_type(self):
        with pytest.raises(ValueError):
            metadata.normalise_source_kind(3.14)

    def test_bool_rejected(self):
        with pytest.raises(ValueError):
            metadata.normalise_source_kind(True)


class TestListMetadata:
    @httpretty.activate(allow_net_connect=False)
    def test_success_returns_results_and_page_info(self):
        body = {"results": [{"slug_perm": "abc", "content_type": "application/json"}]}
        httpretty.register_uri(
            httpretty.GET,
            LIST_URL,
            body=json.dumps(body),
            status=200,
            content_type="application/json",
            adding_headers={
                "X-Pagination-Count": "1",
                "X-Pagination-Page": "1",
                "X-Pagination-PageSize": "30",
                "X-Pagination-PageTotal": "1",
            },
        )

        results, page_info = metadata.list_metadata(PKG)

        assert results == body["results"]
        assert page_info.is_valid
        assert page_info.count == 1

        sent = _last_request()
        assert sent.headers.get("X-Api-Key") == "test-api-key"
        assert sent.headers.get("Accept") == "application/json"

    @httpretty.activate(allow_net_connect=False)
    def test_filters_normalised_to_integers(self):
        httpretty.register_uri(
            httpretty.GET,
            LIST_URL,
            body=json.dumps({"results": []}),
            status=200,
            content_type="application/json",
        )

        metadata.list_metadata(
            PKG, source_kind="customer", classification="GENERIC", page=2, page_size=50
        )

        qs = _last_request().querystring  # pylint: disable=no-member
        assert qs["source_kind"] == ["3"]
        assert qs["classification"] == ["6"]
        assert qs["page"] == ["2"]
        assert qs["page_size"] == ["50"]

    @httpretty.activate(allow_net_connect=False)
    def test_non_positive_page_options_omitted(self):
        httpretty.register_uri(
            httpretty.GET,
            LIST_URL,
            body=json.dumps({"results": []}),
            status=200,
            content_type="application/json",
        )

        metadata.list_metadata(PKG, page=0, page_size=0)

        qs = _last_request().querystring  # pylint: disable=no-member
        assert "page" not in qs
        assert "page_size" not in qs

    @httpretty.activate(allow_net_connect=False)
    def test_404_raises_api_exception(self):
        httpretty.register_uri(
            httpretty.GET,
            LIST_URL,
            body=json.dumps({"detail": "Not found."}),
            status=404,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            metadata.list_metadata(PKG)

        assert exc_info.value.status == 404
        assert exc_info.value.detail == "Not found."

    @httpretty.activate(allow_net_connect=False)
    def test_422_raises_with_fields(self):
        body = {
            "detail": "Invalid query parameters.",
            "fields": {"source_kind": ["Not a valid choice."]},
        }
        httpretty.register_uri(
            httpretty.GET,
            LIST_URL,
            body=json.dumps(body),
            status=422,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            metadata.list_metadata(PKG, source_kind=3)

        assert exc_info.value.status == 422
        assert exc_info.value.fields == {"source_kind": ["Not a valid choice."]}


class TestCreateMetadata:
    @httpretty.activate(allow_net_connect=False)
    def test_success_posts_required_fields(self):
        created = {
            "slug_perm": "new-slug",
            "content_type": "application/json",
            "source_identity": "cloudsmith-cli@1.16.0",
        }
        httpretty.register_uri(
            httpretty.POST,
            LIST_URL,
            body=json.dumps(created),
            status=201,
            content_type="application/json",
        )

        result = metadata.create_metadata(
            PKG,
            content={"foo": "bar"},
            content_type="application/json",
            source_identity="cloudsmith-cli@1.16.0",
        )

        assert result == created
        sent_body = json.loads(_last_request().body)
        assert sent_body == {
            "content": {"foo": "bar"},
            "content_type": "application/json",
            "source_identity": "cloudsmith-cli@1.16.0",
        }

    @httpretty.activate(allow_net_connect=False)
    def test_404_when_package_unknown(self):
        httpretty.register_uri(
            httpretty.POST,
            LIST_URL,
            body=json.dumps({"detail": "Not found."}),
            status=404,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            metadata.create_metadata(
                PKG,
                content={"x": 1},
                content_type="application/json",
                source_identity="customer:test",
            )
        assert exc_info.value.status == 404

    @httpretty.activate(allow_net_connect=False)
    def test_422_carries_field_errors(self):
        body = {
            "detail": "Validation failed.",
            "fields": {"content": ["Content must be a JSON object."]},
        }
        httpretty.register_uri(
            httpretty.POST,
            LIST_URL,
            body=json.dumps(body),
            status=422,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            metadata.create_metadata(
                PKG,
                content="not-an-object",
                content_type="application/json",
                source_identity="customer:test",
            )

        assert exc_info.value.status == 422
        assert exc_info.value.detail == "Validation failed."
        assert exc_info.value.fields == {"content": ["Content must be a JSON object."]}


class TestUpdateMetadata:
    @httpretty.activate(allow_net_connect=False)
    def test_success_sends_only_provided_fields(self):
        updated = {"slug_perm": META, "source_identity": "customer:new"}
        httpretty.register_uri(
            httpretty.PATCH,
            DETAIL_URL,
            body=json.dumps(updated),
            status=200,
            content_type="application/json",
        )

        result = metadata.update_metadata(PKG, META, source_identity="customer:new")

        assert result == updated
        assert json.loads(_last_request().body) == {"source_identity": "customer:new"}

    @httpretty.activate(allow_net_connect=False)
    def test_rejects_empty_patch(self):
        with pytest.raises(ValueError):
            metadata.update_metadata(PKG, META)

    @httpretty.activate(allow_net_connect=False)
    def test_404_on_unknown_metadata(self):
        httpretty.register_uri(
            httpretty.PATCH,
            DETAIL_URL,
            body=json.dumps({"detail": "Not found."}),
            status=404,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            metadata.update_metadata(PKG, META, content={"k": "v"})
        assert exc_info.value.status == 404

    @httpretty.activate(allow_net_connect=False)
    def test_422_when_changing_content_type(self):
        body = {
            "detail": "Validation failed.",
            "fields": {
                "content_type": "content_type cannot be changed after creation."
            },
        }
        httpretty.register_uri(
            httpretty.PATCH,
            DETAIL_URL,
            body=json.dumps(body),
            status=422,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            metadata.update_metadata(PKG, META, content={"k": "v"})

        assert exc_info.value.status == 422
        assert exc_info.value.fields == {
            "content_type": "content_type cannot be changed after creation."
        }


class TestDeleteMetadata:
    @httpretty.activate(allow_net_connect=False)
    def test_success_returns_none(self):
        httpretty.register_uri(httpretty.DELETE, DETAIL_URL, status=204)

        assert metadata.delete_metadata(PKG, META) is None
        assert _last_request().method == "DELETE"

    @httpretty.activate(allow_net_connect=False)
    def test_404_raises(self):
        httpretty.register_uri(
            httpretty.DELETE,
            DETAIL_URL,
            body=json.dumps({"detail": "Not found."}),
            status=404,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            metadata.delete_metadata(PKG, META)
        assert exc_info.value.status == 404

    @httpretty.activate(allow_net_connect=False)
    def test_422_raises(self):
        body = {
            "detail": "Cannot delete.",
            "fields": {"non_field_errors": ["Metadata is read-only."]},
        }
        httpretty.register_uri(
            httpretty.DELETE,
            DETAIL_URL,
            body=json.dumps(body),
            status=422,
            content_type="application/json",
        )

        with pytest.raises(ApiException) as exc_info:
            metadata.delete_metadata(PKG, META)

        assert exc_info.value.status == 422
        assert exc_info.value.fields == {"non_field_errors": ["Metadata is read-only."]}


class TestAuthHeaders:
    @staticmethod
    def _override_config(monkeypatch, *, api_key=None, headers=None):
        cfg = cloudsmith_api.Configuration()
        cfg.api_key = api_key if api_key is not None else cfg.api_key
        cfg.headers = headers if headers is not None else cfg.headers
        monkeypatch.setattr(cloudsmith_api.Configuration, "_default", cfg)

    @httpretty.activate(allow_net_connect=False)
    def test_sso_authorization_header_takes_precedence(self, monkeypatch):
        self._override_config(
            monkeypatch,
            api_key={"X-Api-Key": "test-api-key"},
            headers={"Authorization": "Bearer sso-token"},
        )
        httpretty.register_uri(
            httpretty.GET,
            LIST_URL,
            body=json.dumps({"results": []}),
            status=200,
            content_type="application/json",
        )

        metadata.list_metadata(PKG)

        sent = _last_request()
        assert sent.headers.get("Authorization") == "Bearer sso-token"
        assert sent.headers.get("X-Api-Key") is None

    @httpretty.activate(allow_net_connect=False)
    def test_extra_config_headers_are_preserved(self, monkeypatch):
        self._override_config(
            monkeypatch,
            headers={"X-Custom-Header": "custom-value"},
        )
        httpretty.register_uri(
            httpretty.GET,
            LIST_URL,
            body=json.dumps({"results": []}),
            status=200,
            content_type="application/json",
        )

        metadata.list_metadata(PKG)

        sent = _last_request()
        assert sent.headers.get("X-Custom-Header") == "custom-value"
        assert sent.headers.get("X-Api-Key") == "test-api-key"
