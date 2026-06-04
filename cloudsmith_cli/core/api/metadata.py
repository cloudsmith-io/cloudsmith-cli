"""API - Package metadata (v2) endpoints."""

import json
from typing import Any

import cloudsmith_api

from .. import ratelimits, utils
from ..pagination import PageInfo
from ..rest import RestClient
from .exceptions import catch_raise_api_exception


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
    source_kind: str | None = None,
    classification: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
):
    """List metadata entries attached to a package.

    `source_kind` and `classification` are sent as the lowercased enum name
    the v2 API expects; the authoritative backend validates the value and
    surfaces a 4xx for anything it does not recognise.

    Returns a (results, PageInfo) tuple.
    """
    client = get_metadata_api()
    api_kwargs = {}

    if source_kind:
        api_kwargs["source_kind"] = str(source_kind).strip().lower()
    if classification:
        api_kwargs["classification"] = str(classification).strip().lower()

    api_kwargs.update(utils.get_page_kwargs(page=page, page_size=page_size))

    response = _request(
        client,
        "GET",
        "metadata",
        "packages",
        package_slug_perm,
        query_params=api_kwargs or None,
    )

    payload = _response_json(response)
    results = payload.get("results", payload) if isinstance(payload, dict) else payload
    page_info = PageInfo.from_headers(response.getheaders())
    return results, page_info


def get_metadata(package_slug_perm: str, metadata_slug_perm: str):
    """Retrieve a single metadata entry attached to a package."""
    client = get_metadata_api()
    response = _request(
        client,
        "GET",
        "metadata",
        "packages",
        package_slug_perm,
        metadata_slug_perm,
    )
    return _response_json(response)


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
        client, "POST", "metadata", "packages", package_slug_perm, body=body
    )
    return _response_json(response)


def update_metadata(
    package_slug_perm: str,
    metadata_slug_perm: str,
    *,
    content: Any = None,
    source_identity: str | None = None,
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
        "metadata",
        "packages",
        package_slug_perm,
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
        "metadata",
        "packages",
        package_slug_perm,
        metadata_slug_perm,
    )


def validate_metadata(*, content: Any, content_type: str):
    """Validate a metadata payload against its content type schema.

    Hits POST /v2/metadata/validate/ which checks shape and schema without
    persisting. Server returns 200 on success and 422 on validation failure.
    """
    client = get_metadata_api()
    body = {"content": content, "content_type": content_type}
    _request(client, "POST", "metadata", "validate", body=body)
    return True
