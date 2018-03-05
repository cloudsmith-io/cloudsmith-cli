"""Cloudsmith API - Initialisation."""
from __future__ import absolute_import, print_function, unicode_literals

import base64

import cloudsmith_api
import six


def initialise_api(
        debug=False, host=None, key=None, proxy=None, user_agent=None,
        headers=None):
    """Initialise the API."""
    config = cloudsmith_api.Configuration()
    config.debug = debug
    config.host = host if host else config.host
    config.proxy = proxy if proxy else config.proxy
    config.user_agent = user_agent
    config.headers = headers
    if headers:
        if 'Authorization' in config.headers:
            encoded = config.headers['Authorization'].split(' ')[1]
            decoded = base64.b64decode(encoded)
            values = decoded.decode('utf-8')
            config.username, config.password = values.split(':')
    set_api_key(config, key)
    return config


def get_api_client(cls):
    """Get an API client (with configuration)."""
    config = cloudsmith_api.Configuration()
    client = cls()

    user_agent = getattr(config, 'user_agent', None)
    if user_agent:
        client.api_client.user_agent = user_agent

    headers = getattr(config, 'headers', None)
    if headers:
        for k, v in six.iteritems(headers):
            client.api_client.set_default_header(k, v)

    return client


def set_api_key(config, key):
    """Configure a new API key."""
    if not key and 'X-Api-Key' in config.api_key:
        del config.api_key['X-Api-Key']
    else:
        config.api_key['X-Api-Key'] = key
