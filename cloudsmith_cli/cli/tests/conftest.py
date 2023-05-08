# -*- coding: utf-8 -*-
import os

import click.testing
import pytest


def _get_env_var_or_skip(key):
    """Return the environment variable value if set, otherwise skip the test."""
    value = os.environ.get(key)
    if not value:
        pytest.skip("%s not provided" % key)
    return value


@pytest.fixture()
def runner():
    """Return a CliRunner with which to run Commands."""
    return click.testing.CliRunner(mix_stderr=False)


@pytest.fixture()
def username():
    """Return the PYTEST_CLOUDSMITH_USERNAME value."""
    return _get_env_var_or_skip("PYTEST_CLOUDSMITH_USERNAME")


@pytest.fixture()
def password():
    """Return the PYTEST_CLOUDSMITH_PASSWORD value."""
    return _get_env_var_or_skip("PYTEST_CLOUDSMITH_PASSWORD")


@pytest.fixture()
def api_key():
    """Return the PYTEST_CLOUDSMITH_API_KEY value."""
    return _get_env_var_or_skip("PYTEST_CLOUDSMITH_API_KEY")


@pytest.fixture()
def organization():
    """Return the PYTEST_CLOUDSMITH_ORGANIZATION value.
    This is the name of the organization to use for pytest runs.
    """
    return _get_env_var_or_skip("PYTEST_CLOUDSMITH_ORGANIZATION")


@pytest.fixture()
def api_host():
    """Return the PYTEST_CLOUDSMITH_API_HOST value."""
    return _get_env_var_or_skip("PYTEST_CLOUDSMITH_API_HOST")


@pytest.fixture()
def set_api_host_env_var(api_host):
    """Set the CLOUDSMITH_API_HOST environment variable."""
    os.environ["CLOUDSMITH_API_HOST"] = api_host


@pytest.fixture()
def set_api_key_env_var(api_key):
    """Set the CLOUDSMITH_API_KEY environment variable."""
    os.environ["CLOUDSMITH_API_KEY"] = api_key
