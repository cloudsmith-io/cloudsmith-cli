"""Tests for the error-reporting opt-out controls."""

from unittest.mock import patch

import pytest

from cloudsmith_cli.core import telemetry


@pytest.fixture(autouse=True)
def clear_opt_out_env(monkeypatch):
    """Isolate from a developer's own DO_NOT_TRACK / CLOUDSMITH_NO_TELEMETRY."""
    for name in telemetry.OPT_OUT_ENVS:
        monkeypatch.delenv(name, raising=False)


def test_enabled_when_nothing_set():
    assert telemetry.telemetry_disabled({}) is False


@pytest.mark.parametrize("name", telemetry.OPT_OUT_ENVS)
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", " yes "])
def test_truthy_value_disables(name, value):
    assert telemetry.telemetry_disabled({name: value}) is True


@pytest.mark.parametrize("name", telemetry.OPT_OUT_ENVS)
@pytest.mark.parametrize("value", ["0", "", "no", "false", "off"])
def test_other_values_leave_reporting_on(name, value):
    assert telemetry.telemetry_disabled({name: value}) is False


def test_ci_does_not_disable():
    assert telemetry.telemetry_disabled({"CI": "true"}) is False


def test_defaults_to_os_environ(monkeypatch):
    monkeypatch.setenv(telemetry.DO_NOT_TRACK_ENV, "1")
    assert telemetry.telemetry_disabled() is True


def test_report_exception_reports_when_enabled(capsys):
    assert telemetry.report_exception(RuntimeError("boom")) is True
    assert "oopsie! RuntimeError: boom" in capsys.readouterr().err


@pytest.mark.parametrize("name", telemetry.OPT_OUT_ENVS)
def test_report_exception_is_silent_when_opted_out(name, monkeypatch, capsys):
    monkeypatch.setenv(name, "1")

    assert telemetry.report_exception(RuntimeError("boom")) is False
    assert capsys.readouterr().err == ""


def test_report_exception_never_raises():
    with patch.object(telemetry.click, "echo", side_effect=OSError("broken pipe")):
        assert telemetry.report_exception(RuntimeError("boom")) is False
