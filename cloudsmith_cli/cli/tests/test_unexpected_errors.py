"""Tests for the top-level handler of unexpected exceptions in AliasGroup.main.

Click's own errors and handled API errors keep their existing rendering; any
other exception is caught at the top level, summarised on stderr and exits 1
instead of surfacing a raw Python traceback.
"""

import runpy
import sys
from unittest.mock import patch

import pytest

from cloudsmith_cli.cli.commands.main import main
from cloudsmith_cli.core import telemetry
from cloudsmith_cli.core.api.exceptions import ApiException


@pytest.fixture(autouse=True)
def clear_opt_out_env(monkeypatch):
    """Isolate from a developer's own DO_NOT_TRACK / CLOUDSMITH_NO_TELEMETRY."""
    for name in telemetry.OPT_OUT_ENVS:
        monkeypatch.delenv(name, raising=False)


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
        "fake-api-key",
        *extra,
    ]


def whoami_raises(exc):
    """Patch the whoami API call to raise ``exc``."""
    return patch("cloudsmith_cli.cli.commands.whoami.get_user_brief", side_effect=exc)


def test_unexpected_exception_prints_oopsie_and_exits_1(runner, tmp_path):
    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(main, whoami_args(tmp_path))

    assert result.exit_code == 1
    assert "oopsie! RuntimeError: boom" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


@pytest.mark.parametrize("name", telemetry.OPT_OUT_ENVS)
def test_opted_out_prints_neutral_error(runner, tmp_path, monkeypatch, name):
    monkeypatch.setenv(name, "1")

    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(main, whoami_args(tmp_path))

    assert result.exit_code == 1
    assert "Error: RuntimeError: boom" in result.stderr
    assert "oopsie!" not in result.output
    assert "Traceback" not in result.stderr


def test_ci_still_reports(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CI", "true")

    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(main, whoami_args(tmp_path))

    assert result.exit_code == 1
    assert "oopsie! RuntimeError: boom" in result.stderr


def test_debug_also_prints_traceback(runner, tmp_path):
    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(main, whoami_args(tmp_path, "--debug"))

    assert result.exit_code == 1
    assert "Traceback (most recent call last)" in result.stderr
    assert "oopsie! RuntimeError: boom" in result.stderr


@pytest.mark.parametrize("fmt", ["json", "pretty_json"])
def test_json_output_keeps_stdout_clean(runner, tmp_path, fmt):
    with whoami_raises(RuntimeError("boom")):
        result = runner.invoke(main, whoami_args(tmp_path, "-F", fmt))

    assert result.exit_code == 1
    assert "oopsie!" not in result.stdout
    assert "oopsie! RuntimeError: boom" in result.stderr


def test_handled_api_exception_is_not_caught(runner, tmp_path):
    with whoami_raises(ApiException(status=401, detail="Invalid API key")):
        result = runner.invoke(main, whoami_args(tmp_path))

    # AliasGroup.main runs click with standalone_mode=False, so ctx.exit()'s
    # code is returned (and propagated by the entrypoints' sys.exit()).
    assert result.return_value == 401
    assert "oopsie!" not in result.output


def test_usage_error_is_not_caught(runner):
    result = runner.invoke(main, ["definitely-not-a-command"])

    assert result.exit_code == 2
    assert "oopsie!" not in result.output


def test_non_standalone_mode_reraises(tmp_path):
    with whoami_raises(RuntimeError("boom")), pytest.raises(RuntimeError, match="boom"):
        main(whoami_args(tmp_path), standalone_mode=False)


def test_python_m_exits_1_on_unexpected_exception(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cloudsmith", *whoami_args(tmp_path)])

    with whoami_raises(RuntimeError("boom")), pytest.raises(SystemExit) as exc_info:
        runpy.run_module("cloudsmith_cli", run_name="__main__")

    assert exc_info.value.code == 1
    assert "oopsie! RuntimeError: boom" in capsys.readouterr().err
