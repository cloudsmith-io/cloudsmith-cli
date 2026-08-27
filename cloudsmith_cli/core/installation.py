"""Detect how the CLI was installed and how to upgrade it."""

import os
import platform
import sys
from importlib import metadata

CHANNEL_STANDALONE = "standalone"
CHANNEL_HOMEBREW = "homebrew"
CHANNEL_DOCKER = "docker"
CHANNEL_AQUA = "aqua"
CHANNEL_PIP = "pip"
CHANNEL_PIPX = "pipx"
CHANNEL_UV_TOOL = "uv-tool"
CHANNEL_UV_PIP = "uv-pip"
CHANNEL_UNKNOWN = "unknown"

_DISTRIBUTION_NAME = "cloudsmith-cli"

_UPGRADE_INSTRUCTIONS = {
    CHANNEL_PIP: "pip install --upgrade cloudsmith-cli",
    CHANNEL_PIPX: "pipx upgrade cloudsmith-cli",
    CHANNEL_UV_TOOL: "uv tool upgrade cloudsmith-cli",
    CHANNEL_UV_PIP: "uv pip install --upgrade cloudsmith-cli",
    CHANNEL_HOMEBREW: "brew update && brew upgrade cloudsmith-cli",
    CHANNEL_DOCKER: "docker pull cloudsmith/cloudsmith-cli:latest",
    CHANNEL_AQUA: (
        "update the cloudsmith-io/cloudsmith-cli version in your aqua "
        "configuration, then run `aqua install`"
    ),
    CHANNEL_UNKNOWN: "pip install --upgrade cloudsmith-cli",
}


def _running_in_container():
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return True
    return bool(
        os.environ.get("container") or os.environ.get("KUBERNETES_SERVICE_HOST")
    )


def _distribution_location():
    """Return the installed distribution's directory, or None."""
    try:
        distribution = metadata.distribution(_DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return None
    return str(distribution.locate_file(""))


def _distribution_installer():
    """Return the INSTALLER record of the installed distribution, or None."""
    try:
        distribution = metadata.distribution(_DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return None
    installer = distribution.read_text("INSTALLER")
    return installer.strip() if installer else None


def _detect_frozen_channel(executable_path):
    normalized = os.path.realpath(executable_path).replace("\\", "/")
    if "aquaproj-aqua" in normalized:
        return CHANNEL_AQUA
    if "/Cellar/" in normalized or "/linuxbrew/" in normalized:
        return CHANNEL_HOMEBREW
    if normalized.startswith("/opt/cloudsmith") and _running_in_container():
        return CHANNEL_DOCKER
    return CHANNEL_STANDALONE


def _detect_package_channel():
    location = _distribution_location()
    if location is None:
        return CHANNEL_UNKNOWN
    normalized = location.replace("\\", "/")
    if "/pipx/" in normalized:
        return CHANNEL_PIPX
    if "/uv/tools/" in normalized:
        return CHANNEL_UV_TOOL
    installer = _distribution_installer()
    if installer == "uv":
        return CHANNEL_UV_PIP
    if installer == "pip":
        return CHANNEL_PIP
    return CHANNEL_UNKNOWN


def detect_channel(frozen=None, executable_path=None):
    """Detect the install channel of the running CLI."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if frozen:
        return _detect_frozen_channel(executable_path or sys.executable)
    return _detect_package_channel()


def detect_target():
    """Detect the standalone build target for this platform, or None."""
    system = platform.system()
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64"}.get(machine)
    arm = machine in ("arm64", "aarch64")
    if system == "Darwin":
        return "macos-arm64" if arm else ("macos-x86_64" if arch else None)
    if system == "Windows":
        return "windows-x86_64" if arch else None
    if system == "Linux":
        if arm:
            arch = "aarch64"
        if arch is None:
            return None
        libc = "gnu" if platform.libc_ver()[0] == "glibc" else "musl"
        return f"linux-{arch}-{libc}"
    return None


def upgrade_instruction(channel):
    """Return the upgrade command for a channel, or None for self-update."""
    if channel == CHANNEL_STANDALONE:
        return None
    return _UPGRADE_INSTRUCTIONS[channel]
