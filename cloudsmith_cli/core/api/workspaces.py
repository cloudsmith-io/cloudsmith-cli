# Copyright 2026 Cloudsmith Ltd
"""API - Workspace (v2) endpoints."""

from ..credentials.models import CredentialResult
from . import v2


def list_domains(workspace: str, *, credential: CredentialResult | None) -> list[dict]:
    """List the domains that serve a Workspace, most-preferred first.

    The list holds Cloudsmith-owned and custom domains. The endpoint pages
    with a ``Link`` header, so this follows each ``next`` link to the end.
    """
    client = v2.get_client(credential)
    response = v2.request(client, "GET", "workspaces", workspace, "domains")
    domains = v2.response_json(response).get("results", [])

    while next_url := response.response.links.get("next", {}).get("url"):
        response = v2.request_url(client, "GET", next_url)
        domains.extend(v2.response_json(response).get("results", []))

    return domains
