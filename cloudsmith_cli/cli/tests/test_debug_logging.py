# Copyright 2026 Cloudsmith Ltd
"""Tests for the --debug flag enabling logger output."""

import logging

import click
import pytest

from ..config import OPTIONS
from ..decorators import _DEBUG_LOG_HANDLER_NAME, common_cli_output_options


def _debug_handlers():
    package_logger = logging.getLogger("cloudsmith_cli")
    return [
        handler
        for handler in package_logger.handlers
        if handler.name == _DEBUG_LOG_HANDLER_NAME
    ]


@pytest.fixture
def package_logger_state(monkeypatch):
    """Reset the options and restore the package logger after the test."""
    monkeypatch.delattr(OPTIONS, "value", raising=False)
    package_logger = logging.getLogger("cloudsmith_cli")
    original_level = package_logger.level
    original_handlers = list(package_logger.handlers)
    original_propagate = package_logger.propagate
    yield package_logger
    package_logger.setLevel(original_level)
    package_logger.handlers = original_handlers
    package_logger.propagate = original_propagate


@pytest.fixture
def logging_command(package_logger_state):
    """A minimal command that emits one debug record from a package logger."""

    @click.command()
    @common_cli_output_options
    @click.pass_context
    def emit(ctx, opts):
        logging.getLogger("cloudsmith_cli.cli.tests").debug("debug record")
        logging.getLogger("third_party").debug("third-party record")

    return emit


@pytest.fixture
def logging_group(package_logger_state):
    """A group whose subcommand reports opts.debug and emits a debug record."""

    @click.group()
    @common_cli_output_options
    @click.pass_context
    def group(ctx, opts):
        pass

    @group.command()
    @common_cli_output_options
    @click.pass_context
    def emit(ctx, opts):
        click.echo(f"debug={opts.debug}")
        logging.getLogger("cloudsmith_cli.cli.tests").debug("debug record")

    return group


def test_debug_flag_shows_package_debug_records(runner, logging_command):
    result = runner.invoke(logging_command, ["--debug"])

    assert result.exit_code == 0, result.output
    assert "debug record" in result.stderr


def test_debug_flag_does_not_enable_third_party_debug_records(runner, logging_command):
    result = runner.invoke(logging_command, ["--debug"])

    assert result.exit_code == 0, result.output
    assert "third-party record" not in result.stderr


def test_without_debug_flag_debug_records_stay_hidden(runner, logging_command):
    result = runner.invoke(logging_command, [])

    assert result.exit_code == 0, result.output
    assert "debug record" not in result.stderr
    assert not _debug_handlers()


def test_repeat_invocations_do_not_duplicate_records(runner, logging_command):
    runner.invoke(logging_command, ["--debug"])
    result = runner.invoke(logging_command, ["--debug"])

    assert result.exit_code == 0, result.output
    assert result.stderr.count("debug record") == 1
    assert len(_debug_handlers()) == 1


def test_later_invocation_without_debug_flag_disables_debug_logging(
    runner, logging_command, monkeypatch
):
    runner.invoke(logging_command, ["--debug"])
    monkeypatch.delattr(OPTIONS, "value", raising=False)

    result = runner.invoke(logging_command, [])

    assert result.exit_code == 0, result.output
    assert not _debug_handlers()
    assert logging.getLogger("cloudsmith_cli").getEffectiveLevel() > logging.DEBUG


def test_group_level_debug_flag_reaches_the_subcommand(runner, logging_group):
    result = runner.invoke(logging_group, ["-d", "emit"])

    assert result.exit_code == 0, result.output
    assert "debug=True" in result.output
    assert "debug record" in result.stderr
