"""Credential data models for the Cloudsmith CLI."""

from __future__ import annotations

from dataclasses import dataclass

import requests


@dataclass
class CredentialContext:
    """Context passed to credential providers during resolution.

    All values are populated directly from Click options / ``opts``.
    """

    session: requests.Session | None = None
    api_key: str | None = None
    api_host: str = "https://api.cloudsmith.io"
    creds_file_path: str | None = None
    profile: str | None = None
    debug: bool = False
    keyring_refresh_failed: bool = False


@dataclass
class CredentialResult:
    """Result from a successful credential resolution."""

    api_key: str
    source_name: str
    source_detail: str | None = None
    auth_type: str = "api_key"
