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


@dataclass
class CredentialResult:
    """Result from a successful credential resolution."""

    api_key: str
    source_name: str
    source_detail: str | None = None
    auth_type: Literal["api_key", "bearer"] = "api_key"
