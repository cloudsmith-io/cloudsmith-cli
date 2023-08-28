from cloudsmith_api import Configuration

from ..api.init import initialise_api


def test_initialise_api_sets_cloudsmith_api_config_default():
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

    # For the purposes of this test, we need to explcitly call set_default(None) at the
    # outset because other tests in the suite may have called initialise_api() already.
    # Resetting Configuration._default to None here effectively reverts the
    # Configuration class to its vanilla, unmodified behaviour/state.
    Configuration.set_default(None)

    # Because Configuration._default is None, a newly-created instance of
    # cloudsmith_api.Configuration() should not have any other attributes than those
    # in the auto-generated swagger-codegen class declaration.
    new_config_before_initialise = Configuration()
    assert all(
        not hasattr(new_config_before_initialise, attr) for attr in extra_config_attrs
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
