"""API - Package metadata (v2) endpoints."""

from typing import Any

from .. import utils
from ..credentials.models import CredentialResult
from ..pagination import PageInfo
from . import v2


def list_metadata(
    package_slug_perm: str,
    *,
    credential: CredentialResult | None,
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
    client = v2.get_client(credential)
    api_kwargs = {}

    source_kind_value = str(source_kind).strip().lower() if source_kind else ""
    if source_kind_value:
        api_kwargs["source_kind"] = source_kind_value
    classification_value = str(classification).strip().lower() if classification else ""
    if classification_value:
        api_kwargs["classification"] = classification_value

    api_kwargs.update(utils.get_page_kwargs(page=page, page_size=page_size))

    response = v2.request(
        client,
        "GET",
        "metadata",
        "packages",
        package_slug_perm,
        query_params=api_kwargs or None,
    )

    payload = v2.response_json(response)
    results = payload.get("results", payload) if isinstance(payload, dict) else payload
    page_info = PageInfo.from_headers(response.getheaders())
    return results, page_info


def get_metadata(
    package_slug_perm: str,
    metadata_slug_perm: str,
    *,
    credential: CredentialResult | None,
):
    """Retrieve a single metadata entry attached to a package."""
    client = v2.get_client(credential)
    response = v2.request(
        client,
        "GET",
        "metadata",
        "packages",
        package_slug_perm,
        metadata_slug_perm,
    )
    return v2.response_json(response)


def create_metadata(
    package_slug_perm: str,
    *,
    credential: CredentialResult | None,
    content: Any,
    content_type: str,
    source_identity: str,
):
    """Attach a new metadata entry to a package."""
    client = v2.get_client(credential)
    body = {
        "content": content,
        "content_type": content_type,
        "source_identity": source_identity,
    }
    response = v2.request(
        client, "POST", "metadata", "packages", package_slug_perm, body=body
    )
    return v2.response_json(response)


def update_metadata(
    package_slug_perm: str,
    metadata_slug_perm: str,
    *,
    credential: CredentialResult | None,
    content: Any = None,
    source_identity: str | None = None,
):
    """Patch an existing customer-owned metadata entry.

    Only `content` and `source_identity` are mutable; the v2 API rejects
    attempts to change `content_type`. Fields left as None are omitted from
    the patch body so existing values are preserved.
    """
    client = v2.get_client(credential)
    body = {}
    if content is not None:
        body["content"] = content
    if source_identity is not None:
        body["source_identity"] = source_identity
    if not body:
        raise ValueError(
            "update_metadata requires at least one of content or source_identity"
        )

    response = v2.request(
        client,
        "PATCH",
        "metadata",
        "packages",
        package_slug_perm,
        metadata_slug_perm,
        body=body,
    )
    return v2.response_json(response)


def delete_metadata(
    package_slug_perm: str,
    metadata_slug_perm: str,
    *,
    credential: CredentialResult | None,
):
    """Remove a customer-owned metadata entry from a package."""
    client = v2.get_client(credential)
    v2.request(
        client,
        "DELETE",
        "metadata",
        "packages",
        package_slug_perm,
        metadata_slug_perm,
    )


def validate_metadata(
    *, credential: CredentialResult | None, content: Any, content_type: str
):
    """Validate a metadata payload against its content type schema.

    Hits POST /v2/metadata/validate/ which checks shape and schema without
    persisting. Server returns 200 on success and 422 on validation failure.
    """
    client = v2.get_client(credential)
    body = {"content": content, "content_type": content_type}
    v2.request(client, "POST", "metadata", "validate", body=body)
    return True
