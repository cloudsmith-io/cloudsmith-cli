# Copyright 2026 Cloudsmith Ltd
"""Tests for the terraform-credentials-cloudsmith named entry point.

The ``cloudsmith_cli.wrapper`` module backs both the ``[project.scripts]``
console script and the second PyInstaller EXE, so a binary named
``terraform-credentials-cloudsmith`` routes to ``credential-helper terraform``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from cloudsmith_cli import wrapper


def test_run_prepends_credential_helper_terraform():
    """run() forwards its argv to the `credential-helper terraform` subcommand."""
    with patch("cloudsmith_cli.wrapper.main") as fake_main:
        fake_main.return_value = 0
        rc = wrapper.run(["get", "terraform.cloudsmith.io"])

    assert rc == 0
    _, kwargs = fake_main.call_args
    assert kwargs["args"] == [
        "credential-helper",
        "terraform",
        "get",
        "terraform.cloudsmith.io",
    ]
    assert kwargs["prog_name"] == "terraform-credentials-cloudsmith"


def test_run_forwards_baked_in_args_then_verb():
    """Terraformrc `args` (e.g. --org/-r) precede the verb+host and are kept."""
    with patch("cloudsmith_cli.wrapper.main") as fake_main:
        fake_main.return_value = 0
        wrapper.run(["--org", "acme", "-r", "repo", "get", "terraform.cloudsmith.io"])

    _, kwargs = fake_main.call_args
    assert kwargs["args"] == [
        "credential-helper",
        "terraform",
        "--org",
        "acme",
        "-r",
        "repo",
        "get",
        "terraform.cloudsmith.io",
    ]


def test_run_uses_sys_argv_by_default(monkeypatch):
    """With no argv, run() reads sys.argv[1:]."""
    monkeypatch.setattr(
        "sys.argv",
        ["terraform-credentials-cloudsmith", "get", "terraform.cloudsmith.io"],
    )
    with patch("cloudsmith_cli.wrapper.main") as fake_main:
        fake_main.return_value = 0
        wrapper.run()

    _, kwargs = fake_main.call_args
    assert kwargs["args"] == [
        "credential-helper",
        "terraform",
        "get",
        "terraform.cloudsmith.io",
    ]


def test_run_returns_nonzero_exit_code():
    """run() propagates the CLI's exit code."""
    with patch("cloudsmith_cli.wrapper.main") as fake_main:
        fake_main.return_value = 1
        assert wrapper.run(["get", "host"]) == 1


def test_main_entry_wraps_run_in_sys_exit():
    """main_entry() calls sys.exit() with run()'s code so callers see failures."""
    with patch("cloudsmith_cli.wrapper.run", return_value=7):
        with pytest.raises(SystemExit) as exc:
            wrapper.main_entry()
    assert exc.value.code == 7
