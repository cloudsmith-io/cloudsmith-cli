"""Cloudsmith API - Initialisation."""
from __future__ import absolute_import, print_function, unicode_literals

import cloudsmith_api


def initialise_api(
        debug=False, host=None, key=None, proxy=None, user_agent=None):
    """Initialise the API."""
    config = cloudsmith_api.Configuration()
    config.debug = debug
    config.host = host if host else config.host
    config.proxy = proxy if proxy else config.proxy
    config.user_agent = user_agent
    set_api_key(config, key)
    return config


def set_api_key(config, key):
    """Configure a new API key."""
    if not key and 'X-Api-Key' in config.api_key:
        del config.api_key['X-Api-Key']
    else:
        config.api_key['X-Api-Key'] = key
