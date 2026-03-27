"""Cloudsmith API - Initialisation."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Callable

import click
import cloudsmith_sdk

from ...cli import saml
from .. import keyring
from .exceptions import ApiException

DEFAULT_API_HOST = "https://api.cloudsmith.io"


@dataclass
class CliConfig:
    """CLI configuration — replaces cloudsmith_api.Configuration singleton."""

    # Connection
    host: str = DEFAULT_API_HOST
    debug: bool = False
    proxy: str | None = None
    verify_ssl: bool = True
    user_agent: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    # Auth (resolved state)
    api_key: dict[str, str] = field(default_factory=dict)
    username: str = ""
    password: str = ""

    # Rate limiting
    rate_limit: bool = True
    rate_limit_callback: Callable | None = None

    # Retry
    error_retry_max: int | None = None
    error_retry_backoff: float | None = None
    error_retry_codes: Any | None = None
    error_retry_cb: Callable | None = None

    def get_basic_auth_token(self) -> str:
        """Get HTTP basic authentication header string."""
        if self.username or self.password:
            credentials = f"{self.username}:{self.password}".encode()
            return "Basic " + base64.b64encode(credentials).decode("utf-8")
        return ""


_cli_config: CliConfig | None = None


def get_cli_config() -> CliConfig:
    """Get the current CLI configuration."""
    if _cli_config is None:
        return CliConfig()
    return _cli_config


def initialise_api(
    debug=False,
    host=None,
    key=None,
    proxy=None,
    ssl_verify=True,
    user_agent=None,
    headers=None,
    rate_limit=True,
    rate_limit_callback=None,
    error_retry_max=None,
    error_retry_backoff=None,
    error_retry_codes=None,
    error_retry_cb=None,
    access_token=None,
):
    """Initialise the CLI configuration."""
    # pylint: disable=too-many-arguments
    global _cli_config

    config = CliConfig(
        debug=debug,
        host=host if host else DEFAULT_API_HOST,
        proxy=proxy or None,
        verify_ssl=ssl_verify if ssl_verify is not None else True,
        user_agent=user_agent,
        headers=headers if headers else {},
        rate_limit=rate_limit if rate_limit is not None else True,
        rate_limit_callback=rate_limit_callback,
        error_retry_max=error_retry_max,
        error_retry_backoff=error_retry_backoff,
        error_retry_codes=error_retry_codes,
        error_retry_cb=error_retry_cb,
    )

    # Use directly provided access token (e.g. from SSO callback),
    # or fall back to keyring lookup if enabled.
    if not access_token:
        access_token = keyring.get_access_token(config.host)

    if access_token:
        auth_header = config.headers.get("Authorization")

        # overwrite auth header if empty or is basic auth without username or password
        if not auth_header or auth_header == config.get_basic_auth_token():
            refresh_token = keyring.get_refresh_token(config.host)

            try:
                if keyring.should_refresh_access_token(config.host):
                    new_access_token, new_refresh_token = saml.refresh_access_token(
                        config.host,
                        access_token,
                        refresh_token,
                        session=saml.create_configured_session(
                            proxy=config.proxy,
                            ssl_verify=config.verify_ssl,
                            user_agent=config.user_agent,
                            headers=config.headers,
                        ),
                    )
                    keyring.store_sso_tokens(
                        config.host, new_access_token, new_refresh_token
                    )
                    # Use the new tokens
                    access_token = new_access_token
            except ApiException:
                keyring.update_refresh_attempted_at(config.host)

                click.secho(
                    "An error occurred when attempting to refresh your SSO access token. To refresh this session, run 'cloudsmith auth'",
                    fg="yellow",
                    err=True,
                )

                # Clear access_token to prevent using expired token
                access_token = None

                # Fall back to API key auth if available
                if key:
                    click.secho(
                        "Falling back to API key authentication.",
                        fg="yellow",
                        err=True,
                    )
                    config.api_key["X-Api-Key"] = key

            # Only use SSO token if refresh didn't fail
            if access_token:
                config.headers["Authorization"] = f"Bearer {access_token}"

                if config.debug:
                    click.echo("SSO access token config value set")
    elif key:
        config.api_key["X-Api-Key"] = key

        if config.debug:
            click.echo("User API key config value set")

    auth_header = headers and config.headers.get("Authorization")
    if auth_header and " " in auth_header:
        auth_type, encoded = auth_header.split(" ", 1)
        if auth_type == "Basic":
            decoded = base64.b64decode(encoded)
            values = decoded.decode("utf-8")
            config.username, config.password = values.split(":")

            if config.debug:
                click.echo("Username and password config values set")

    _cli_config = config
    return config


def _resolve_sdk_auth(
    config: CliConfig,
) -> (
    cloudsmith_sdk.BasicAuth
    | cloudsmith_sdk.BearerTokenAuth
    | cloudsmith_sdk.ApiTokenAuth
    | None
):
    """Resolve SDK auth from CLI configuration."""
    auth_header = config.headers.get("Authorization")
    if auth_header and " " in auth_header:
        auth_type, token = auth_header.split(" ", 1)
        if auth_type == "Bearer":
            return cloudsmith_sdk.BearerTokenAuth(token=token)
        elif auth_type == "Basic":
            return cloudsmith_sdk.BasicAuth(
                username=config.username, password=config.password
            )
    if "X-Api-Key" in config.api_key:
        return cloudsmith_sdk.ApiTokenAuth(token=config.api_key["X-Api-Key"])

    return None


def get_new_api_client() -> cloudsmith_sdk.CloudsmithClient:
    """Get an API client (with configuration)."""
    config = get_cli_config()

    return cloudsmith_sdk.CloudsmithClient(
        base_url=config.host,
        auth=_resolve_sdk_auth(config),
        user_agent=config.user_agent,
        extra_headers=config.headers or None,
        rate_limit=cloudsmith_sdk.RateLimitConfig(
            callback=config.rate_limit_callback if config.rate_limit else None
        ),
    )


def unset_api_key():
    """Unset the API key."""
    config = get_cli_config()
    config.api_key.pop("X-Api-Key", None)
