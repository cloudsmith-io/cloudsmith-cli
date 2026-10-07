"""Tests for the top-level handler of unexpected exceptions in AliasGroup.main.

Click's own errors and handled API errors keep their existing rendering and
are never reported. Any other exception is reported (unless opted out),
summarised on stderr, and exits 1 instead of surfacing a raw traceback.
"""

import json
import runpy
import sys
from unittest.mock import patch

import click
import pytest

from cloudsmith_cli.cli import config as cli_config
from cloudsmith_cli.cli.commands.main import main
from cloudsmith_cli.core import telemetry
from cloudsmith_cli.core.api.exceptions import (
    ApiException,
    TwoFactorRequiredException,
)

API_KEY = "fake-api-key-0123456789"


def whoami_args(config_dir, *extra):
    """Return args for a whoami isolated from real config."""
    return [
        "whoami",
        "--config-file",
        str(config_dir),
        "--credentials-file",
        str(config_dir),
        "--api-host",
        "https://api.example.invalid",
        "--api-key",
        API_KEY,
        *extra,
    ]


def whoami_raises(exc):
    """Patch the whoami API call to raise ``exc``."""
    return patch("cloudsmith_cli.cli.commands.whoami.get_user_brief", side_effect=exc)


def test_unexpected_exception_is_reported_and_exits_1(runner, tmp_path, sentry_events):
    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(main, whoami_args(tmp_path))

    assert result.exit_code == 1
    assert result.stderr.strip().endswith("Error: RuntimeError: boom")
    assert "Traceback" not in result.output

    (event,) = sentry_events
    assert event["tags"]["command"] == "whoami"
    assert event["exception"]["values"][-1]["type"] == "RuntimeError"
    assert event["exception"]["values"][-1]["mechanism"]["handled"] is False


def test_event_carries_no_arguments_or_credentials(runner, tmp_path, sentry_events):
    with whoami_raises(RuntimeError("boom")):
        runner.invoke(main, whoami_args(tmp_path))

    serialised = json.dumps(sentry_events)
    for leaked in (API_KEY, "api.example.invalid", str(tmp_path), "--api-key"):
        assert leaked not in serialised


def test_command_path_is_canonical_and_argument_free(runner, tmp_path, sentry_events):
    """Aliases resolve to command names; the OWNER/REPO argument is not sent."""
    with patch(
        "cloudsmith_cli.core.api.repos.list_repo_gpg_key",
        side_effect=RuntimeError("boom"),
    ):
        result = runner.invoke(
            main,
            [
                "repos",
                "gpg",
                "ls",
                "acme-org/acme-repo",
                "--config-file",
                str(tmp_path),
                "--credentials-file",
                str(tmp_path),
                "--api-key",
                API_KEY,
            ],
        )

    assert result.exit_code == 1
    (event,) = sentry_events
    assert event["tags"]["command"] == "repositories gpg get"
    assert "acme-org" not in json.dumps(event)
    assert "acme-repo" not in json.dumps(event)


@pytest.mark.parametrize("name", telemetry.OPT_OUT_ENVS)
def test_opted_out_sends_nothing_and_prints_the_same_line(
    runner, tmp_path, monkeypatch, sentry_events, name
):
    monkeypatch.setenv(name, "1")

    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(main, whoami_args(tmp_path))

    assert result.exit_code == 1
    assert result.stderr.strip().endswith("Error: RuntimeError: boom")
    assert sentry_events == []


def test_ci_still_reports(runner, tmp_path, monkeypatch, sentry_events):
    monkeypatch.setenv("CI", "true")

    with whoami_raises(RuntimeError("boom")):
        runner.invoke(main, whoami_args(tmp_path))

    assert len(sentry_events) == 1


def test_reporting_failure_does_not_change_the_outcome(
    runner, tmp_path, monkeypatch, sentry_events
):
    # pylint: disable=protected-access
    def explode(envelope):
        raise OSError("sentry is down")

    monkeypatch.setattr(telemetry._transport, "capture_envelope", explode)

    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(main, whoami_args(tmp_path))

    assert result.exit_code == 1
    assert result.stderr.strip().endswith("Error: RuntimeError: boom")
    assert "sentry is down" not in result.output


def test_debug_also_prints_traceback(runner, tmp_path):
    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(main, whoami_args(tmp_path, "--debug"))

    assert result.exit_code == 1
    assert "Traceback (most recent call last)" in result.stderr
    assert "Error: RuntimeError: boom" in result.stderr


@pytest.mark.parametrize("fmt", ["json", "pretty_json"])
def test_json_output_keeps_stdout_clean(runner, tmp_path, fmt):
    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(main, whoami_args(tmp_path, "-F", fmt))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error: RuntimeError: boom" in result.stderr


def test_handled_api_exception_is_not_reported(runner, tmp_path, sentry_events):
    with whoami_raises(ApiException(status=401, detail="Invalid API key")):
        result = runner.invoke(main, whoami_args(tmp_path))

    # AliasGroup.main runs click with standalone_mode=False, so ctx.exit()'s
    # code is returned (and propagated by the entrypoints' sys.exit()).
    assert result.return_value == 401
    assert "RuntimeError" not in result.output
    assert sentry_events == []


@pytest.mark.parametrize(
    "exc",
    [
        click.ClickException("nope"),
        click.UsageError("bad usage"),
        click.exceptions.Abort(),
    ],
    ids=["ClickException", "UsageError", "Abort"],
)
def test_click_errors_are_not_reported(runner, tmp_path, sentry_events, exc):
    with whoami_raises(exc):
        result = runner.invoke(main, whoami_args(tmp_path))

    assert result.exit_code != 0
    assert sentry_events == []


def test_user_error_is_not_reported(runner, tmp_path, sentry_events):
    with whoami_raises(TwoFactorRequiredException("2fa-token")):
        result = runner.invoke(main, whoami_args(tmp_path))

    assert result.exit_code == 1
    assert "Two-factor authentication is required" in result.stderr
    assert sentry_events == []


MALFORMED_INI = {
    "no-section-header": (b"api_key = x\n[default]\n", "MissingSectionHeaderError"),
    "duplicate-option": (
        b"[default]\napi_key = a\napi_key = b\n",
        "DuplicateOptionError",
    ),
    "duplicate-section": (b"[default]\n[default]\n", "DuplicateSectionError"),
    "unparsable-line": (b"[default]\n=ap\n", "ParsingError"),
    "not-utf8": (b"\xff\xfe\x00garbage", "UnicodeDecodeError"),
}


@pytest.fixture()
def isolated_config_readers(monkeypatch, tmp_path):
    """Keep --config-file paths from leaking into later tests.

    ``load_config`` inserts the given file into the reader's class-level
    ``config_files`` list, so a malformed file would otherwise be re-read by
    every test that runs after this one.
    """
    for reader in (cli_config.ConfigReader, cli_config.CredentialsReader):
        monkeypatch.setattr(reader, "config_files", list(reader.config_files))
        monkeypatch.setattr(reader, "config_searchpath", [str(tmp_path)])


@pytest.mark.usefixtures("isolated_config_readers")
@pytest.mark.parametrize("which", ["config", "credentials"])
@pytest.mark.parametrize("case", list(MALFORMED_INI))
def test_malformed_ini_is_shown_but_not_reported(
    runner, tmp_path, sentry_events, which, case
):
    content, exc_type = MALFORMED_INI[case]
    bad = tmp_path / f"bad-{which}.ini"
    bad.write_bytes(content)
    good = tmp_path / "good.ini"
    good.write_text("[default]\n")
    config, creds = (bad, good) if which == "config" else (good, bad)

    with whoami_raises(AssertionError("must fail before calling the API")):
        result = runner.invoke(
            main,
            ["whoami", "--config-file", str(config), "--credentials-file", str(creds)],
        )

    # Shown exactly as any other unexpected error: the parser's own message.
    assert result.exit_code == 1
    assert f"Error: {exc_type}: " in result.stderr
    assert "Traceback" not in result.output
    assert sentry_events == []


@pytest.mark.usefixtures("isolated_config_readers")
def test_parsing_error_message_is_unchanged(runner, tmp_path, sentry_events):
    bad = tmp_path / "config.ini"
    bad.write_text("[default]\n=ap\n")

    result = runner.invoke(main, ["whoami", "--config-file", str(bad)])

    assert (
        f"Error: ParsingError: Source contains parsing errors: '{bad}'\n"
        "\t[line  2]: '=ap\\n'"
    ) in result.stderr
    assert sentry_events == []


@pytest.mark.usefixtures("isolated_config_readers")
def test_valid_ini_still_loads(runner, tmp_path, sentry_events):
    config = tmp_path / "config.ini"
    config.write_text("[default]\napi_host = https://api.example.invalid\n")

    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(
            main,
            ["whoami", "--config-file", str(config), "--api-key", API_KEY],
        )

    # Reached the API call, so the file was read without complaint.
    assert "Error: RuntimeError: boom" in result.stderr
    assert len(sentry_events) == 1


def test_unknown_command_is_not_reported(runner, sentry_events):
    result = runner.invoke(main, ["definitely-not-a-command"])

    assert result.exit_code == 2
    assert sentry_events == []


def test_non_standalone_mode_reraises_without_reporting(tmp_path, sentry_events):
    with whoami_raises(RuntimeError("boom")), pytest.raises(RuntimeError, match="boom"):
        main(whoami_args(tmp_path), standalone_mode=False)

    assert sentry_events == []


def test_python_m_exits_1_on_unexpected_exception(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cloudsmith", *whoami_args(tmp_path)])

    with whoami_raises(RuntimeError("boom")), pytest.raises(SystemExit) as exc_info:
        runpy.run_module("cloudsmith_cli", run_name="__main__")

    assert exc_info.value.code == 1
    assert "Error: RuntimeError: boom" in capsys.readouterr().err
