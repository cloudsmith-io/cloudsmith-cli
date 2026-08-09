import pytest

from ....cli import config as cli_config
from ....core.credentials.models import CredentialResult


@pytest.fixture()
def cli_config_dir(tmp_path, monkeypatch):
    """Point the CLI config dir at a tmp dir, and return it.

    Maven helper state (``package-managers.ini`` and the shims dir) hangs off
    it. The trusted config search path is pinned at an empty directory, so
    the developer's own ``config.ini`` cannot change the default domains
    these tests observe.
    """
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.maven.config.get_default_config_path",
        lambda: str(tmp_path),
    )
    empty = tmp_path / "empty-trusted-config"
    empty.mkdir()
    monkeypatch.setattr(cli_config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(cli_config.ConfigReader, "config_searchpath", [str(empty)])
    return tmp_path


@pytest.fixture()
def credential():
    """A resolved credential, as the provider chain would hand one back."""
    return CredentialResult(api_key="k_abc", source_name="test")


class MockToken:
    """Mock Token object with the properties needed for testing."""

    def __init__(self, key, created, slug_perm):
        self.key = key
        self.created = created
        self.slug_perm = slug_perm

    def to_dict(self):
        return {
            "key": self.key,
            "created": self.created,
            "slug_perm": self.slug_perm,
        }


@pytest.fixture
def mock_token():
    """Return a default MockToken for use in tests."""
    return MockToken(
        key="ck_test123456",
        created="2026-02-06T00:00:00Z",
        slug_perm="test-token",
    )
