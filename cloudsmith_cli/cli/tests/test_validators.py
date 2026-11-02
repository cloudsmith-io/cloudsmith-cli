"""Tests for the OWNER/REPO path validators."""

import click
import pytest

from ..validators import validate_optional_owner_repo, validate_owner_repo


def test_optional_owner_repo_drops_empty_trailing_repo():
    assert validate_optional_owner_repo(None, None, "myorg/") == ["myorg"]


def test_optional_owner_repo_treats_all_empty_parts_as_not_given():
    assert validate_optional_owner_repo(None, None, "/") is None


def test_optional_owner_repo_rejects_blank_owner():
    with pytest.raises(click.BadParameter, match="cannot be blank"):
        validate_optional_owner_repo(None, None, "/myrepo")


def test_required_repo_left_blank_raises():
    with pytest.raises(click.BadParameter, match="cannot be blank"):
        validate_owner_repo(None, None, "myorg/")
