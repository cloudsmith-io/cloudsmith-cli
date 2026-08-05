"""Credential data models for the Cloudsmith CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import requests


@dataclass
class CredentialContext:
    """Context passed to credential providers during resolution.

    Separate per-source fields allow the chain to evaluate sources in priority
    order without conflating them. Populated from Click options in
    ``resolve_credentials``.
    """

    session: requests.Session | None = None
    api_key_from_flag: str | None = None
    api_key_from_env: str | None = None
    api_key_from_file: str | None = None
    api_host: str = "https://api.cloudsmith.io"
    creds_file_path: str | None = None
    profile: str | None = None
    debug: bool = False
    keyring_refresh_failed: bool = False
    oidc_audience: str | None = None
    org: str | None = None
    oidc_service_slug: str | None = None
    oidc_discovery_disabled: bool = False
    oidc_detector_order: str | None = None
    oidc_disabled_detectors: frozenset[str] = frozenset()


@dataclass
class CredentialResult:
    """Result from a successful credential resolution."""

    api_key: str
    source_name: str
    source_detail: str | None = None
    auth_type: Literal["api_key", "bearer"] = "api_key"

    def auth_headers(self) -> dict[str, str]:
        """Return the headers that authenticate a raw request with this credential.

        The two headers are not interchangeable: a raw JWT in ``X-Api-Key`` is
        rejected outright, aborting the auth chain before the SSO
        authenticators run.
        """
        if self.auth_type == "bearer":
            return {"Authorization": f"Bearer {self.api_key}"}

        return {"X-Api-Key": self.api_key}
