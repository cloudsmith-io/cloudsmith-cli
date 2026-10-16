"""Tests for config file messaging."""

import io
from unittest.mock import Mock, patch

import pytest

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


def json_opts(output, has_default_file):
    """Opts for a JSON-output command whose config readers report the given state."""

    def reader(name):
        return Mock(
            config_name=name,
            has_default_file=Mock(return_value=has_default_file),
            get_default_filepath=Mock(return_value=f"/nowhere/{name}.ini"),
            spec=["config_name", "has_default_file", "get_default_filepath"],
        )

    return Mock(
        output=output,
        api_key_from_file=None,
        get_config_reader=Mock(return_value=reader("standard")),
        get_creds_reader=Mock(return_value=reader("credentials")),
    )


@pytest.mark.parametrize("output", ["json", "pretty_json"])
@pytest.mark.parametrize("has_default_file", [True, False])
def test_json_output_keeps_config_messages_off_stdout(
    capsys, monkeypatch, output, has_default_file
):
    """Callers print JSON on stdout, so prompts and messages go to stderr."""
    monkeypatch.setattr("sys.stdin", io.StringIO("N\n"))
    opts = json_opts(output, has_default_file)

    create, has_errors = create_config_files(None, opts, api_key="csa_new")
    new_config_messaging(has_errors, opts, create, api_key="csa_new")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "config file locations" in captured.err
    assert "ready to rock" in captured.err
