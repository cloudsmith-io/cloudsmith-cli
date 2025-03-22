"""Cloudsmith API - Initialisation."""

import base64
from typing import Type, TypeVar

import click
import cloudsmith_api

from ...cli import saml
from .. import keyring
from ..rest import RestClient
from .exceptions import ApiException


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
):
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
    config.client_side_validation = False

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
                        session=saml.create_configured_session(config),
                    )
                    keyring.store_sso_tokens(
                        config.host, new_access_token, new_refresh_token
                    )
            except ApiException:
                keyring.update_refresh_attempted_at(config.host)

                click.secho(
                    "An error occurred when attempting to refresh your SSO access token. To refresh this session, run 'cloudsmith auth'",
                    fg="yellow",
                )

                # try falling back to API key auth if refresh fails
                if key:
                    config.api_key["X-Api-Key"] = key

            config.headers["Authorization"] = "Bearer {access_token}".format(
                access_token=access_token
            )

            if config.debug:
                click.echo("SSO access token config value set")
    elif key:
        config.api_key["X-Api-Key"] = key

        if config.debug:
            click.echo("User API key config value set")

    if headers:
        if "Authorization" in config.headers:
            auth_type, encoded = config.headers["Authorization"].split(" ")
            if auth_type == "Basic":
                decoded = base64.b64decode(encoded)
                values = decoded.decode("utf-8")
                config.username, config.password = values.split(":")

                if config.debug:
                    click.echo("Username and password config values set")

    # Important! Some of the attributes set above (e.g. error_retry_max) are not
    # present in the cloudsmith_api.Configuration class declaration.
    # By calling the set_default() method, we ensure that future instances of that
    # class will include those attributes, and their (default) values.
    cloudsmith_api.Configuration.set_default(config)

    return config


T = TypeVar("T")


def get_api_client(cls: Type[T]) -> T:
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
