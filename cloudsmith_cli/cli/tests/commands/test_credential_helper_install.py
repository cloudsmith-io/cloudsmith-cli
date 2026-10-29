# Copyright 2026 Cloudsmith Ltd
"""Tests for credential-helper install/uninstall/list commands and launchers."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import click.testing
import pytest

from cloudsmith_cli.credential_helpers.generic import PartialInstallError
from cloudsmith_cli.credential_helpers.pnpm.installer import PNPMInstaller

from ....cli.commands.credential_helper import credential_helper
from ....core.credentials.models import CredentialResult
from ....credential_helpers.docker.installer import DockerInstaller
from ....credential_helpers.launchers import (
    UnsafeLauncherValue,
    _launcher_content,
    _launcher_filename,
    is_on_path,
    remove_launcher,
    resolve_bin_dir,
    write_launcher,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner():
    """Return a CliRunner."""
    return click.testing.CliRunner()


@pytest.fixture(autouse=True)
def clear_cloudsmith_env(monkeypatch):
    """Keep the CLOUDSMITH_* settings of the developer shell out of the installs."""
    for name in [name for name in os.environ if name.startswith("CLOUDSMITH_")]:
        monkeypatch.delenv(name)


# ---------------------------------------------------------------------------
# 1. launcher filename + content (pure, platform-parameterised)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "windows,format,expected_name,expected_content",
    [
        (
            False,
            "docker",
            "docker-credential-cloudsmith",
            '#!/bin/sh\nexec cloudsmith credential-helper docker "$@"\n',
        ),
        (
            True,
            "docker",
            "docker-credential-cloudsmith.cmd",
            "@echo off\r\ncloudsmith credential-helper docker %*\r\n",
        ),
        (
            False,
            "pnpm",
            "pnpm-credential-cloudsmith",
            '#!/bin/sh\nexec cloudsmith credential-helper pnpm "$@"\n',
        ),
        (
            True,
            "pnpm",
            "pnpm-credential-cloudsmith.cmd",
            "@echo off\r\ncloudsmith credential-helper pnpm %*\r\n",
        ),
    ],
)
def test_launcher_filename_and_content(
    windows, format, expected_name, expected_content
):
    """Per-platform launcher name + body — guards the exact Windows .cmd bytes.

    Parameterised on ``windows`` rather than patching ``os.name`` so no
    ``pathlib.Path`` is built under a faked platform (which raises
    ``NotImplementedError`` on Python < 3.12).
    """
    assert (
        _launcher_filename(f"{format}-credential-cloudsmith", windows=windows)
        == expected_name
    )
    assert (
        _launcher_content(f"cloudsmith credential-helper {format}", windows=windows)
        == expected_content
    )


@pytest.mark.parametrize(
    "profile,value,expected",
    [
        ("C:\\Users\\jo", "C:\\Users\\jo\\a b&c!", "C:\\Users\\jo\\a b&c!"),
        (
            "C:\\Users\\José",
            "c:\\users\\josé\\cs\\config.ini",
            "%USERPROFILE%\\cs\\config.ini",
        ),
    ],
)
def test_windows_launcher_settings_are_ascii(monkeypatch, profile, value, expected):
    """cmd.exe reads a batch file in the console code page, not UTF-8.

    Only a non-ASCII path under the user profile is written as %USERPROFILE%,
    because another account that runs the package manager has a different
    profile.
    """
    monkeypatch.setenv("USERPROFILE", profile)
    content = _launcher_content("cmd", windows=True, env={"CLOUDSMITH_X": value})
    assert content == (
        "@echo off\r\nsetlocal DisableDelayedExpansion\r\n"
        f'set "CLOUDSMITH_X={expected}"\r\ncmd %*\r\n'
    )


@pytest.mark.parametrize("value", ["%PATH%", "D:\\Données"])
def test_windows_launcher_refuses_a_value_a_batch_file_cannot_hold(monkeypatch, value):
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\José")
    with pytest.raises(UnsafeLauncherValue, match="CLOUDSMITH_PROFILE"):
        _launcher_content("cmd", windows=True, env={"CLOUDSMITH_PROFILE": value})


def test_install_passes_flag_and_environment_settings_to_the_launcher(
    runner, monkeypatch, tmp_path
):
    """Settings from flags and CLOUDSMITH_* variables go to the launcher.

    A value read from a config file does not, because the helper reads that
    file itself.  Secrets and the proxy never go to the launcher.  A flag on
    the parent command also counts.
    """
    from ....cli.commands.credential_helper import manage
    from ....cli.commands.main import main

    launcher_env = {}

    class SettingsInstaller:
        KEEPS_INSTALL_TIME_SETTINGS = True

        def install(self, **kwargs):
            launcher_env.update(kwargs["launcher_env"])
            return []

    monkeypatch.setitem(manage._INSTALLERS, "settings", SettingsInstaller)
    config = tmp_path / "config.ini"
    config.write_text("[default]\nssl_verify_strict = false\n")
    result = runner.invoke(
        main,
        args=[
            "-P",
            "work",
            "credential-helper",
            "install",
            "settings",
            "-w",
            "acme",
            "--config-file",
            str(config),
            "--api-host",
            "https://api.example.com",
            "--proxy",
            "http://proxy.example.com:3128",
            "-S",
        ],
        env={
            "CLOUDSMITH_API_KEY": "k_secret",
            "CLOUDSMITH_API_HEADERS": "X-Secret=1",
            "CLOUDSMITH_KEYRING_KEY": "keyring_secret",
            "CLOUDSMITH_KEYRING_DIR": "/var/keyring",
            "CLOUDSMITH_OIDC_AUDIENCE": "cloudsmith-test",
            "CLOUDSMITH_SERVICE_SLUG": "ci-bot",
        },
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert launcher_env == {
        "CLOUDSMITH_WORKSPACE": "acme",
        "CLOUDSMITH_PROFILE": "work",
        "CLOUDSMITH_CONFIG_FILE": str(config.resolve()),
        "CLOUDSMITH_API_HOST": "https://api.example.com",
        "CLOUDSMITH_WITHOUT_API_SSL_VERIFY": "true",
        "CLOUDSMITH_OIDC_AUDIENCE": "cloudsmith-test",
        "CLOUDSMITH_SERVICE_SLUG": "ci-bot",
        "CLOUDSMITH_KEYRING_DIR": "/var/keyring",
    }


# ---------------------------------------------------------------------------
# 2. write_launcher / remove_launcher — end-to-end on the host platform
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "format",
    [
        "docker",
        "pnpm",
    ],
)
def test_write_launcher_writes_executable_script(format, tmp_path):
    """write_launcher writes the shim with content + 0o755 on the host platform."""
    dest = write_launcher(
        tmp_path,
        f"{format}-credential-cloudsmith",
        f"cloudsmith credential-helper {format}",
    )
    expected = f'#!/bin/sh\nexec cloudsmith credential-helper {format} "$@"\n'
    assert dest.read_text(encoding="utf-8") == expected
    assert stat.S_IMODE(dest.stat().st_mode) == 0o755


@pytest.mark.parametrize(
    "format",
    [
        "docker",
        "pnpm",
    ],
)
def test_remove_launcher(format, tmp_path):
    """remove_launcher returns True + file gone when present, False when absent."""
    write_launcher(
        tmp_path,
        f"{format}-credential-cloudsmith",
        f"cloudsmith credential-helper {format}",
    )
    launcher = f"{format}-credential-cloudsmith"
    assert (tmp_path / launcher).exists()
    assert remove_launcher(tmp_path, launcher) is True
    assert not (tmp_path / launcher).exists()

    # Second call: file is gone now
    assert remove_launcher(tmp_path, launcher) is False


# ---------------------------------------------------------------------------
# 3. resolve_bin_dir + user-bin (no os.name faking)
# ---------------------------------------------------------------------------


def test_resolve_bin_dir_override_absolute(tmp_path):
    """An absolute path override is returned as an absolute path."""
    absolute_path = tmp_path.resolve()
    assert resolve_bin_dir(str(absolute_path)) == absolute_path


def test_resolve_bin_dir_override_relative_simple(tmp_path, monkeypatch):
    """A relative path override is resolved to an absolute path.

    If we're in /path/from/root/to and give 'launcher/bin', it returns
    /path/from/root/to/launcher/bin.
    """
    monkeypatch.chdir(tmp_path)
    relative_override = "launcher/bin"
    result = resolve_bin_dir(relative_override)

    # Result should be absolute
    assert result.is_absolute()

    # Result should be correct: cwd / relative_override
    expected = tmp_path / relative_override
    assert result == expected


def test_resolve_bin_dir_override_relative_parent(tmp_path, monkeypatch):
    """A relative path with parent directory references is resolved correctly.

    If we're in /path/from/root/to/randomdir and give '../launcher/bin',
    it returns /path/from/root/to/launcher/bin.
    """
    # Create subdirectory structure
    random_dir = tmp_path / "randomdir"
    random_dir.mkdir()

    monkeypatch.chdir(random_dir)
    relative_override = "../launcher/bin"
    result = resolve_bin_dir(relative_override)

    # Result should be absolute
    assert result.is_absolute()

    # Result should be correct: (cwd / parent / launcher / bin)
    expected = tmp_path / "launcher" / "bin"
    assert result == expected


def test_resolve_bin_dir_override_relative_current_dir(tmp_path, monkeypatch):
    """A relative path starting with './' is resolved correctly."""
    monkeypatch.chdir(tmp_path)
    relative_override = "./locally-scoped-dir"
    result = resolve_bin_dir(relative_override)

    # Result should be absolute
    assert result.is_absolute()

    # Result should be correct
    expected = tmp_path / "locally-scoped-dir"
    assert result == expected


def test_resolve_bin_dir_defaults_to_cloudsmith_bin(tmp_path, monkeypatch):
    """Without an override the launcher goes to ``~/.cloudsmith/bin``."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert resolve_bin_dir() == tmp_path / ".cloudsmith" / "bin"


def test_list_finds_a_launcher_installed_to_the_default_dir(
    runner, tmp_path, monkeypatch
):
    """`list` looks for launchers where `install` puts them by default."""
    from ....cli.commands.credential_helper.manage import install_cmd, list_cmd

    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))
    result = runner.invoke(
        install_cmd, ["docker", "--no-discover"], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(list_cmd, ["-F", "json"], catch_exceptions=False)

    docker = next(
        e for e in json.loads(result.stdout)["data"] if e["helper"] == "docker"
    )
    assert docker["launcher"] == str(
        tmp_path / ".cloudsmith" / "bin" / "docker-credential-cloudsmith"
    )


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


def test_pnpm_installer_install(tmp_path: Path, monkeypatch: MonkeyPatch):
    """install sets default+extra domains, preserves foreign entries, writes the launcher."""
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", str(bin_dir))

    # Seed a config with foreign data that must be preserved
    npm_path.write_text("//registry.npmjs.org/:_authToken=abc123")

    installer = PNPMInstaller()
    actions = installer.install(
        bin_dir=str(bin_dir), domains=("my.registry.example.com",)
    )

    assert (
        npm_path.read_text() == "//registry.npmjs.org/:_authToken=abc123\n"
        f"//npm.cloudsmith.io/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith\n"
        f"//my.registry.example.com/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith\n"
    )
    assert actions[1:] == [
        f"set //npm.cloudsmith.io/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith"
        f" in {npm_path}",
        f"set //my.registry.example.com/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith"
        f" in {npm_path}",
    ]
    # Launcher written
    assert (bin_dir / "pnpm-credential-cloudsmith").exists()


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


def test_pnpm_installer_dry_run(tmp_path, monkeypatch):
    """dry_run=True: no launcher written, config.json absent, returns planned strings."""
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"

    installer = PNPMInstaller()
    actions = installer.install(bin_dir=str(bin_dir), dry_run=True)

    assert not (bin_dir / "pnpm-credential-cloudsmith").exists()
    assert not npm_path.exists()
    assert any("would write launcher" in a for a in actions)
    assert any(a.startswith("would set //npm.cloudsmith.io/") for a in actions)


def test_pnpm_installer_dry_run_updates_existing_tokenhelper(tmp_path, monkeypatch):
    """dry_run with existing tokenHelper reports update same as adding new entry.

    When re-installing with a different bin_dir, the dry-run should report
    the update using the same "would set" format as if adding a new entry.
    """
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    old_bin_dir = tmp_path / "old_bin"
    new_bin_dir = tmp_path / "new_bin"

    # Seed config with existing tokenHelper entry
    npm_path.write_text(
        f"//npm.cloudsmith.io/:tokenHelper={old_bin_dir}/pnpm-credential-cloudsmith\n"
    )

    # Re-install with different bin_dir in dry-run mode
    installer = PNPMInstaller()
    actions = installer.install(
        bin_dir=str(new_bin_dir), domains=("npm.cloudsmith.io",), dry_run=True
    )

    # Verify no files were created/modified
    assert not (new_bin_dir / "pnpm-credential-cloudsmith").exists()
    assert npm_path.read_text().startswith(
        f"//npm.cloudsmith.io/:tokenHelper={old_bin_dir}"
    )

    # Verify dry-run reported the update as a "would set" action
    # Same format as if it were being added for the first time
    assert any("would write launcher" in a for a in actions)
    assert any(a.startswith("would set //npm.cloudsmith.io/") for a in actions)
    assert any(str(new_bin_dir) in a for a in actions), (
        "Actions should mention the new bin_dir path"
    )


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


def test_pnpm_installer_idempotent(tmp_path, monkeypatch):
    """Second install run reports no change (config mtime unchanged, 'already up to date')."""
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"

    installer = PNPMInstaller()
    installer.install(bin_dir=str(bin_dir))

    mtime_before = npm_path.stat().st_mtime
    actions = installer.install(bin_dir=str(bin_dir))
    mtime_after = npm_path.stat().st_mtime

    assert mtime_before == mtime_after
    assert any("already up to date" in a for a in actions)


def test_pnpm_installer_adds_missing_final_newline(tmp_path, monkeypatch):
    """A reinstall adds the final newline that an earlier version left out."""
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"
    entry = f"//npm.cloudsmith.io/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith"
    npm_path.write_text(entry)

    PNPMInstaller().install(bin_dir=str(bin_dir), discover=False)

    assert npm_path.read_text() == f"{entry}\n"


def test_pnpm_installer_updates_tokenhelper_with_different_bin_dir(
    tmp_path: Path, monkeypatch: MonkeyPatch
):
    """Re-installing with a different bin_dir updates the tokenHelper path.

    When an entry with tokenHelper already exists for a domain, calling install
    again with a different bin_dir should overwrite the old launcher path with
    the new one. Verifies that only the matching domain entries are updated.
    """
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    old_bin_dir = tmp_path / "old_bin"
    new_bin_dir = tmp_path / "new_bin"

    # Seed config with existing tokenHelper entries for domains that will be
    # re-installed, plus one unrelated entry
    npm_path.write_text(
        f"//npm.cloudsmith.io/:tokenHelper={old_bin_dir}/pnpm-credential-cloudsmith\n"
        f"//my.custom.domain/:tokenHelper={old_bin_dir}/pnpm-credential-cloudsmith\n"
        "//registry.npmjs.org/:_authToken=abc123"
    )

    # Re-install with new bin_dir for the same domains that already exist
    installer = PNPMInstaller()
    installer.install(bin_dir=str(new_bin_dir), domains=("my.custom.domain",))

    content = npm_path.read_text()

    # Verify old paths are replaced with new ones for managed domains
    assert (
        f"//npm.cloudsmith.io/:tokenHelper={new_bin_dir}/pnpm-credential-cloudsmith"
        in content
    ), "npm.cloudsmith.io should be updated to new_bin_dir"

    assert (
        f"//my.custom.domain/:tokenHelper={new_bin_dir}/pnpm-credential-cloudsmith"
        in content
    ), "my.custom.domain should be updated to new_bin_dir"

    # Verify old bin_dir paths are gone
    assert f"{old_bin_dir}" not in content, (
        "All old bin_dir paths should be replaced with new_bin_dir"
    )

    # Verify non-cloudsmith entries are preserved
    assert "//registry.npmjs.org/:_authToken=abc123" in content, (
        "Non-cloudsmith entries should be preserved"
    )

    # Verify launcher exists in new location
    assert (new_bin_dir / "pnpm-credential-cloudsmith").exists()


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


@pytest.mark.parametrize("dry_run", [False, True])
def test_docker_uninstall_without_config_creates_nothing(
    dry_run, tmp_path, monkeypatch
):
    """uninstall with no config.json creates no file and claims no removal."""
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))

    actions = DockerInstaller().uninstall(
        bin_dir=str(tmp_path / "bin"), dry_run=dry_run
    )

    assert not docker_dir.exists()
    assert any("no credHelpers entries to remove" in a for a in actions)


def test_pnpm_installer_uninstall(tmp_path: Path, monkeypatch):
    """uninstall removes only cloudsmith entries (foreign kept) + removes launcher.

    Also verifies --bin-dir: install to custom dir, uninstall with same --bin-dir removes it.
    """
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    custom_bin_dir = tmp_path / "custom_bin"

    # Install to a custom bin dir
    installer = PNPMInstaller()
    npm_path.write_text(
        "//registry.npmjs.org/:_authToken=abc123\n"
        f"//npm.cloudsmith.io/:tokenHelper={custom_bin_dir}/pnpm-credential-cloudsmith\n"
        f"//my.custom.domain/:tokenHelper={custom_bin_dir}/pnpm-credential-cloudsmith"
    )
    # Install launcher to custom_bin_dir
    installer.install(bin_dir=str(custom_bin_dir))
    launcher = custom_bin_dir / "pnpm-credential-cloudsmith"
    assert launcher.exists(), "Precondition: launcher must exist after install"

    # Uninstall — removes cloudsmith keys and launcher
    installer.uninstall(bin_dir=str(custom_bin_dir))

    assert npm_path.read_text() == "//registry.npmjs.org/:_authToken=abc123\n"
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
    assert isinstance(launcher, str), (
        f"status()['launcher'] must be str, got {type(launcher).__name__!r}"
    )
    assert launcher.endswith("docker-credential-cloudsmith")
    assert not isinstance(launcher, Path)


def test_pnpm_installer_status_type_contract(tmp_path: Path, monkeypatch: MonkeyPatch):
    """status()['launcher'] is str when installed and None when not — never a Path.

    Retained guard: the -F json Path-serialization regression.
    """
    npm_path = tmp_path / ".npm"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"

    installer = PNPMInstaller()

    # Before install: launcher is None
    with patch(
        "cloudsmith_cli.credential_helpers.pnpm.installer.resolve_bin_dir",
        return_value=bin_dir,
    ):
        result_before = installer.status()

    assert result_before["launcher"] is None
    assert not isinstance(result_before["launcher"], Path)

    # After install: launcher is a non-None str
    installer.install(bin_dir=str(bin_dir))
    with patch(
        "cloudsmith_cli.credential_helpers.pnpm.installer.resolve_bin_dir",
        return_value=bin_dir,
    ):
        result_after = installer.status()

    launcher = result_after["launcher"]
    assert launcher is not None
    assert isinstance(launcher, str), (
        f"status()['launcher'] must be str, got {type(launcher).__name__!r}"
    )
    assert launcher.endswith("pnpm-credential-cloudsmith")
    assert not isinstance(launcher, Path)


def test_pnpm_installer_status_lists_hosts_of_a_bin_dir_install(
    tmp_path: Path, monkeypatch: MonkeyPatch
):
    """status() reports .npmrc hosts whose launcher is not in the default bin dir."""
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(tmp_path / ".npmrc"))
    bin_dir = tmp_path / "bin"
    installer = PNPMInstaller()
    installer.install(bin_dir=str(tmp_path / "custom-bin"))

    with patch(
        "cloudsmith_cli.credential_helpers.pnpm.installer.resolve_bin_dir",
        return_value=bin_dir,
    ):
        result = installer.status()

    assert result == {"launcher": None, "hosts": [PNPMInstaller.DEFAULT_HOST]}


# ---------------------------------------------------------------------------
# 10. autodiscovery
# ---------------------------------------------------------------------------

_INSTALLER_GET_FORMAT_DOMAINS = (
    "cloudsmith_cli.credential_helpers.docker.installer.get_format_domains"
)


def test_docker_install_uses_the_cloudsmith_owned_host_the_api_lists(
    tmp_path, monkeypatch
):
    """Another API host lists its own Docker host, so the default is not added."""
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(
        _INSTALLER_GET_FORMAT_DOMAINS,
        lambda *_a, **_kw: ["docker.acme.com", "docker.example.com"],
    )

    DockerInstaller().install(
        bin_dir=str(bin_dir),
        org="acme",
        credential=CredentialResult(api_key="k_test", source_name="test"),
    )

    cfg = json.loads((docker_dir / "config.json").read_text())
    assert sorted(cfg["credHelpers"]) == ["docker.acme.com", "docker.example.com"]


def test_pnpm_install_uses_the_cloudsmith_owned_host_the_api_lists(
    tmp_path, monkeypatch
):
    """Another API host lists its own npm host, so the default is not added."""
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.pnpm.installer.get_format_domains",
        lambda *_a, **_kw: ["npm.acme.com", "npm.example.com"],
    )

    PNPMInstaller().install(
        bin_dir=str(bin_dir),
        org="acme",
        credential=CredentialResult(api_key="k_test", source_name="test"),
    )

    assert npm_path.read_text() == (
        f"//npm.acme.com/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith\n"
        f"//npm.example.com/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith\n"
    )


@pytest.mark.parametrize(
    "scenario",
    [
        "discovery_on",
        "no_discover",
        "missing_org",
        "missing_credential",
        "blank_credential",
        "dry_run",
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

    credential = CredentialResult(api_key="k_test", source_name="test")

    if scenario == "discovery_on":
        captured = {}

        def _fake_get_format_domains(*_a, **kwargs):
            captured.update(kwargs)
            return ["docker.acme.com", "docker.cloudsmith.io"]

        monkeypatch.setattr(_INSTALLER_GET_FORMAT_DOMAINS, _fake_get_format_domains)
        installer = DockerInstaller()
        actions = installer.install(
            bin_dir=str(bin_dir), discover=True, org="acme", credential=credential
        )
        cfg = json.loads((docker_dir / "config.json").read_text())
        assert cfg["credHelpers"]["docker.cloudsmith.io"] == "cloudsmith"
        assert cfg["credHelpers"]["docker.acme.com"] == "cloudsmith"
        assert any("discovered" in a and "1" in a for a in actions)
        assert captured["credential"] is credential

    elif scenario == "no_discover":
        called = []

        def _should_not_be_called(*_a, **_kw):
            called.append(True)
            return []

        monkeypatch.setattr(_INSTALLER_GET_FORMAT_DOMAINS, _should_not_be_called)
        installer = DockerInstaller()
        installer.install(
            bin_dir=str(bin_dir), discover=False, org="acme", credential=credential
        )
        assert not called, "get_format_domains must not be called when discover=False"
        cfg = json.loads((docker_dir / "config.json").read_text())
        assert "docker.cloudsmith.io" in cfg["credHelpers"]
        assert "docker.acme.com" not in cfg["credHelpers"]

    elif scenario in ("missing_org", "missing_credential", "blank_credential"):
        called = []

        def _should_not_be_called(*_a, **_kw):
            called.append(True)
            return []

        monkeypatch.setattr(_INSTALLER_GET_FORMAT_DOMAINS, _should_not_be_called)
        installer = DockerInstaller()
        org = None if scenario == "missing_org" else "acme"
        creds = {
            "missing_org": credential,
            "missing_credential": None,
            "blank_credential": CredentialResult(api_key="", source_name="test"),
        }
        installer.install(
            bin_dir=str(bin_dir), discover=True, org=org, credential=creds[scenario]
        )
        assert not called, (
            "get_format_domains must not be called when org/credential absent"
        )
        cfg = json.loads((docker_dir / "config.json").read_text())
        assert cfg["credHelpers"]["docker.cloudsmith.io"] == "cloudsmith"

    elif scenario == "dry_run":
        called = []

        def _should_not_be_called(*_a, **_kw):
            called.append(True)
            return []

        monkeypatch.setattr(_INSTALLER_GET_FORMAT_DOMAINS, _should_not_be_called)
        installer = DockerInstaller()
        actions = installer.install(
            bin_dir=str(bin_dir),
            discover=True,
            org="acme",
            credential=credential,
            dry_run=True,
        )
        assert not called, "a dry run must not query the custom-domain API"
        assert not (docker_dir / "config.json").exists()
        assert any("skipped custom-domain auto-discovery" in a for a in actions)

    else:  # discovery_raises — graceful failure guard

        def _raise(*_a, **_kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(_INSTALLER_GET_FORMAT_DOMAINS, _raise)
        installer = DockerInstaller()
        # Must NOT raise
        actions = installer.install(
            bin_dir=str(bin_dir), discover=True, org="acme", credential=credential
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

    from ....credential_helpers.domains import (
        domain_from_payload,
        get_cache_path,
        get_workspace_domains,
        write_cache,
    )

    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )

    def _payload(name):
        return {
            "domain_name": name,
            "domain_type": "NATIVE_DOCKER",
            "domain_scope": "WORKSPACE",
            "repository": None,
        }

    cache_path = get_cache_path("acme")
    write_cache(cache_path, "acme", [_payload("docker.acme.com")])
    os.utime(cache_path, (time.time(), time.time()))

    api_calls = []

    def _fake_list(*_a, **_kw):
        api_calls.append(True)
        return [_payload("new.acme.com")]

    with patch(
        "cloudsmith_cli.core.api.workspaces.list_domains",
        _fake_list,
    ):
        result = get_workspace_domains(
            "acme",
            credential=CredentialResult(api_key="k", source_name="test"),
            refresh=refresh,
        )

    if refresh:
        # API must have been called
        assert api_calls, "API must be called when refresh=True"
        assert result == [domain_from_payload(_payload("new.acme.com"), "acme")]
    else:
        # API must NOT have been called
        assert not api_calls, (
            "API must not be called when refresh=False with valid cache"
        )
        assert result == [domain_from_payload(_payload("docker.acme.com"), "acme")]


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


@pytest.mark.parametrize(
    "helper",
    [
        "docker",
        "pnpm",
    ],
)
def test_manage_cli_dry_run_exits_0(helper, runner, tmp_path, monkeypatch):
    """install docker --no-discover --dry-run exits 0."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(tmp_path / ".npmrc"))

    from ....cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        [helper, "--no-discover", "--dry-run", "--bin-dir", str(tmp_path / "bin")],
    )

    assert result.exit_code == 0, result.output
    assert "would" in result.output.lower() or "dry run" in result.output.lower()


@pytest.mark.parametrize(
    "format,installer",
    [
        ("docker", DockerInstaller),
        ("pnpm", PNPMInstaller),
    ],
)
def test_manage_cli_passes_resolved_credential_to_installer(
    format, installer, runner, tmp_path, monkeypatch
):
    """install hands the resolved CredentialResult to the installer intact."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(tmp_path / ".npmrc"))

    from ....cli.commands.credential_helper.manage import install_cmd

    with patch.object(installer, "install", return_value=[]) as mock_install:
        result = runner.invoke(
            install_cmd,
            [
                format,
                "--no-discover",
                "--bin-dir",
                str(tmp_path / "bin"),
                "--api-key",
                "k_flag",
            ],
        )

    assert result.exit_code == 0, result.output
    credential = mock_install.call_args.kwargs["credential"]
    assert isinstance(credential, CredentialResult)
    assert credential.api_key == "k_flag"


# ---------------------------------------------------------------------------
# 14. PATH warning
# ---------------------------------------------------------------------------


def test_docker_path_warning_when_bin_dir_not_on_path(tmp_path, monkeypatch):
    """install returns a WARNING action when target bin_dir is not on PATH."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", "/usr/bin:/usr/local/bin")

    installer = DockerInstaller()
    actions = installer.install(bin_dir=str(bin_dir))

    warning_actions = [a for a in actions if a.startswith("WARNING")]
    assert warning_actions, f"Expected a WARNING action, got: {actions}"
    assert any("PATH" in a for a in warning_actions)


def test_pnpm_no_path_warning_when_bin_dir_not_on_path(tmp_path, monkeypatch):
    """install returns a WARNING action when target bin_dir is not on PATH."""
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(tmp_path / ".npmrc"))
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", "/usr/bin:/usr/local/bin")

    installer = PNPMInstaller()
    actions = installer.install(bin_dir=str(bin_dir))

    warning_actions = [a for a in actions if a.startswith("WARNING")]
    assert not warning_actions, f"Expected no WARNING action, got: {actions}"


# ---------------------------------------------------------------------------
# 15. Unwritable dir → clean ClickException (no raw traceback)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="permission test only meaningful on POSIX as non-root",
)
@pytest.mark.parametrize(
    "format",
    [
        "docker",
        "pnpm",
    ],
)
def test_unwritable_bin_dir_gives_click_exception(
    format, runner, tmp_path, monkeypatch
):
    """install with an unwritable --bin-dir exits non-zero as ClickException/SystemExit, not raw OSError."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(tmp_path / ".npmrc"))

    from ....cli.commands.credential_helper.manage import install_cmd

    ro_dir = tmp_path / "readonly"
    ro_dir.mkdir()
    ro_dir.chmod(0o500)

    try:
        result = runner.invoke(install_cmd, [format, "--bin-dir", str(ro_dir)])
    finally:
        ro_dir.chmod(0o700)

    assert result.exit_code != 0
    assert not isinstance(result.exception, OSError), (
        f"Raw OSError escaped: {result.exception}"
    )


# ---------------------------------------------------------------------------
# 16. -F output format
# ---------------------------------------------------------------------------


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
        (
            "install_cmd",
            [
                "pnpm",
                "--dry-run",
                "--no-discover",
                "--bin-dir",
                "{bin_dir}",
                "-F",
                "json",
            ],
            "pnpm",
            True,
        ),
        # uninstall dry-run with -F json
        (
            "uninstall_cmd",
            ["docker", "--dry-run", "-F", "json"],
            "docker",
            True,
        ),
        (
            "uninstall_cmd",
            ["pnpm", "--dry-run", "-F", "json"],
            "pnpm",
            True,
        ),
        # list with -F json
        (
            "list_cmd",
            ["-F", "json"],
            "docker",
            False,
        ),
        (
            "list_cmd",
            ["-F", "json"],
            "pnpm",
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

    def _docker_stub_status_fn(_self):
        return {
            "launcher": "/some/bin/docker-credential-cloudsmith",
            "hosts": ["docker.cloudsmith.io"],
        }

    def _pnpm_stub_status_fn(_self):
        return {
            "launcher": "/some/bin/pnpm-credential-cloudsmith",
            "hosts": ["npm.cloudsmith.io"],
        }

    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(tmp_path / ".npmrc"))
    monkeypatch.setattr(DockerInstaller, "status", _docker_stub_status_fn)
    monkeypatch.setattr(PNPMInstaller, "status", _pnpm_stub_status_fn)

    from ....cli.commands.credential_helper import manage as manage_mod

    cmd = getattr(manage_mod, cmd_name)

    # Replace {bin_dir} placeholder in args
    resolved_args = [a.replace("{bin_dir}", str(tmp_path / "bin")) for a in cli_args]

    result = runner.invoke(cmd, resolved_args, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    # Pure JSON on stdout (no human text leaking before the JSON)
    assert result.output.strip().startswith("{"), (
        f"Output does not start with {{: {result.output[:100]!r}"
    )
    parsed = json.loads(result.output)
    data = parsed["data"]

    if cmd_name == "list_cmd":
        assert isinstance(data, list)
        entry = next(e for e in data if e["helper"] == expected_helper)
        assert "launcher" in entry
        assert entry["launcher"] == f"/some/bin/{expected_helper}-credential-cloudsmith"
        assert "hosts" in entry
    else:
        assert data["helper"] == expected_helper
        assert isinstance(data["actions"], list)
        assert isinstance(data["warnings"], list)
        if expect_dry_run_key:
            assert data["dry_run"] is True


@pytest.mark.parametrize("helper", ["docker", "pnpm"])
def test_output_format_default_shows_human_text(helper, runner, tmp_path, monkeypatch):
    """Default (no -F) install dry-run shows human-readable text, not raw JSON."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(tmp_path / ".npmrc"))

    from ....cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        [helper, "--dry-run", "--no-discover", "--bin-dir", str(tmp_path / "bin")],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert "dry run" in result.output.lower() or "would" in result.output.lower()


# ---------------------------------------------------------------------------
# 17. Malformed credHelpers robustness
# ---------------------------------------------------------------------------


def test_docker_install_coerces_malformed_cred_helpers(tmp_path, monkeypatch):
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


def test_pnpm_install_coerces_malformed_cred_helpers(tmp_path: Path, monkeypatch):
    """install coerces a non-dict credHelpers (list) rather than raising TypeError."""
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"

    # Seed config with a malformed credHelpers value (list instead of dict)
    npm_path.write_text(
        "badtext\n//registry.npmjs.org/:_authToken=abc123\nmorebadtext\n"
    )

    installer = PNPMInstaller()
    # Must not raise
    installer.install(bin_dir=str(bin_dir), discover=False)

    assert (
        npm_path.read_text() == "badtext\n"
        "//registry.npmjs.org/:_authToken=abc123\n"
        "morebadtext\n"
        f"//npm.cloudsmith.io/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith\n"
    )


def test_docker_uninstall_tolerates_malformed_cred_helpers(tmp_path, monkeypatch):
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


def test_pnpm_uninstall_tolerates_malformed_cred_helpers(tmp_path: Path, monkeypatch):
    """uninstall treats a non-dict credHelpers (string) as a no-op rather than raising."""
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"

    # Seed config with a malformed credHelpers value (string instead of dict)
    npm_path.write_text(
        "badtext\n"
        "//registry.npmjs.org/:_authToken=abc123\n"
        "morebadtext\n"
        f"//npm.cloudsmith.io/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith"
    )

    installer = PNPMInstaller()
    # Must not raise
    installer.uninstall(bin_dir=str(bin_dir))

    assert (
        npm_path.read_text()
        == "badtext\n//registry.npmjs.org/:_authToken=abc123\nmorebadtext\n"
    )


@pytest.mark.parametrize(
    "helper,config_name,content",
    [
        ("docker", ".docker/config.json", b'{"credHelpers": ["x"]}'),
        ("docker", ".docker/config.json", b"\xff\xfe"),
        ("pnpm", ".npmrc", b"\xff\xfe"),
        ("pnpm", ".npmrc", None),
        ("terraform", ".terraformrc", b"\xff\xfe"),
    ],
)
def test_list_shows_a_helper_with_a_bad_config_as_not_configured(
    runner, tmp_path: Path, monkeypatch, helper: str, config_name: str, content
):
    """`list` reports no hosts for a bad config file and still lists every helper."""
    from ....cli.commands.credential_helper.manage import _INSTALLERS, list_cmd

    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(tmp_path / ".npmrc"))
    monkeypatch.setenv("TF_CLI_CONFIG_FILE", str(tmp_path / ".terraformrc"))
    monkeypatch.setenv("CARGO_HOME", str(tmp_path / ".cargo"))
    config_path = tmp_path / config_name
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        config_path.mkdir()
    else:
        config_path.write_bytes(content)

    result = runner.invoke(list_cmd, ["-F", "json"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert sorted(e["helper"] for e in data) == sorted(_INSTALLERS)
    assert next(e for e in data if e["helper"] == helper)["hosts"] == []


@pytest.mark.parametrize("char", [";", "#"])
def test_pnpm_uninstall_tolerates_comments(char, tmp_path: Path, monkeypatch):
    """uninstall treats a non-dict credHelpers (string) as a no-op rather than raising."""
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"

    # Seed config with a malformed credHelpers value (string instead of dict)
    npm_path.write_text(
        "//registry.npmjs.org/:_authToken=abc123\n"
        f"//npm.cloudsmith.io/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith{char}wowcommented"
    )

    installer = PNPMInstaller()
    # Must not raise
    installer.uninstall(bin_dir=str(bin_dir))

    assert npm_path.read_text() == "//registry.npmjs.org/:_authToken=abc123\n"


def test_pnpm_uninstall_tolerates_leading_whitespace(tmp_path: Path, monkeypatch):
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"

    # Seed config with a malformed credHelpers value (string instead of dict)
    npm_path.write_text(
        "//registry.npmjs.org/:_authToken=abc123\n"
        f"   //npm.cloudsmith.io/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith\n"
        "//unrelated.registry/:_authToken=abc123"
    )

    installer = PNPMInstaller()
    # Must not raise
    installer.uninstall(bin_dir=str(bin_dir))

    assert (
        npm_path.read_text()
        == "//registry.npmjs.org/:_authToken=abc123\n//unrelated.registry/:_authToken=abc123\n"
    )


def test_pnpm_uninstall_preserves_leading_whitespace(tmp_path: Path, monkeypatch):
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"

    # Seed config with a malformed credHelpers value (string instead of dict)
    npm_path.write_text(
        "    //registry.npmjs.org/:_authToken=abc123\n"
        f"//npm.cloudsmith.io/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith\n"
        "//unrelated.registry/:_authToken=abc123"
    )

    installer = PNPMInstaller()
    # Must not raise
    installer.uninstall(bin_dir=str(bin_dir))

    assert (
        npm_path.read_text()
        == "    //registry.npmjs.org/:_authToken=abc123\n//unrelated.registry/:_authToken=abc123\n"
    )


@pytest.mark.parametrize("kind", ["_auth", "_authToken", "_password"])
def test_pnpm_install_warn_on_auth_configured(kind, tmp_path: Path, monkeypatch):
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"

    npm_path.write_text(f"//npm.cloudsmith.io/:{kind}=token")

    installer = PNPMInstaller()
    with pytest.raises(PartialInstallError) as e:
        installer.install(bin_dir=str(bin_dir), discover=False)
    assert e.value.exit_code == 1
    actions = e.value.actions

    # file only got its final newline
    assert npm_path.read_text() == f"//npm.cloudsmith.io/:{kind}=token\n"

    warning_actions = [a for a in actions if a.startswith("WARNING")]
    assert warning_actions, f"Expected a WARNING action, got: {actions}"


@pytest.mark.parametrize("kind", ["_auth", "_authToken", "_password"])
def test_pnpm_install_warn_on_auth_configured_partial_write(
    kind, tmp_path: Path, monkeypatch
):
    npm_path = tmp_path / ".npmrc"
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(npm_path))
    bin_dir = tmp_path / "bin"

    npm_path.write_text(f"//npm.cloudsmith.io/:{kind}=token")

    installer = PNPMInstaller()
    with pytest.raises(PartialInstallError) as e:
        installer.install(
            bin_dir=str(bin_dir), discover=False, domains=("my.registry.example.com",)
        )

    assert e.value.exit_code == 1
    actions = e.value.actions

    # file was partially written to
    assert (
        npm_path.read_text() == f"//npm.cloudsmith.io/:{kind}=token\n"
        f"//my.registry.example.com/:tokenHelper={bin_dir}/pnpm-credential-cloudsmith\n"
    )

    warning_actions = [a for a in actions if a.startswith("WARNING")]
    assert warning_actions, f"Expected a WARNING action, got: {actions}"


# ---------------------------------------------------------------------------
# 18. frozen-binary launcher target (PyInstaller standalone)
# ---------------------------------------------------------------------------


def test_default_install_launcher_uses_bare_command(tmp_path, monkeypatch):
    """A pip/source install writes a launcher that forwards to the bare
    ``cloudsmith`` command resolved via PATH."""
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", str(bin_dir))

    DockerInstaller().install(bin_dir=str(bin_dir), discover=False)

    body = (bin_dir / "docker-credential-cloudsmith").read_text(encoding="utf-8")
    assert "exec cloudsmith credential-helper docker" in body


def test_frozen_install_launcher_targets_executable(tmp_path, monkeypatch):
    """A frozen install writes a launcher that execs the absolute executable.

    A standalone binary is not guaranteed to be on PATH as ``cloudsmith``, so a
    bare-command launcher would leave Docker unable to find the helper.
    """
    docker_dir = tmp_path / ".docker"
    monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", str(bin_dir))
    exe = tmp_path / "price$USD dir" / "cloudsmith"

    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", str(exe)),
    ):
        DockerInstaller().install(bin_dir=str(bin_dir), discover=False)

    body = (bin_dir / "docker-credential-cloudsmith").read_text(encoding="utf-8")
    assert f"exec '{exe}' credential-helper docker \"$@\"" in body


@pytest.mark.parametrize(
    "helper, summary",
    [
        ("cargo", "Cargo credential provider for Cloudsmith registries."),
        ("docker", "Docker credential helper for Cloudsmith registries."),
        ("generic", "Emit a Cloudsmith credential as JSON."),
        ("pnpm", "pnpm credential helper for Cloudsmith registries."),
        ("terraform", "Terraform credentials helper for Cloudsmith registries."),
    ],
)
def test_group_help_shows_helper_summary(runner, helper: str, summary: str) -> None:
    result = runner.invoke(credential_helper, ["--help"])

    assert result.exit_code == 0
    command_rows = [line.split(None, 1) for line in result.stdout.splitlines()]
    assert [helper, summary] in command_rows
