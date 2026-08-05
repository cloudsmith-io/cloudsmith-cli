import cloudsmith_api
import pytest


@pytest.fixture(autouse=True)
def restore_api_configuration_default():
    """Undo the process-wide SDK configuration a test leaves behind.

    ``initialise_api`` ends in ``Configuration.set_default()``, so a test that
    sets a proxy, host or credential would otherwise hand it to every test that
    runs after it. A fresh ``Configuration`` is a copy of the current default,
    which makes it the snapshot to put back afterwards.
    """
    default = cloudsmith_api.Configuration()
    yield
    cloudsmith_api.Configuration.set_default(default)
