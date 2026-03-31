from cloudsmith_api import Configuration

from ..api.init import initialise_api


class TestInitialiseApi:
    def setup_class(cls):  # pylint: disable=no-self-argument
        # For the purposes of these tests, we need to explicitly call set_default(None) at the
        # outset because other tests in the suite may have called initialise_api() already.
        # Resetting Configuration._default to None here effectively reverts the
        # Configuration class to its vanilla, unmodified behaviour/state.
        Configuration.set_default(None)

    def test_initialise_api_sets_cloudsmith_api_config_default(self):
        """Assert that the extra attributes we add to the cloudsmith_cli.Configuration class
        are present on newly-created instances of that class.
        """
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

    def test_initialise_api_sets_bearer_auth_with_access_token(self):
        """Verify access_token is set as Bearer auth header."""
        from cloudsmith_cli.core.credentials.models import CredentialResult

        credential = CredentialResult(
            api_key="test_access_token", source_name="test", auth_type="bearer"
        )
        config = initialise_api(
            host="https://example.com",
            credential=credential,
        )
        assert config.headers == {"Authorization": "Bearer test_access_token"}

    def test_initialise_api_sets_api_key(self):
        """Verify key is set as X-Api-Key header."""
        from cloudsmith_cli.core.credentials.models import CredentialResult

        credential = CredentialResult(
            api_key="test_api_key", source_name="test", auth_type="api_key"
        )
        config = initialise_api(
            host="https://example.com",
            credential=credential,
        )
        assert config.api_key["X-Api-Key"] == "test_api_key"

    def test_initialise_api_bearer_credential(self):
        """Verify bearer credential sets Authorization header, not X-Api-Key."""
        from cloudsmith_cli.core.credentials.models import CredentialResult

        Configuration.set_default(None)
        credential = CredentialResult(
            api_key="test_access_token", source_name="test", auth_type="bearer"
        )
        config = initialise_api(
            host="https://example.com",
            credential=credential,
        )
        assert config.headers == {"Authorization": "Bearer test_access_token"}
        assert "X-Api-Key" not in config.api_key

    def test_initialise_api_with_basic_auth_header(self):
        """Verify basic auth header is parsed into username and password."""
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
