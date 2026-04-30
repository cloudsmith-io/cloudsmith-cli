"""API - Package metadata (v2) endpoints."""

import json
from typing import Any, Optional, Union

import cloudsmith_api

from .. import ratelimits, utils
from ..pagination import PageInfo
from ..rest import RestClient
from .exceptions import catch_raise_api_exception

SOURCE_KIND_VALUES = {
    "unknown": 0,
    "system": 1,
    "ecosystem": 2,
    "customer": 3,
    "third_party": 4,
}

CLASSIFICATION_VALUES = {
    "unknown": 0,
    "intrinsic": 1,
    "upstream": 2,
    "security": 3,
    "provenance": 4,
    "sbom": 5,
    "generic": 6,
}


def _normalise_enum(value, mapping, name):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name} value: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"Invalid {name} value: {value!r}")
        try:
            return int(text)
        except ValueError:
            pass
        key = text.lower().replace("-", "_")
        try:
            return mapping[key]
        except KeyError:
            valid = ", ".join(sorted(mapping))
            raise ValueError(
                f"Invalid {name} {value!r}. Expected an integer or one of: {valid}."
            )
    raise ValueError(f"Invalid {name} type: {type(value).__name__}")


def normalise_source_kind(value):
    """Coerce a MetadataSourceKind name or integer to its integer value."""
    return _normalise_enum(value, SOURCE_KIND_VALUES, "source_kind")


def normalise_classification(value):
    """Coerce a MetadataClassification name or integer to its integer value."""
    return _normalise_enum(value, CLASSIFICATION_VALUES, "classification")


class _MetadataApi:
    """Small client for metadata endpoints not yet present in cloudsmith_api."""

    def __init__(self):
        self.config = cloudsmith_api.Configuration()
        self.rest_client = RestClient(
            error_retry_cb=getattr(self.config, "error_retry_cb", None),
            respect_retry_after_header=getattr(self.config, "rate_limit", True),
        )


def get_metadata_api():
    """Get the metadata API client."""
    return _MetadataApi()


def _build_url(config, *parts):
    host = (config.host or "").rstrip("/")
    suffix = "/".join(p.strip("/") for p in parts if p)
    return f"{host}/v2/{suffix}/"


def _build_headers(config):
    """Build request headers from the configured cloudsmith_api.Configuration.

    Mirrors the auth resolution performed by core/api/init.py: an Authorization
    header (SSO bearer or Basic) takes precedence; otherwise we fall back to
    the X-Api-Key header.
    """
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    headers.update(getattr(config, "headers", None) or {})

    user_agent = getattr(config, "user_agent", None)
    if user_agent:
        headers["User-Agent"] = user_agent

    if headers.get("Authorization"):
        headers.pop("X-Api-Key", None)
    else:
        api_key = (config.api_key or {}).get("X-Api-Key")
        if api_key:
            headers["X-Api-Key"] = api_key

    return headers


def _request(client, method, *path_parts, query_params=None, body=None):
    url = _build_url(client.config, *path_parts)

    with catch_raise_api_exception():
        response = client.rest_client.request(
            method,
            url,
            query_params=query_params,
            headers=_build_headers(client.config),
            body=body,
        )

    ratelimits.maybe_rate_limit(client, response.getheaders())
    return response


def _response_json(response):
    if not response.data:
        return {}
    return json.loads(response.data)


def list_metadata(
    package_slug_perm: str,
    *,
    source_kind: Optional[Union[int, str]] = None,
    classification: Optional[Union[int, str]] = None,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
):
    """List metadata entries attached to a package.

    `source_kind` and `classification` may be supplied as either an integer
    or the matching enum name (case-insensitive); both are converted to the
    integer the v2 API expects before the request is issued.

    Returns a (results, PageInfo) tuple.
    """
    client = get_metadata_api()
    api_kwargs = {}

    source_kind_value = normalise_source_kind(source_kind)
    if source_kind_value is not None:
        api_kwargs["source_kind"] = source_kind_value

    classification_value = normalise_classification(classification)
    if classification_value is not None:
        api_kwargs["classification"] = classification_value

    api_kwargs.update(utils.get_page_kwargs(page=page, page_size=page_size))

    response = _request(
        client,
        "GET",
        "packages",
        package_slug_perm,
        "metadata",
        query_params=api_kwargs or None,
    )

    payload = _response_json(response)
    results = payload.get("results", payload) if isinstance(payload, dict) else payload
    page_info = PageInfo.from_headers(response.getheaders())
    return results, page_info


def create_metadata(
    package_slug_perm: str,
    *,
    content: Any,
    content_type: str,
    source_identity: str,
):
    """Attach a new metadata entry to a package."""
    client = get_metadata_api()
    body = {
        "content": content,
        "content_type": content_type,
        "source_identity": source_identity,
    }
    response = _request(
        client, "POST", "packages", package_slug_perm, "metadata", body=body
    )
    return _response_json(response)


def update_metadata(
    package_slug_perm: str,
    metadata_slug_perm: str,
    *,
    content: Any = None,
    source_identity: Optional[str] = None,
):
    """Patch an existing customer-owned metadata entry.

    Only `content` and `source_identity` are mutable; the v2 API rejects
    attempts to change `content_type`. Fields left as None are omitted from
    the patch body so existing values are preserved.
    """
    client = get_metadata_api()
    body = {}
    if content is not None:
        body["content"] = content
    if source_identity is not None:
        body["source_identity"] = source_identity
    if not body:
        raise ValueError(
            "update_metadata requires at least one of content or source_identity"
        )

    response = _request(
        client,
        "PATCH",
        "packages",
        package_slug_perm,
        "metadata",
        metadata_slug_perm,
        body=body,
    )
    return _response_json(response)


def delete_metadata(package_slug_perm: str, metadata_slug_perm: str):
    """Remove a customer-owned metadata entry from a package."""
    client = get_metadata_api()
    _request(
        client,
        "DELETE",
        "packages",
        package_slug_perm,
        "metadata",
        metadata_slug_perm,
    )
