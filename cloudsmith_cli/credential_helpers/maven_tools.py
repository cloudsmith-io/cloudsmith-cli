# Copyright 2026 Cloudsmith Ltd
"""
Shared code for the installers of the Cloudsmith Maven tools.

The Maven extension and the Gradle and sbt plugins get their credential from
`cloudsmith credential-helper generic`. They are published to a public
Cloudsmith repository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from xml.etree import ElementTree

from ..core.session import create_requests_session

if TYPE_CHECKING:
    from pathlib import Path

    import requests

REPOSITORY_URL = "https://dl.cloudsmith.io/public/cloudsmith/maven-tools/maven/"
TIMEOUT_SECONDS = 30


class ProjectNotFound(Exception):
    """The current directory is not the root directory of a project."""


class InstallOptionError(Exception):
    """The helper cannot install with the given options."""


def _get(artifact_path: str, session: requests.Session | None) -> bytes:
    response = (session or create_requests_session()).get(
        REPOSITORY_URL + artifact_path, timeout=TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.content


def latest_version(artifact_path: str, session: requests.Session | None = None) -> str:
    """Return the newest release of the artifact at *artifact_path*."""
    metadata = ElementTree.fromstring(
        _get(f"{artifact_path}/maven-metadata.xml", session)
    )
    release = metadata.findtext("versioning/release")
    if not release:
        raise OSError(f"{REPOSITORY_URL}{artifact_path} has no release")
    return release


def download(
    artifact_path: str, destination: Path, session: requests.Session | None = None
) -> None:
    """Download the file at *artifact_path* to *destination*."""
    content = _get(artifact_path, session)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


class ConfigFileInstaller:
    """Install a plugin with one config file that names its latest version."""

    name = ""
    summary = ""
    artifact_path = ""
    install_options = ("local",)
    # The install command passes a session with its proxy and TLS settings.
    downloads_files = True

    def path(self) -> Path:
        """Return the config file that loads the plugin for every build."""
        raise NotImplementedError

    def local_path(self) -> Path:
        """Return the config file that loads the plugin for the current project."""
        raise NotImplementedError

    def render(self, version: str) -> str:
        """Return the content of the config file for *version*."""
        raise NotImplementedError

    def install(
        self,
        *,
        dry_run: bool = False,
        local: bool = False,
        session: requests.Session | None = None,
        **_options,
    ) -> list[str]:
        path = self.local_path() if local else self.path()
        version = latest_version(self.artifact_path, session)
        text = self.render(version)
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return [f"{path} already uses version {version} (no change)"]
        if dry_run:
            return [f"would write {path} for version {version}"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return [f"wrote {path} for version {version}"]

    def uninstall(
        self, *, dry_run: bool = False, local: bool = False, **_options
    ) -> list[str]:
        path = self.local_path() if local else self.path()
        if not path.exists():
            return [f"{path} not found (nothing to remove)"]
        if dry_run:
            return [f"would remove {path}"]
        path.unlink()
        return [f"removed {path}"]

    def status(self) -> dict:
        path = self.path()
        return {"launcher": str(path) if path.exists() else None, "hosts": []}
