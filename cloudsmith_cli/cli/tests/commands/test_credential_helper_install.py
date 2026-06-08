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
# write_launcher / remove_launcher — Unix
# ---------------------------------------------------------------------------


class TestWriteLauncherUnix:
    """Tests for write_launcher on Unix (os.name == 'posix')."""

    def test_content_is_correct(self, tmp_path):
        """Launcher content is exactly the exec-forwarding shell script."""
        dest = write_launcher(
            tmp_path,
            "docker-credential-cloudsmith",
            "cloudsmith credential-helper docker",
        )
        expected = '#!/bin/sh\nexec cloudsmith credential-helper docker "$@"\n'
        assert dest.read_text(encoding="utf-8") == expected

    def test_mode_is_755(self, tmp_path):
        """Launcher is created with mode 0o755."""
        dest = write_launcher(
            tmp_path,
            "docker-credential-cloudsmith",
            "cloudsmith credential-helper docker",
        )
        mode = dest.stat().st_mode
        assert stat.S_IMODE(mode) == 0o755

    def test_returns_path_without_extension(self, tmp_path):
        """Returned path has no extension on Unix."""
        dest = write_launcher(
            tmp_path, "my-helper", "cloudsmith credential-helper docker"
        )
        assert dest.name == "my-helper"

    def test_creates_bin_dir_if_absent(self, tmp_path):
        """write_launcher creates bin_dir if it does not yet exist."""
        new_dir = tmp_path / "newdir" / "bin"
        assert not new_dir.exists()
        write_launcher(new_dir, "my-helper", "cloudsmith credential-helper docker")
        assert new_dir.is_dir()


class TestRemoveLauncherUnix:
    """Tests for remove_launcher on Unix."""

    def test_returns_true_when_file_existed(self, tmp_path):
        """remove_launcher returns True when a file was present and deleted."""
        write_launcher(
            tmp_path,
            "docker-credential-cloudsmith",
            "cloudsmith credential-helper docker",
        )
        result = remove_launcher(tmp_path, "docker-credential-cloudsmith")
        assert result is True

    def test_returns_false_when_file_absent(self, tmp_path):
        """remove_launcher returns False when no launcher file exists."""
        result = remove_launcher(tmp_path, "docker-credential-cloudsmith")
        assert result is False

    def test_file_is_gone_after_remove(self, tmp_path):
        """After remove_launcher the file no longer exists on disk."""
        write_launcher(
            tmp_path,
            "docker-credential-cloudsmith",
            "cloudsmith credential-helper docker",
        )
        remove_launcher(tmp_path, "docker-credential-cloudsmith")
        assert not (tmp_path / "docker-credential-cloudsmith").exists()


# ---------------------------------------------------------------------------
# write_launcher — Windows simulation
# ---------------------------------------------------------------------------


class TestWriteLauncherWindows:
    """Tests for write_launcher when os.name == 'nt'.

    On non-Windows systems we cannot instantiate a WindowsPath, so we test
    the string content by inspecting the file via the returned path string and
    verifying the name suffix—the actual file is created with a str join rather
    than a WindowsPath object on macOS/Linux CI.
    """

    def test_creates_cmd_file(self, tmp_path, monkeypatch):
        """On Windows, write_launcher creates a .cmd file."""
        import cloudsmith_cli.credential_helpers.launchers as _launchers_mod

        monkeypatch.setattr(_launchers_mod.os, "name", "nt")
        dest = write_launcher(
            tmp_path,
            "docker-credential-cloudsmith",
            "cloudsmith credential-helper docker",
        )
        assert str(dest).endswith(".cmd")

    def test_cmd_content(self, tmp_path, monkeypatch):
        """On Windows, .cmd content is byte-exact for correct Docker credential parsing."""
        import cloudsmith_cli.credential_helpers.launchers as _launchers_mod

        monkeypatch.setattr(_launchers_mod.os, "name", "nt")
        dest = write_launcher(
            tmp_path,
            "docker-credential-cloudsmith",
            "cloudsmith credential-helper docker",
        )
        # Read raw bytes to avoid universal-newline translation on macOS/Linux
        raw = Path(str(dest)).read_bytes()
        assert raw == b"@echo off\r\ncloudsmith credential-helper docker %*\r\n"


# ---------------------------------------------------------------------------
# resolve_bin_dir
# ---------------------------------------------------------------------------


class TestResolveBinDir:
    """Tests for resolve_bin_dir resolution logic."""

    def test_override_is_respected(self, tmp_path):
        """An explicit override path is returned as-is."""
        result = resolve_bin_dir(str(tmp_path))
        assert result == tmp_path

    def test_falls_back_to_user_bin_when_no_writable_cloudsmith(
        self, tmp_path, monkeypatch
    ):
        """Falls back to ~/.local/bin when cloudsmith is not found and bin is not writable."""
        import cloudsmith_cli.credential_helpers.launchers as _launchers_mod

        # Patch shutil.which inside the launchers module
        monkeypatch.setattr(_launchers_mod.shutil, "which", lambda _name: None)
        # Patch Path.home() to point at tmp_path
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        monkeypatch.setattr(_launchers_mod.os, "name", "posix")
        # Make os.access always return False so no fallback dir looks writable
        monkeypatch.setattr(_launchers_mod.os, "access", lambda _path, _mode: False)

        result = resolve_bin_dir()
        assert result == tmp_path / ".local" / "bin"

    def test_falls_back_to_windows_user_bin(self, tmp_path, monkeypatch):
        """On Windows, falls back to %LOCALAPPDATA%/Cloudsmith/bin."""
        import cloudsmith_cli.credential_helpers.launchers as _launchers_mod

        monkeypatch.setattr(_launchers_mod.shutil, "which", lambda _name: None)
        monkeypatch.setattr(_launchers_mod.os, "name", "nt")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        # Make no directory look writable
        monkeypatch.setattr(_launchers_mod.os, "access", lambda _path, _mode: False)

        result = resolve_bin_dir()
        # Compare normalised paths to handle cross-platform separator differences
        # when testing Windows branch on macOS/Linux
        result_str = str(result).replace("\\", "/")
        expected_str = str(tmp_path / "Cloudsmith" / "bin").replace("\\", "/")
        assert result_str == expected_str


# ---------------------------------------------------------------------------
# is_on_path
# ---------------------------------------------------------------------------


class TestIsOnPath:
    """Tests for is_on_path."""

    def test_directory_on_path(self, tmp_path, monkeypatch):
        """A directory that appears in PATH is detected correctly."""
        monkeypatch.setenv("PATH", str(tmp_path))
        assert is_on_path(tmp_path) is True

    def test_directory_not_on_path(self, tmp_path, monkeypatch):
        """A directory absent from PATH returns False."""
        monkeypatch.setenv("PATH", "/usr/bin:/usr/local/bin")
        assert is_on_path(tmp_path) is False

    def test_normalisation_handles_trailing_slash(self, tmp_path, monkeypatch):
        """Trailing slashes in PATH entries are normalised correctly."""
        monkeypatch.setenv("PATH", str(tmp_path) + os.sep)
        assert is_on_path(tmp_path) is True


# ---------------------------------------------------------------------------
# DockerInstaller.install
# ---------------------------------------------------------------------------


class TestDockerInstallerInstall:
    """Tests for DockerInstaller.install."""

    def _make_docker_config(self, docker_dir: Path, data: dict) -> Path:
        """Write a config.json to *docker_dir* and return its path."""
        docker_dir.mkdir(parents=True, exist_ok=True)
        cfg = docker_dir / "config.json"
        cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return cfg

    def test_sets_default_host(self, tmp_path, monkeypatch):
        """install sets credHelpers[docker.cloudsmith.io]=cloudsmith."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"
        monkeypatch.setenv("PATH", str(bin_dir))

        installer = DockerInstaller()
        installer.install(bin_dir=str(bin_dir))

        cfg = json.loads((docker_dir / "config.json").read_text())
        assert cfg["credHelpers"]["docker.cloudsmith.io"] == "cloudsmith"

    def test_sets_additional_domain(self, tmp_path, monkeypatch):
        """install also sets credHelpers for --domain entries."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        installer = DockerInstaller()
        installer.install(bin_dir=str(bin_dir), domains=("my.registry.example.com",))

        cfg = json.loads((docker_dir / "config.json").read_text())
        assert cfg["credHelpers"]["my.registry.example.com"] == "cloudsmith"

    def test_preserves_foreign_keys(self, tmp_path, monkeypatch):
        """Foreign keys in auths and credHelpers are not touched."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        # Seed a config with existing foreign data
        self._make_docker_config(
            docker_dir,
            {
                "auths": {"ghcr.io": {"auth": "dG9rZW4="}},
                "credHelpers": {"ghcr.io": "gh"},
            },
        )

        installer = DockerInstaller()
        installer.install(bin_dir=str(bin_dir))

        cfg = json.loads((docker_dir / "config.json").read_text())
        assert cfg["auths"] == {"ghcr.io": {"auth": "dG9rZW4="}}
        assert cfg["credHelpers"]["ghcr.io"] == "gh"

    def test_writes_launcher(self, tmp_path, monkeypatch):
        """install writes a launcher script to bin_dir."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        installer = DockerInstaller()
        installer.install(bin_dir=str(bin_dir))

        launcher = bin_dir / "docker-credential-cloudsmith"
        assert launcher.exists()

    def test_creates_bak_file(self, tmp_path, monkeypatch):
        """install creates a .bak backup when config.json already exists."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        # Seed existing config
        self._make_docker_config(docker_dir, {"auths": {}})

        installer = DockerInstaller()
        installer.install(bin_dir=str(bin_dir))

        bak = docker_dir / "config.json.bak"
        assert bak.exists()


# ---------------------------------------------------------------------------
# DockerInstaller.install — dry_run
# ---------------------------------------------------------------------------


class TestDockerInstallerDryRun:
    """Tests for DockerInstaller.install with dry_run=True."""

    def test_no_launcher_written(self, tmp_path, monkeypatch):
        """dry_run=True does NOT write a launcher file."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        installer = DockerInstaller()
        installer.install(bin_dir=str(bin_dir), dry_run=True)

        assert not (bin_dir / "docker-credential-cloudsmith").exists()

    def test_config_json_not_modified(self, tmp_path, monkeypatch):
        """dry_run=True does NOT modify config.json."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        installer = DockerInstaller()
        installer.install(bin_dir=str(bin_dir), dry_run=True)

        assert not (docker_dir / "config.json").exists()

    def test_returns_planned_action_strings(self, tmp_path, monkeypatch):
        """dry_run=True returns strings describing what would be done."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        installer = DockerInstaller()
        actions = installer.install(bin_dir=str(bin_dir), dry_run=True)

        assert any("would write launcher" in a for a in actions)
        assert any("docker.cloudsmith.io" in a for a in actions)


# ---------------------------------------------------------------------------
# DockerInstaller.install — idempotency
# ---------------------------------------------------------------------------


class TestDockerInstallerIdempotent:
    """Tests for idempotent second-run behaviour."""

    def test_second_install_no_change(self, tmp_path, monkeypatch):
        """Running install twice does not change config.json the second time."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        installer = DockerInstaller()
        installer.install(bin_dir=str(bin_dir))

        mtime_before = (docker_dir / "config.json").stat().st_mtime

        # Second run — config should be considered up-to-date
        actions = installer.install(bin_dir=str(bin_dir))

        mtime_after = (docker_dir / "config.json").stat().st_mtime
        assert mtime_before == mtime_after
        assert any("already up to date" in a for a in actions)


# ---------------------------------------------------------------------------
# DockerInstaller.uninstall
# ---------------------------------------------------------------------------


class TestDockerInstallerUninstall:
    """Tests for DockerInstaller.uninstall."""

    def test_removes_cloudsmith_entries_only(self, tmp_path, monkeypatch):
        """uninstall removes cloudsmith entries but leaves foreign helpers."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        # Seed a mixed config
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

        with patch(
            "cloudsmith_cli.credential_helpers.docker.installer.resolve_bin_dir",
            return_value=bin_dir,
        ):
            installer = DockerInstaller()
            installer.uninstall()

        cfg = json.loads(cfg_path.read_text())
        # cloudsmith entry removed
        assert "docker.cloudsmith.io" not in cfg.get("credHelpers", {})
        # foreign entry kept
        assert cfg["credHelpers"]["ghcr.io"] == "gh"

    def test_removes_launcher(self, tmp_path, monkeypatch):
        """uninstall removes the launcher binary if it exists."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        # Write launcher manually
        bin_dir.mkdir(parents=True)
        launcher = bin_dir / "docker-credential-cloudsmith"
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")

        with patch(
            "cloudsmith_cli.credential_helpers.docker.installer.resolve_bin_dir",
            return_value=bin_dir,
        ):
            installer = DockerInstaller()
            installer.uninstall()

        assert not launcher.exists()

    def test_uninstall_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        """uninstall with dry_run=True makes no filesystem changes."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(parents=True)
        launcher = bin_dir / "docker-credential-cloudsmith"
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")

        docker_dir.mkdir(parents=True)
        cfg_path = docker_dir / "config.json"
        data = {"credHelpers": {"docker.cloudsmith.io": "cloudsmith"}}
        cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        with patch(
            "cloudsmith_cli.credential_helpers.docker.installer.resolve_bin_dir",
            return_value=bin_dir,
        ):
            installer = DockerInstaller()
            actions = installer.uninstall(dry_run=True)

        # Launcher still present, config unchanged
        assert launcher.exists()
        assert json.loads(cfg_path.read_text()) == data
        assert any("would remove" in a for a in actions)


# ---------------------------------------------------------------------------
# manage CLI (CliRunner)
# ---------------------------------------------------------------------------


class TestManageCLI:
    """Tests for the install/uninstall/list Click commands via CliRunner."""

    def test_install_docker_dry_run_exits_0(self, runner, tmp_path, monkeypatch):
        """install docker --dry-run exits 0 and prints a plan."""
        monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))

        from ....cli.commands.credential_helper.manage import install_cmd

        result = runner.invoke(
            install_cmd,
            ["docker", "--dry-run", "--bin-dir", str(tmp_path / "bin")],
        )

        assert result.exit_code == 0, result.output
        assert "would" in result.output.lower() or "dry run" in result.output.lower()

    def test_install_unknown_helper_exits_nonzero(self, runner):
        """install with an unknown helper name exits non-zero with an error."""
        from ....cli.commands.credential_helper.manage import install_cmd

        result = runner.invoke(install_cmd, ["badhelper"])

        assert result.exit_code != 0

    def test_uninstall_unknown_helper_exits_nonzero(self, runner):
        """uninstall with an unknown helper name exits non-zero."""
        from ....cli.commands.credential_helper.manage import uninstall_cmd

        result = runner.invoke(uninstall_cmd, ["badhelper"])

        assert result.exit_code != 0

    def test_list_exits_0(self, runner, tmp_path, monkeypatch):
        """list exits 0 and shows the docker helper entry."""
        monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))

        from ....cli.commands.credential_helper.manage import list_cmd

        result = runner.invoke(list_cmd, [])

        assert result.exit_code == 0, result.output
        assert "docker" in result.output


# ---------------------------------------------------------------------------
# PATH warning
# ---------------------------------------------------------------------------


class TestPathWarning:
    """Tests that a WARNING action is emitted when bin_dir is not on PATH."""

    def test_warning_fires_when_bin_dir_not_on_path(self, tmp_path, monkeypatch):
        """install returns a WARNING action when target dir is not on PATH."""
        docker_dir = tmp_path / ".docker"
        monkeypatch.setenv("DOCKER_CONFIG", str(docker_dir))
        bin_dir = tmp_path / "bin"

        # Keep PATH pointing somewhere else so bin_dir is definitely absent
        monkeypatch.setenv("PATH", "/usr/bin:/usr/local/bin")

        installer = DockerInstaller()
        actions = installer.install(bin_dir=str(bin_dir))

        warning_actions = [a for a in actions if a.startswith("WARNING")]
        assert warning_actions, f"Expected a WARNING action, got: {actions}"
        assert any("PATH" in a for a in warning_actions)


# ---------------------------------------------------------------------------
# Unwritable directory → clean ClickException (no raw traceback)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="permission test only meaningful on POSIX as non-root",
)
class TestUnwritableDirCleanError:
    """Tests that an unwritable bin_dir surfaces as a ClickException, not a raw OSError."""

    def test_unwritable_bin_dir_gives_click_exception(
        self, runner, tmp_path, monkeypatch
    ):
        """install with an unwritable --bin-dir exits non-zero without a bare OSError."""
        monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))

        from ....cli.commands.credential_helper.manage import install_cmd

        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        ro_dir.chmod(0o500)

        try:
            result = runner.invoke(
                install_cmd,
                ["docker", "--bin-dir", str(ro_dir)],
            )
        finally:
            # Restore permissions so pytest can clean up tmp_path
            ro_dir.chmod(0o700)

        assert result.exit_code != 0
        # The exception path should be a SystemExit (via ClickException), not a
        # bare OSError escaping the command.
        assert not isinstance(
            result.exception, OSError
        ), f"Raw OSError escaped: {result.exception}"
