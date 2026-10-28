"""Cloudsmith API - Initialisation."""

import base64
from typing import TypeVar

import click
import cloudsmith_api

from ..rest import RestClient


def _basic_auth_credentials(encoded: str) -> tuple[str, str]:
    """Decode a Basic auth token into a username and password."""
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except ValueError as exc:
        raise click.BadParameter(
            "Authorization header needs to be Authorization=username:password",
            param_hint="'--api-headers'",
        ) from exc
    return username, password


def initialise_api(
    debug=False,
    host=None,
    credential=None,
    proxy=None,
    ssl_verify=True,
    ssl_verify_strict=True,
    user_agent=None,
    headers=None,
    rate_limit=True,
    rate_limit_callback=None,
    error_retry_max=None,
    error_retry_backoff=None,
    error_retry_codes=None,
    error_retry_cb=None,
) -> cloudsmith_api.Configuration:
    """Initialise the cloudsmith_api.Configuration."""
    # FIXME: pylint: disable=too-many-arguments
    config = cloudsmith_api.Configuration()
    config.debug = debug
    config.host = host if host else config.host
    config.proxy = proxy if proxy else config.proxy
    config.user_agent = user_agent
    config.headers = headers if headers else {}
    config.rate_limit = rate_limit
    config.rate_limit_callback = rate_limit_callback
    config.error_retry_max = error_retry_max
    config.error_retry_backoff = error_retry_backoff
    config.error_retry_codes = error_retry_codes
    config.error_retry_cb = error_retry_cb
    config.verify_ssl = ssl_verify
    config.ssl_verify_strict = ssl_verify_strict
    config.client_side_validation = False

    if credential:
        if credential.auth_type == "bearer":
            # set_default() makes api_key sticky across calls, so an X-Api-Key
            # left by an earlier credential would ride along with the bearer token.
            config.api_key.pop("X-Api-Key", None)
            config.headers["Authorization"] = f"Bearer {credential.api_key}"
            if config.debug:
                click.echo("SAML access token config value set")
        else:
            config.api_key["X-Api-Key"] = credential.api_key
            if config.debug:
                click.echo("User API key config value set")

    auth_header = headers and config.headers.get("Authorization")
    if auth_header and " " in auth_header:
        auth_type, encoded = auth_header.split(" ", 1)
        if auth_type == "Basic":
            config.username, config.password = _basic_auth_credentials(encoded)

            if config.debug:
                click.echo("Username and password config values set")

    # Important! Some of the attributes set above (e.g. error_retry_max) are not
    # present in the cloudsmith_api.Configuration class declaration.
    # By calling the set_default() method, we ensure that future instances of that
    # class will include those attributes, and their (default) values.
    cloudsmith_api.Configuration.set_default(config)

    return config


T = TypeVar("T")


def get_api_client(cls: type[T]) -> T:
    """Get an API client (with configuration)."""
    config = cloudsmith_api.Configuration()
    client = cls()
    client.config = config
    client.api_client.rest_client = RestClient(
        error_retry_cb=getattr(config, "error_retry_cb", None),
        respect_retry_after_header=getattr(config, "rate_limit", True),
    )

    user_agent = getattr(config, "user_agent", None)
    if user_agent:
        client.api_client.user_agent = user_agent

    headers = getattr(config, "headers", None)
    if headers:
        for k, v in headers.items():
            client.api_client.set_default_header(k, v)

    return client


def unset_api_key():
    """Unset the API key."""
    config = cloudsmith_api.Configuration()

    try:
        del config.api_key["X-Api-Key"]
    except KeyError:
        pass

    if hasattr(cloudsmith_api.Configuration, "set_default"):
        cloudsmith_api.Configuration.set_default(config)
