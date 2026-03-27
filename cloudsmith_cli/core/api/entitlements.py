"""API - entitlements endpoints."""

import cloudsmith_sdk
from cloudsmith_sdk.models import (
    RepositoryTokenRequest,
    RepositoryTokenRequestPatch,
    RepositoryTokenSyncRequest,
)

from .exceptions import catch_raise_api_exception
from .init import get_new_api_client


def get_entitlements_api() -> cloudsmith_sdk.EntitlementsApi:
    """Get the entitlements API client."""
    return get_new_api_client().entitlements


def list_entitlements(owner, repo, page_size, show_tokens):
    """Get a list of entitlements on a repository."""
    client = get_entitlements_api()

    with catch_raise_api_exception():
        return client.list(
            owner=owner,
            repo=repo,
            page_size=page_size,
            show_tokens=show_tokens,
        )


def create_entitlement(owner, repo, name, token, show_tokens):
    """Create an entitlement in a repository."""
    client = get_entitlements_api()

    repository_token_create_request = RepositoryTokenRequest()
    if name is not None:
        repository_token_create_request.name = name

    if token is not None:
        repository_token_create_request.token = token
    with catch_raise_api_exception():
        token = client.create(
            owner=owner,
            repo=repo,
            show_tokens=show_tokens,
            body=repository_token_create_request,
        )

    return token


def delete_entitlement(owner, repo, identifier):
    """Delete an entitlement from a repository."""
    client = get_entitlements_api()

    with catch_raise_api_exception():
        client.delete(owner=owner, repo=repo, identifier=identifier)


def update_entitlement(owner, repo, identifier, name, token, show_tokens):
    """Update an entitlement in a repository."""
    client = get_entitlements_api()

    repository_token_update_request = RepositoryTokenRequestPatch()
    if name is not None:
        repository_token_update_request.name = name

    if token is not None:
        repository_token_update_request.token = token

    with catch_raise_api_exception():
        token = client.partial_update(
            owner=owner,
            repo=repo,
            identifier=identifier,
            show_tokens=show_tokens,
            body=repository_token_update_request,
        )

    return token


def refresh_entitlement(owner, repo, identifier, show_tokens):
    """Refresh an entitlement in a repository."""
    client = get_entitlements_api()

    with catch_raise_api_exception():
        token = client.refresh(
            owner=owner, repo=repo, identifier=identifier, show_tokens=show_tokens
        )

    return token


def sync_entitlements(owner, repo, source, show_tokens):
    """Sync entitlements from another repository."""
    client = get_entitlements_api()
    repository_token_sync_request = RepositoryTokenSyncRequest(source=source)

    with catch_raise_api_exception():
        token_sync = client.sync(
            owner=owner,
            repo=repo,
            show_tokens=show_tokens,
            body=repository_token_sync_request,
        )

    return token_sync


def restrict_entitlement(owner, repo, identifier, data):
    """Restrict entitlement token using provided restrictions."""

    client = get_entitlements_api()

    repository_token_update = RepositoryTokenRequestPatch.from_dict(data)

    with catch_raise_api_exception():
        token = client.partial_update(
            owner=owner, repo=repo, identifier=identifier, body=repository_token_update
        )

    return token
