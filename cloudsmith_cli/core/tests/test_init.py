from unittest.mock import patch

import pytest
from cloudsmith_api import Configuration

from ...cli import saml
from .. import keyring
from ..api.init import initialise_api


@pytest.fixture
def mocked_get_access_token():
    with patch.object(
        keyring, "get_access_token", return_value="dummy_access_token"
    ) as get_access_token_mock:
        yield get_access_token_mock


@pytest.fixture
def mocked_get_refresh_token():
    with patch.object(
        keyring, "get_refresh_token", return_value="dummy_refresh_token"
    ) as get_refresh_token_mock:
        yield get_refresh_token_mock


@pytest.fixture
def mocked_should_refresh_access_token():
    with patch.object(
        keyring, "should_refresh_access_token", return_value=False
    ) as should_refresh_access_token_mock:
        yield should_refresh_access_token_mock


@pytest.fixture
def mocked_refresh_access_token():
    with patch.object(
        saml,
        "refresh_access_token",
        return_value=("new_access_token", "new_refresh_token"),
    ) as refresh_access_token_mock:
        yield refresh_access_token_mock


@pytest.fixture
def mocked_store_sso_tokens():
    with patch.object(keyring, "store_sso_tokens") as store_sso_tokens_mock:
        yield store_sso_tokens_mock


@pytest.fixture
def mocked_update_refresh_attempted_at():
    with patch.object(
        keyring, "update_refresh_attempted_at"
    ) as update_refresh_attempted_at_mock:
        yield update_refresh_attempted_at_mock


class TestInitialiseApi:
    def setup_class(cls):  # pylint: disable=no-self-argument
        # For the purposes of these tests, we need to explcitly call set_default(None) at the
        # outset because other tests in the suite may have called initialise_api() already.
        # Resetting Configuration._default to None here effectively reverts the
        # Configuration class to its vanilla, unmodified behaviour/state.
        Configuration.set_default(None)

    def test_initialise_api_sets_cloudsmith_api_config_default(
        self, mocked_get_access_token
    ):
        """Assert that the extra attributes we add to the cloudsmith_cli.Configuration class
        are present on newly-created instances of that class.
        """
        mocked_get_access_token.return_value = None

        # Read and understand the Configuration class's initialiser.
        # Notice how the _default class attribute is used if not None.
        # https://github.com/cloudsmith-io/cloudsmith-api/blob/57963fff5b7818783b3d87246495275545d505df/bindings/python/src/cloudsmith_api/configuration.py#L32-L40

        # There are a number of attributes which we automagically add to instances of
        # cloudsmith_api.Configuration().
        extra_config_attrs = [
            "rate_limit",
            "error_retry_max",
            "error_retry_backoff",
            "error_retry_codes",
            "error_retry_cb",
        ]

        # We do that in our initialise_api() function by
        # (i) creating a new instance of Configuration and adding attributes/values to it.
        # (ii) calling the cloudsmith_api.Configuration.set_default(config) classmethod.

        # Because Configuration._default is None, a newly-created instance of
        # cloudsmith_api.Configuration() should not have any other attributes than those
        # in the auto-generated swagger-codegen class declaration.
        new_config_before_initialise = Configuration()
        assert all(
            not hasattr(new_config_before_initialise, attr)
            for attr in extra_config_attrs
        )

        # Our initialise_api() function should create an instance of
        # cloudsmith_api.Configuration, add some extra attributes to it, set default values
        # and pass that instance to cloudsmith_api.Configuration.set_default().
        config_from_initialise = initialise_api()
        assert all(hasattr(config_from_initialise, attr) for attr in extra_config_attrs)
        assert (
            Configuration._default  # pylint: disable=protected-access
            is config_from_initialise
        )

        # After which point, any newly-created instances of cloudsmith_api.Configuration
        # should automagically include copies of those "extra" attributes we assigned to
        # the "default" config instance in our initialise_api() function.
        new_config_after_initialise = Configuration()
        assert all(
            hasattr(new_config_after_initialise, attr) for attr in extra_config_attrs
        )
        assert (
            Configuration._default  # pylint: disable=protected-access
            is not new_config_after_initialise
        )

    def test_initialise_api_with_refreshable_access_token_set(
        self,
        mocked_get_access_token,
        mocked_get_refresh_token,
        mocked_should_refresh_access_token,
        mocked_refresh_access_token,
        mocked_store_sso_tokens,
        mocked_update_refresh_attempted_at,
    ):
        mocked_should_refresh_access_token.return_value = True

        config = initialise_api(host="https://example.com")

        assert config.headers == {"Authorization": "Bearer dummy_access_token"}
        mocked_refresh_access_token.assert_called_once()
        mocked_store_sso_tokens.assert_called_once_with(
            "https://example.com", "new_access_token", "new_refresh_token"
        )

    def test_initialise_api_with_recently_refreshed_access_token_and_empty_basic_auth_set(
        self,
        mocked_get_access_token,
        mocked_get_refresh_token,
        mocked_should_refresh_access_token,
        mocked_refresh_access_token,
        mocked_store_sso_tokens,
        mocked_update_refresh_attempted_at,
    ):
        auth_header = Configuration().get_basic_auth_token()
        config = initialise_api(
            host="https://example.com", headers={"Authorization": auth_header}
        )

        assert config.headers == {"Authorization": "Bearer dummy_access_token"}
        assert config.username == ""
        assert config.password == ""
        mocked_refresh_access_token.assert_not_called()
        mocked_store_sso_tokens.assert_not_called()
        mocked_update_refresh_attempted_at.assert_not_called()

    def test_initialise_api_with_recently_refreshed_access_token_and_present_basic_auth(
        self,
        mocked_get_access_token,
        mocked_get_refresh_token,
        mocked_should_refresh_access_token,
        mocked_refresh_access_token,
        mocked_store_sso_tokens,
        mocked_update_refresh_attempted_at,
    ):
        temp_config = Configuration()
        temp_config.username = "username"
        temp_config.password = "password"
        auth_header = temp_config.get_basic_auth_token()
        config = initialise_api(
            host="https://example.com", headers={"Authorization": auth_header}
        )

        assert config.headers == {"Authorization": auth_header}
        assert config.username == "username"
        assert config.password == "password"
        mocked_refresh_access_token.assert_not_called()
        mocked_store_sso_tokens.assert_not_called()
        mocked_update_refresh_attempted_at.assert_not_called()
