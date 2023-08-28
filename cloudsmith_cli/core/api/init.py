"""Cloudsmith API - Initialisation."""

import base64
from typing import Type, TypeVar

import cloudsmith_api

from ..rest import RestClient


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
    config.headers = headers
    config.rate_limit = rate_limit
    config.rate_limit_callback = rate_limit_callback
    config.error_retry_max = error_retry_max
    config.error_retry_backoff = error_retry_backoff
    config.error_retry_codes = error_retry_codes
    config.error_retry_cb = error_retry_cb
    config.verify_ssl = ssl_verify
    config.client_side_validation = False

    if headers:
        if "Authorization" in config.headers:
            encoded = config.headers["Authorization"].split(" ")[1]
            decoded = base64.b64decode(encoded)
            values = decoded.decode("utf-8")
            config.username, config.password = values.split(":")

    if key:
        config.api_key["X-Api-Key"] = key

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
