# Copyright 2026 Cloudsmith Ltd
"""Tests for credential-helper install/uninstall/list commands and launchers."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import click.testing
import pytest

from ....credential_helpers.docker.installer import DockerInstaller
from ....credential_helpers.launchers import (
    _launcher_content,
    _launcher_filename,
    _user_bin_dir,
    is_on_path,
    remove_launcher,
    resolve_bin_dir,
    write_launcher,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner():
    """Return a CliRunner."""
    return click.testing.CliRunner()


# ---------------------------------------------------------------------------
# 1. launcher filename + content (pure, platform-parameterised)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "windows,expected_name,expected_content",
    [
        (
            False,
            "docker-credential-cloudsmith",
            '#!/bin/sh\nexec cloudsmith credential-helper docker "$@"\n',
        ),
        (
            True,
            "docker-credential-cloudsmith.cmd",
            "@echo off\r\ncloudsmith credential-helper docker %*\r\n",
        ),
    ],
)
def test_launcher_filename_and_content(windows, expected_name, expected_content):
    """Per-platform launcher name + body — guards the exact Windows .cmd bytes.

    Parameterised on ``windows`` rather than patching ``os.name`` so no
    ``pathlib.Path`` is built under a faked platform (which raises
    ``NotImplementedError`` on Python < 3.12).
    """
    assert (
        _launcher_filename("docker-credential-cloudsmith", windows=windows)
        == expected_name
    )
    assert (
        _launcher_content("cloudsmith credential-helper docker", windows=windows)
        == expected_content
    )


# ---------------------------------------------------------------------------
# 2. write_launcher / remove_launcher — end-to-end on the host platform
# ---------------------------------------------------------------------------


def test_write_launcher_writes_executable_script(tmp_path):
    """write_launcher writes the shim with content + 0o755 on the host platform."""
    dest = write_launcher(
        tmp_path,
        "docker-credential-cloudsmith",
        "cloudsmith credential-helper docker",
    )
    expected = '#!/bin/sh\nexec cloudsmith credential-helper docker "$@"\n'
    assert dest.read_text(encoding="utf-8") == expected
    assert stat.S_IMODE(dest.stat().st_mode) == 0o755


def test_remove_launcher(tmp_path):
    """remove_launcher returns True + file gone when present, False when absent."""
    write_launcher(
        tmp_path,
        "docker-credential-cloudsmith",
        "cloudsmith credential-helper docker",
    )
    assert remove_launcher(tmp_path, "docker-credential-cloudsmith") is True
    assert not (tmp_path / "docker-credential-cloudsmith").exists()

    # Second call: file is gone now
    assert remove_launcher(tmp_path, "docker-credential-cloudsmith") is False


# ---------------------------------------------------------------------------
# 3. resolve_bin_dir + user-bin (no os.name faking)
# ---------------------------------------------------------------------------


def test_resolve_bin_dir_override(tmp_path):
    """An explicit override is returned verbatim."""
    assert resolve_bin_dir(str(tmp_path)) == tmp_path


@pytest.mark.parametrize(
    "windows,expected_suffix",
    [
        (False, (".local", "bin")),
        (True, ("Cloudsmith", "bin")),
    ],
)
def test_user_bin_dir(tmp_path, monkeypatch, windows, expected_suffix):
    """_user_bin_dir returns the per-platform user bin location.

    Parameterised on ``windows`` (not ``os.name``) to avoid building a
    ``WindowsPath`` on a posix host.
    """
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    result = _user_bin_dir(windows)
    assert result.parts[-2:] == expected_suffix


# ---------------------------------------------------------------------------
# 4. is_on_path
# ---------------------------------------------------------------------------


def test_is_on_path(tmp_path, monkeypatch):
    """is_on_path returns True when dir is in PATH, False when absent."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert is_on_path(tmp_path) is True

    monkeypatch.setenv("PATH", "/usr/bin:/usr/local/bin")
    assert is_on_path(tmp_path) is False


# ---------------------------------------------------------------------------
# 5. DockerInstaller.install
# ---------------------------------------------------------------------------


def test_docker_installer_install(tmp_path, monkeypatch):
    """install sets default+extra domains, preserves foreign entries, writes the launcher."""
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", str(bin_dir))

    # Seed a config with foreign data that must be preserved
    docker_dir.mkdir(parents=True)
    (docker_dir / "config.json").write_text(
        json.dumps(
            {
                "auths": {"ghcr.io": {"auth": "dG9rZW4="}},
                "credHelpers": {"ghcr.io": "gh"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    installer = DockerInstaller()
    installer.install(bin_dir=str(bin_dir), domains=("my.registry.example.com",))

    cfg = json.loads((docker_dir / "config.json").read_text())

    # Default host registered
    assert cfg["credHelpers"]["docker.cloudsmith.io"] == "cloudsmith"
    # Extra --domain host registered
    assert cfg["credHelpers"]["my.registry.example.com"] == "cloudsmith"
    # Foreign entries preserved
    assert cfg["auths"] == {"ghcr.io": {"auth": "dG9rZW4="}}
    assert cfg["credHelpers"]["ghcr.io"] == "gh"
    # Launcher written
    assert (bin_dir / "docker-credential-cloudsmith").exists()


# ---------------------------------------------------------------------------
# 6. install --dry-run
# ---------------------------------------------------------------------------


def test_docker_installer_dry_run(tmp_path, monkeypatch):
    """dry_run=True: no launcher written, config.json absent, returns planned strings."""
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"

    installer = DockerInstaller()
    actions = installer.install(bin_dir=str(bin_dir), dry_run=True)

    assert not (bin_dir / "docker-credential-cloudsmith").exists()
    assert not (docker_dir / "config.json").exists()
    assert any("would write launcher" in a for a in actions)
    assert any("docker.cloudsmith.io" in a for a in actions)


# ---------------------------------------------------------------------------
# 7. install idempotent
# ---------------------------------------------------------------------------


def test_docker_installer_idempotent(tmp_path, monkeypatch):
    """Second install run reports no change (config mtime unchanged, 'already up to date')."""
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"

    installer = DockerInstaller()
    installer.install(bin_dir=str(bin_dir))

    mtime_before = (docker_dir / "config.json").stat().st_mtime
    actions = installer.install(bin_dir=str(bin_dir))
    mtime_after = (docker_dir / "config.json").stat().st_mtime

    assert mtime_before == mtime_after
    assert any("already up to date" in a for a in actions)


# ---------------------------------------------------------------------------
# 8. uninstall
# ---------------------------------------------------------------------------


def test_docker_installer_uninstall(tmp_path, monkeypatch):
    """uninstall removes only cloudsmith entries (foreign kept) + removes launcher.

    Also verifies --bin-dir: install to custom dir, uninstall with same --bin-dir removes it.
    """
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    custom_bin_dir = tmp_path / "custom_bin"

    # Install to a custom bin dir
    installer = DockerInstaller()
    docker_dir.mkdir(parents=True)
    cfg_path = docker_dir / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "credHelpers": {
                    "docker.cloudsmith.io": "cloudsmith",
                    "ghcr.io": "gh",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    # Install launcher to custom_bin_dir
    installer.install(bin_dir=str(custom_bin_dir))
    launcher = custom_bin_dir / "docker-credential-cloudsmith"
    assert launcher.exists(), "Precondition: launcher must exist after install"

    # Uninstall — removes cloudsmith keys and launcher
    installer.uninstall(bin_dir=str(custom_bin_dir))

    cfg = json.loads(cfg_path.read_text())
    assert "docker.cloudsmith.io" not in cfg.get("credHelpers", {})
    assert cfg["credHelpers"]["ghcr.io"] == "gh"
    assert not launcher.exists()


# ---------------------------------------------------------------------------
# 9. DockerInstaller.status — str-not-Path guard
# ---------------------------------------------------------------------------


def test_docker_installer_status_type_contract(tmp_path, monkeypatch):
    """status()['launcher'] is str when installed and None when not — never a Path.

    Retained guard: the -F json Path-serialization regression.
    """
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"

    installer = DockerInstaller()

    # Before install: launcher is None
    with patch(
        "cloudsmith_cli.credential_helpers.docker.installer.resolve_bin_dir",
        return_value=bin_dir,
    ):
        result_before = installer.status()

    assert result_before["launcher"] is None
    assert not isinstance(result_before["launcher"], Path)

    # After install: launcher is a non-None str
    installer.install(bin_dir=str(bin_dir))
    with patch(
        "cloudsmith_cli.credential_helpers.docker.installer.resolve_bin_dir",
        return_value=bin_dir,
    ):
        result_after = installer.status()

    launcher = result_after["launcher"]
    assert launcher is not None
    assert isinstance(
        launcher, str
    ), f"status()['launcher'] must be str, got {type(launcher).__name__!r}"
    assert launcher.endswith("docker-credential-cloudsmith")
    assert not isinstance(launcher, Path)


# ---------------------------------------------------------------------------
# 10. autodiscovery
# ---------------------------------------------------------------------------

_INSTALLER_GET_FORMAT_DOMAINS = (
    "cloudsmith_cli.credential_helpers.docker.installer.get_format_domains"
)


@pytest.mark.parametrize(
    "scenario",
    [
        "discovery_on",
        "no_discover",
        "missing_org",
        "missing_api_key",
        "discovery_raises",
    ],
)
def test_autodiscovery(tmp_path, monkeypatch, scenario):
    """Autodiscovery matrix: registered, skipped, defaults-only, or graceful failure.

    Retained guard: graceful-discovery-failure (exception → WARNING, no crash).
    """
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", str(bin_dir))

    if scenario == "discovery_on":
        monkeypatch.setattr(
            _INSTALLER_GET_FORMAT_DOMAINS,
            lambda *_a, **_kw: ["docker.acme.com"],
        )
        installer = DockerInstaller()
        actions = installer.install(
            bin_dir=str(bin_dir), discover=True, org="acme", api_key="k_test"
        )
        cfg = json.loads((docker_dir / "config.json").read_text())
        assert cfg["credHelpers"]["docker.cloudsmith.io"] == "cloudsmith"
        assert cfg["credHelpers"]["docker.acme.com"] == "cloudsmith"
        assert any("discovered" in a and "1" in a for a in actions)

    elif scenario == "no_discover":
        called = []

        def _should_not_be_called(*_a, **_kw):
            called.append(True)
            return []

        monkeypatch.setattr(_INSTALLER_GET_FORMAT_DOMAINS, _should_not_be_called)
        installer = DockerInstaller()
        installer.install(
            bin_dir=str(bin_dir), discover=False, org="acme", api_key="k_test"
        )
        assert not called, "get_format_domains must not be called when discover=False"
        cfg = json.loads((docker_dir / "config.json").read_text())
        assert "docker.cloudsmith.io" in cfg["credHelpers"]
        assert "docker.acme.com" not in cfg["credHelpers"]

    elif scenario in ("missing_org", "missing_api_key"):
        called = []

        def _should_not_be_called(*_a, **_kw):
            called.append(True)
            return []

        monkeypatch.setattr(_INSTALLER_GET_FORMAT_DOMAINS, _should_not_be_called)
        installer = DockerInstaller()
        org = None if scenario == "missing_org" else "acme"
        api_key = "k_test" if scenario == "missing_org" else None
        installer.install(bin_dir=str(bin_dir), discover=True, org=org, api_key=api_key)
        assert (
            not called
        ), "get_format_domains must not be called when org/api_key absent"
        cfg = json.loads((docker_dir / "config.json").read_text())
        assert cfg["credHelpers"]["docker.cloudsmith.io"] == "cloudsmith"

    else:  # discovery_raises — graceful failure guard

        def _raise(*_a, **_kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(_INSTALLER_GET_FORMAT_DOMAINS, _raise)
        installer = DockerInstaller()
        # Must NOT raise
        actions = installer.install(
            bin_dir=str(bin_dir), discover=True, org="acme", api_key="k_test"
        )
        cfg = json.loads((docker_dir / "config.json").read_text())
        assert cfg["credHelpers"]["docker.cloudsmith.io"] == "cloudsmith"
        assert (bin_dir / "docker-credential-cloudsmith").exists()
        warning_actions = [a for a in actions if a.startswith("WARNING")]
        assert warning_actions, f"Expected a WARNING action, got: {actions}"
        assert any("network down" in a for a in warning_actions)


# ---------------------------------------------------------------------------
# 11. --refresh
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("refresh", [False, True])
def test_refresh_flag(tmp_path, monkeypatch, refresh):
    """refresh=False uses the on-disk cache; refresh=True bypasses it and hits the API."""
    import time

    from ....credential_helpers.custom_domains import (
        CustomDomain,
        get_cache_path,
        get_custom_domains,
        write_cache,
    )

    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
        lambda: str(tmp_path),
    )

    cache_path = get_cache_path("acme")
    cached_domain = CustomDomain(
        host="docker.acme.com", backend_kind=6, enabled=True, validated=True
    )
    write_cache(cache_path, [cached_domain])
    os.utime(cache_path, (time.time(), time.time()))

    fresh_domain = CustomDomain(
        host="new.acme.com", backend_kind=6, enabled=True, validated=True
    )
    api_calls = []

    def _fake_list(*_a, **_kw):
        api_calls.append(True)
        return [
            {
                "host": "new.acme.com",
                "backend_kind": 6,
                "enabled": True,
                "validated": True,
            }
        ]

    with patch(
        "cloudsmith_cli.credential_helpers.custom_domains.list_custom_domains",
        _fake_list,
    ):
        result = get_custom_domains("acme", api_key="k", refresh=refresh)

    if refresh:
        # API must have been called
        assert api_calls, "API must be called when refresh=True"
        assert result == [fresh_domain]
    else:
        # API must NOT have been called
        assert (
            not api_calls
        ), "API must not be called when refresh=False with valid cache"
        assert result == [cached_domain]


# ---------------------------------------------------------------------------
# 12. manage CLI — unknown helper
# ---------------------------------------------------------------------------


def test_manage_cli_unknown_helper_exits_nonzero(runner):
    """install/uninstall with an unknown helper name exits non-zero with a clear error."""
    from ....cli.commands.credential_helper.manage import install_cmd, uninstall_cmd

    for cmd in (install_cmd, uninstall_cmd):
        result = runner.invoke(cmd, ["badhelper"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 13. manage CLI dry-run
# ---------------------------------------------------------------------------


def test_manage_cli_dry_run_exits_0(runner, tmp_path, monkeypatch):
    """install docker --no-discover --dry-run exits 0."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))

    from ....cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        ["docker", "--no-discover", "--dry-run", "--bin-dir", str(tmp_path / "bin")],
    )

    assert result.exit_code == 0, result.output
    assert "would" in result.output.lower() or "dry run" in result.output.lower()


# ---------------------------------------------------------------------------
# 14. PATH warning
# ---------------------------------------------------------------------------


def test_path_warning_when_bin_dir_not_on_path(tmp_path, monkeypatch):
    """install returns a WARNING action when target bin_dir is not on PATH."""
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", "/usr/bin:/usr/local/bin")

    installer = DockerInstaller()
    actions = installer.install(bin_dir=str(bin_dir))

    warning_actions = [a for a in actions if a.startswith("WARNING")]
    assert warning_actions, f"Expected a WARNING action, got: {actions}"
    assert any("PATH" in a for a in warning_actions)


# ---------------------------------------------------------------------------
# 15. Unwritable dir → clean ClickException (no raw traceback)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="permission test only meaningful on POSIX as non-root",
)
def test_unwritable_bin_dir_gives_click_exception(runner, tmp_path, monkeypatch):
    """install with an unwritable --bin-dir exits non-zero as ClickException/SystemExit, not raw OSError."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))

    from ....cli.commands.credential_helper.manage import install_cmd

    ro_dir = tmp_path / "readonly"
    ro_dir.mkdir()
    ro_dir.chmod(0o500)

    try:
        result = runner.invoke(install_cmd, ["docker", "--bin-dir", str(ro_dir)])
    finally:
        ro_dir.chmod(0o700)

    assert result.exit_code != 0
    assert not isinstance(
        result.exception, OSError
    ), f"Raw OSError escaped: {result.exception}"


# ---------------------------------------------------------------------------
# 16. -F output format
# ---------------------------------------------------------------------------


_STUB_STATUS = {
    "launcher": "/some/bin/docker-credential-cloudsmith",
    "hosts": ["docker.cloudsmith.io"],
}


def _stub_status_fn(_self):
    return _STUB_STATUS


@pytest.mark.parametrize(
    "cmd_name,cli_args,expected_helper,expect_dry_run_key",
    [
        # install dry-run with -F json
        (
            "install_cmd",
            [
                "docker",
                "--dry-run",
                "--no-discover",
                "--bin-dir",
                "{bin_dir}",
                "-F",
                "json",
            ],
            "docker",
            True,
        ),
        # uninstall dry-run with -F json
        (
            "uninstall_cmd",
            ["docker", "--dry-run", "-F", "json"],
            "docker",
            True,
        ),
        # list with -F json
        (
            "list_cmd",
            ["-F", "json"],
            "docker",
            False,
        ),
    ],
)
def test_output_format_json(
    runner,
    tmp_path,
    monkeypatch,
    cmd_name,
    cli_args,
    expected_helper,
    expect_dry_run_key,
):
    """-F json produces valid parseable JSON with expected top-level data shape.

    Retained guard: list -F json serialises a launcher path (str), not a Path object.
    """
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))
    monkeypatch.setattr(DockerInstaller, "status", _stub_status_fn)

    from ....cli.commands.credential_helper import manage as manage_mod

    cmd = getattr(manage_mod, cmd_name)

    # Replace {bin_dir} placeholder in args
    resolved_args = [a.replace("{bin_dir}", str(tmp_path / "bin")) for a in cli_args]

    result = runner.invoke(cmd, resolved_args, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    # Pure JSON on stdout (no human text leaking before the JSON)
    assert result.output.strip().startswith(
        "{"
    ), f"Output does not start with {{: {result.output[:100]!r}"
    parsed = json.loads(result.output)
    data = parsed["data"]

    if cmd_name == "list_cmd":
        assert isinstance(data, list)
        entry = next(e for e in data if e["helper"] == expected_helper)
        assert "launcher" in entry
        assert entry["launcher"] == "/some/bin/docker-credential-cloudsmith"
        assert "hosts" in entry
    else:
        assert data["helper"] == expected_helper
        assert isinstance(data["actions"], list)
        assert isinstance(data["warnings"], list)
        if expect_dry_run_key:
            assert data["dry_run"] is True


def test_output_format_default_shows_human_text(runner, tmp_path, monkeypatch):
    """Default (no -F) install dry-run shows human-readable text, not raw JSON."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))

    from ....cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        ["docker", "--dry-run", "--no-discover", "--bin-dir", str(tmp_path / "bin")],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert "dry run" in result.output.lower() or "would" in result.output.lower()


# ---------------------------------------------------------------------------
# 17. Malformed credHelpers robustness
# ---------------------------------------------------------------------------


def test_install_coerces_malformed_cred_helpers(tmp_path, monkeypatch):
    """install coerces a non-dict credHelpers (list) rather than raising TypeError."""
    docker_dir = tmp_path / ".docker"
    docker_dir.mkdir(parents=True)
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"

    # Seed config with a malformed credHelpers value (list instead of dict)
    (docker_dir / "config.json").write_text(
        json.dumps({"credHelpers": ["not", "a", "dict"]}),
        encoding="utf-8",
    )

    installer = DockerInstaller()
    # Must not raise
    installer.install(bin_dir=str(bin_dir), discover=False)

    cfg = json.loads((docker_dir / "config.json").read_text(encoding="utf-8"))
    assert isinstance(cfg["credHelpers"], dict)
    assert cfg["credHelpers"]["docker.cloudsmith.io"] == "cloudsmith"


def test_uninstall_tolerates_malformed_cred_helpers(tmp_path, monkeypatch):
    """uninstall treats a non-dict credHelpers (string) as a no-op rather than raising."""
    docker_dir = tmp_path / ".docker"
    docker_dir.mkdir(parents=True)
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"

    # Seed config with a malformed credHelpers value (string instead of dict)
    (docker_dir / "config.json").write_text(
        json.dumps({"credHelpers": "garbage"}),
        encoding="utf-8",
    )

    installer = DockerInstaller()
    # Must not raise
    installer.uninstall(bin_dir=str(bin_dir))
