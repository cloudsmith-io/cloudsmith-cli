"""Tests for config file creation and messaging."""

import os
import stat
from unittest.mock import Mock, patch

import click
import pytest

from ...cli.config import CredentialsReader, Options
from ..config import create_config_files, new_config_messaging


def capture_messages(api_key_from_file, new_api_key, create=False):
    """Return the messaging emitted after generating config files, as one string."""
    opts = Mock(api_key_from_file=api_key_from_file)

    with (
        patch("cloudsmith_cli.core.config.click.secho") as secho,
        patch("cloudsmith_cli.core.config.click.echo"),
    ):
        new_config_messaging(
            has_errors=False, opts=opts, create=create, api_key=new_api_key
        )

    return " ".join(str(call.args[0]) for call in secho.call_args_list if call.args)


class TestNewConfigMessaging:
    """The mismatch warning names the credentials file specifically, so it reads
    the file-sourced chain input rather than the effective key.
    """

    def test_warns_when_the_file_key_differs_from_the_new_token(self):
        messages = capture_messages(api_key_from_file="csa_old", new_api_key="csa_new")

        assert "doesn't match" in messages

    def test_stays_quiet_when_the_file_key_matches_the_new_token(self):
        messages = capture_messages(
            api_key_from_file="csa_same", new_api_key="csa_same"
        )

        assert "doesn't match" not in messages

    def test_prompts_to_store_the_key_when_the_file_has_none(self):
        messages = capture_messages(api_key_from_file=None, new_api_key="csa_new")

        assert "Don't forget to put your API key in a config file" in messages


@pytest.mark.skipif(os.name == "nt", reason="Windows does not use group mode bits")
@pytest.mark.parametrize("existing_mode", [None, 0o660])
def test_saved_credentials_file_is_owner_only(telemetry_config_dir, existing_mode):
    creds_path = telemetry_config_dir / "credentials.ini"
    if existing_mode is not None:
        creds_path.write_text("[default]\napi_key = review_old_key\n")
        creds_path.chmod(existing_mode)

    opts = Options()
    opts.output = "pretty"
    with click.Context(click.Command("login")) as ctx:
        create_config_files(ctx, opts, "review_new_key", force=True)

    assert stat.S_IMODE(creds_path.stat().st_mode) == 0o600
    assert "review_new_key" in creds_path.read_text()


def test_update_api_key_saves_key_when_mode_cannot_change(tmp_path):
    creds_path = tmp_path / "credentials.ini"
    creds_path.write_text("[default]\napi_key = review_old_key\n")

    with patch("cloudsmith_cli.cli.config.os.chmod", side_effect=PermissionError):
        CredentialsReader.update_api_key(str(creds_path), "review_new_key")

    assert "review_new_key" in creds_path.read_text()


@pytest.mark.skipif(os.name == "nt", reason="Windows does not use group mode bits")
def test_credentials_file_is_owner_only_before_mode_is_set(telemetry_config_dir):
    with patch("cloudsmith_cli.cli.config.os.chmod"):
        CredentialsReader.create_default_file({"api_key": "review_new_key"}, 0o600)

    creds_path = telemetry_config_dir / "credentials.ini"
    assert stat.S_IMODE(creds_path.stat().st_mode) == 0o600
