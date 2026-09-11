# Copyright 2026 Cloudsmith Ltd
"""Tests for cloudsmith_cli.core.installation.

Channel and build-target detection are pure functions of the runtime
environment (executable path, distribution metadata, platform). Every test
stubs those inputs so nothing depends on how the test host installed the CLI.
"""

from __future__ import annotations

import pytest

from cloudsmith_cli.core import installation


class TestDetectFrozenChannel:
    @pytest.mark.parametrize(
        "path, expected",
        [
            ("/home/u/.local/aquaproj-aqua/bin/cloudsmith", installation.CHANNEL_AQUA),
            (
                "/opt/homebrew/Cellar/cloudsmith-cli/1.0/bin/cloudsmith",
                installation.CHANNEL_HOMEBREW,
            ),
            (
                "/home/linuxbrew/.linuxbrew/bin/cloudsmith",
                installation.CHANNEL_HOMEBREW,
            ),
            ("/usr/local/bin/cloudsmith", installation.CHANNEL_STANDALONE),
        ],
    )
    def test_paths(self, monkeypatch, path, expected):
        monkeypatch.setattr(installation.os.path, "realpath", lambda p: p)
        assert (
            installation.detect_channel(frozen=True, executable_path=path) == expected
        )

    def test_docker(self, monkeypatch):
        monkeypatch.setattr(installation.os.path, "realpath", lambda p: p)
        monkeypatch.setattr(installation, "_running_in_container", lambda: True)
        assert (
            installation.detect_channel(
                frozen=True, executable_path="/opt/cloudsmith/bin/cloudsmith"
            )
            == installation.CHANNEL_DOCKER
        )

    def test_opt_cloudsmith_without_container_is_standalone(self, monkeypatch):
        monkeypatch.setattr(installation.os.path, "realpath", lambda p: p)
        monkeypatch.setattr(installation, "_running_in_container", lambda: False)
        assert (
            installation.detect_channel(
                frozen=True, executable_path="/opt/cloudsmith/bin/cloudsmith"
            )
            == installation.CHANNEL_STANDALONE
        )


class TestDetectPackageChannel:
    def _patch(self, monkeypatch, location, installer=None):
        monkeypatch.setattr(installation, "_distribution_location", lambda: location)
        monkeypatch.setattr(installation, "_distribution_installer", lambda: installer)

    def test_pipx(self, monkeypatch):
        self._patch(monkeypatch, "/home/u/.local/pipx/venvs/cloudsmith-cli")
        assert installation.detect_channel(frozen=False) == installation.CHANNEL_PIPX

    def test_uv_tool(self, monkeypatch):
        self._patch(monkeypatch, "/home/u/.local/share/uv/tools/cloudsmith-cli")
        assert installation.detect_channel(frozen=False) == installation.CHANNEL_UV_TOOL

    def test_uv_pip(self, monkeypatch):
        self._patch(monkeypatch, "/venv/lib/python3.12/site-packages", installer="uv")
        assert installation.detect_channel(frozen=False) == installation.CHANNEL_UV_PIP

    def test_pip(self, monkeypatch):
        self._patch(monkeypatch, "/venv/lib/python3.12/site-packages", installer="pip")
        assert installation.detect_channel(frozen=False) == installation.CHANNEL_PIP

    def test_unknown_installer(self, monkeypatch):
        self._patch(monkeypatch, "/some/site-packages", installer=None)
        assert installation.detect_channel(frozen=False) == installation.CHANNEL_UNKNOWN

    def test_no_distribution(self, monkeypatch):
        self._patch(monkeypatch, None)
        assert installation.detect_channel(frozen=False) == installation.CHANNEL_UNKNOWN


class TestDetectTarget:
    def _patch_platform(self, monkeypatch, system, machine, libc="glibc"):
        monkeypatch.setattr(installation.platform, "system", lambda: system)
        monkeypatch.setattr(installation.platform, "machine", lambda: machine)
        monkeypatch.setattr(installation.platform, "libc_ver", lambda: (libc, "2.35"))

    @pytest.mark.parametrize(
        "system, machine, libc, expected",
        [
            ("Darwin", "arm64", "glibc", "macos-arm64"),
            ("Darwin", "x86_64", "glibc", "macos-x86_64"),
            ("Windows", "AMD64", "glibc", "windows-x86_64"),
            ("Linux", "x86_64", "glibc", "linux-x86_64-gnu"),
            ("Linux", "x86_64", "musl", "linux-x86_64-musl"),
            ("Linux", "aarch64", "glibc", "linux-aarch64-gnu"),
        ],
    )
    def test_supported(self, monkeypatch, system, machine, libc, expected):
        self._patch_platform(monkeypatch, system, machine, libc)
        assert installation.detect_target() == expected

    @pytest.mark.parametrize(
        "system, machine",
        [("Darwin", "ppc"), ("Windows", "arm64"), ("Linux", "ppc64le"), ("Plan9", "x")],
    )
    def test_unsupported(self, monkeypatch, system, machine):
        self._patch_platform(monkeypatch, system, machine)
        assert installation.detect_target() is None


class TestUpgradeInstruction:
    def test_standalone_returns_none(self):
        assert installation.upgrade_instruction(installation.CHANNEL_STANDALONE) is None

    @pytest.mark.parametrize(
        "channel",
        [
            installation.CHANNEL_PIP,
            installation.CHANNEL_PIPX,
            installation.CHANNEL_UV_TOOL,
            installation.CHANNEL_UV_PIP,
            installation.CHANNEL_HOMEBREW,
            installation.CHANNEL_DOCKER,
            installation.CHANNEL_AQUA,
            installation.CHANNEL_UNKNOWN,
        ],
    )
    def test_channels_return_instruction(self, channel):
        instruction = installation.upgrade_instruction(channel)
        assert isinstance(instruction, str) and instruction


class TestSelfUpdateSupported:
    def test_posix_supported(self, monkeypatch):
        monkeypatch.setattr(installation.os, "name", "posix")
        assert installation.self_update_supported() is True

    def test_windows_not_supported(self, monkeypatch):
        monkeypatch.setattr(installation.os, "name", "nt")
        assert installation.self_update_supported() is False
