import pytest


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
