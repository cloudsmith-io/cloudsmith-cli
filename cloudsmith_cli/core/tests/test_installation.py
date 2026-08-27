"""Install channel detection - Tests."""

import unittest
from unittest import mock

from .. import installation


class TestDetectFrozenChannel(unittest.TestCase):
    def _detect(self, path, in_container=False):
        with mock.patch.object(
            installation, "_running_in_container", return_value=in_container
        ):
            return installation.detect_channel(frozen=True, executable_path=path)

    def test_aqua(self):
        path = "/home/user/.local/share/aquaproj-aqua/pkgs/x/cloudsmith"
        self.assertEqual(installation.CHANNEL_AQUA, self._detect(path))

    def test_homebrew_macos(self):
        path = "/opt/homebrew/Cellar/cloudsmith-cli/1.25.0/libexec/cloudsmith"
        self.assertEqual(installation.CHANNEL_HOMEBREW, self._detect(path))

    def test_homebrew_linux(self):
        path = (
            "/home/linuxbrew/.linuxbrew/Cellar/cloudsmith-cli/1.25.0/libexec/cloudsmith"
        )
        self.assertEqual(installation.CHANNEL_HOMEBREW, self._detect(path))

    def test_docker(self):
        path = "/opt/cloudsmith/cloudsmith"
        self.assertEqual(
            installation.CHANNEL_DOCKER, self._detect(path, in_container=True)
        )

    def test_standalone(self):
        path = "/usr/local/cloudsmith/cloudsmith"
        self.assertEqual(installation.CHANNEL_STANDALONE, self._detect(path))

    def test_standalone_windows_path(self):
        path = "C:\\Tools\\cloudsmith\\cloudsmith.exe"
        self.assertEqual(installation.CHANNEL_STANDALONE, self._detect(path))


class TestDetectPackageChannel(unittest.TestCase):
    def _detect(self, location, installer):
        with (
            mock.patch.object(
                installation, "_distribution_location", return_value=location
            ),
            mock.patch.object(
                installation, "_distribution_installer", return_value=installer
            ),
        ):
            return installation.detect_channel(frozen=False)

    def test_pipx(self):
        location = (
            "/home/user/.local/pipx/venvs/cloudsmith-cli/lib/python3.12/site-packages"
        )
        self.assertEqual(installation.CHANNEL_PIPX, self._detect(location, "pip"))

    def test_uv_tool(self):
        location = "/home/user/.local/share/uv/tools/cloudsmith-cli/lib/site-packages"
        self.assertEqual(installation.CHANNEL_UV_TOOL, self._detect(location, "uv"))

    def test_uv_pip(self):
        location = "/home/user/project/.venv/lib/site-packages"
        self.assertEqual(installation.CHANNEL_UV_PIP, self._detect(location, "uv"))

    def test_pip(self):
        location = "/usr/lib/python3.12/site-packages"
        self.assertEqual(installation.CHANNEL_PIP, self._detect(location, "pip"))

    def test_unknown_without_distribution(self):
        self.assertEqual(installation.CHANNEL_UNKNOWN, self._detect(None, None))


class TestDetectTarget(unittest.TestCase):
    def _detect(self, system, machine, libc="glibc"):
        with (
            mock.patch("platform.system", return_value=system),
            mock.patch("platform.machine", return_value=machine),
            mock.patch("platform.libc_ver", return_value=(libc, "")),
        ):
            return installation.detect_target()

    def test_macos_arm64(self):
        self.assertEqual("macos-arm64", self._detect("Darwin", "arm64"))

    def test_macos_x86_64(self):
        self.assertEqual("macos-x86_64", self._detect("Darwin", "x86_64"))

    def test_windows(self):
        self.assertEqual("windows-x86_64", self._detect("Windows", "AMD64"))

    def test_linux_gnu(self):
        self.assertEqual("linux-x86_64-gnu", self._detect("Linux", "x86_64"))

    def test_linux_musl(self):
        self.assertEqual(
            "linux-aarch64-musl", self._detect("Linux", "aarch64", libc="")
        )

    def test_linux_arm64_alias(self):
        self.assertEqual("linux-aarch64-gnu", self._detect("Linux", "arm64"))

    def test_unsupported(self):
        self.assertIsNone(self._detect("SunOS", "sparc"))


class TestUpgradeInstruction(unittest.TestCase):
    def test_each_managed_channel_has_an_instruction(self):
        managed = (
            installation.CHANNEL_PIP,
            installation.CHANNEL_PIPX,
            installation.CHANNEL_UV_TOOL,
            installation.CHANNEL_UV_PIP,
            installation.CHANNEL_HOMEBREW,
            installation.CHANNEL_DOCKER,
            installation.CHANNEL_AQUA,
            installation.CHANNEL_UNKNOWN,
        )
        for channel in managed:
            self.assertIsInstance(installation.upgrade_instruction(channel), str)

    def test_standalone_self_updates(self):
        self.assertIsNone(
            installation.upgrade_instruction(installation.CHANNEL_STANDALONE)
        )

    def test_pip_instruction(self):
        self.assertIn(
            "pip install --upgrade cloudsmith-cli",
            installation.upgrade_instruction(installation.CHANNEL_PIP),
        )
