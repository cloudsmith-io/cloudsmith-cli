# -*- coding: utf-8 -*-
"""Cloudsmith API - Initialisation."""
from __future__ import absolute_import, print_function, unicode_literals

import base64

import cloudsmith_api
import six

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
    """Initialise the API."""
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

    if headers:
        if "Authorization" in config.headers:
            encoded = config.headers["Authorization"].split(" ")[1]
            decoded = base64.b64decode(encoded)
            values = decoded.decode("utf-8")
            config.username, config.password = values.split(":")

    set_api_key(config, key)
    return config


def get_api_client(cls):
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
        for k, v in six.iteritems(headers):
            client.api_client.set_default_header(k, v)

    return client


def set_api_key(config, key):
    """Configure a new API key."""
    if not key and "X-Api-Key" in config.api_key:
        del config.api_key["X-Api-Key"]
    else:
        config.api_key["X-Api-Key"] = key
