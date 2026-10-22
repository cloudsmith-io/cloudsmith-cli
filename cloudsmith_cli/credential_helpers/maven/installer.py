# Copyright 2026 Cloudsmith Ltd
"""Turn on the Cloudsmith Maven extension in the Maven project of the current directory.

Maven 3.9 has no user-wide extensions, and Maven loads a build extension only
from Maven Central or the local repository. So the installer puts the extension
in the local repository and lists it in the project's ``.mvn/extensions.xml``.
"""

from __future__ import annotations

from pathlib import Path

from .. import maven_tools
from . import extensions

EXTENSION_PATH = f"io/cloudsmith/{extensions.ARTIFACT_ID}"


class MavenProjectNotFound(Exception):
    """The current directory is not in a Maven project."""


def _project_dir() -> Path:
    """Return the directory where Maven reads ``.mvn``: the nearest one that has it."""
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        if (directory / ".mvn").is_dir():
            return directory
    return cwd


def _extensions_file() -> Path:
    return _project_dir() / ".mvn" / "extensions.xml"


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


class MavenInstaller:
    name = "maven"
    summary = "Maven extension that gets credentials from the Cloudsmith CLI"

    def install(self, *, dry_run: bool = False, **_options) -> list[str]:
        """Put the extension in ``~/.m2/repository`` and list it in ``.mvn/extensions.xml``."""
        project_dir = _project_dir()
        if not (project_dir / "pom.xml").is_file():
            raise MavenProjectNotFound(
                f"No pom.xml in {project_dir}. "
                "Run the command in the root directory of a Maven project."
            )
        version = maven_tools.latest_version(EXTENSION_PATH)
        return self._download(version, dry_run) + self._turn_on(version, dry_run)

    def _download(self, version: str, dry_run: bool) -> list[str]:
        version_dir = Path.home() / ".m2" / "repository" / EXTENSION_PATH / version
        actions = []
        for file_type in ("jar", "pom"):
            file_name = f"{extensions.ARTIFACT_ID}-{version}.{file_type}"
            destination = version_dir / file_name
            if destination.exists():
                actions.append(f"{file_name} already in {version_dir} (no change)")
            elif dry_run:
                actions.append(f"would download {file_name} to {version_dir}")
            else:
                maven_tools.download(
                    f"{EXTENSION_PATH}/{version}/{file_name}", destination
                )
                actions.append(f"downloaded {file_name} to {version_dir}")
        return actions

    def _turn_on(self, version: str, dry_run: bool) -> list[str]:
        path = _extensions_file()
        text, changed = extensions.add_extension(_read(path), version)
        if not changed:
            return [f"{path} already lists version {version} (no change)"]
        if dry_run:
            return [f"would add version {version} to {path}"]
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return [f"added version {version} to {path}"]

    def uninstall(self, *, dry_run: bool = False, **_options) -> list[str]:
        """Remove the extension from ``.mvn/extensions.xml``.

        The local repository is shared with other projects, so it stays as it is.
        """
        path = _extensions_file()
        current = _read(path)
        if current is None:
            return [f"{path} not found (nothing to remove)"]
        text, changed = extensions.remove_extension(current)
        if not changed:
            return [f"{path} does not list the extension (nothing to remove)"]
        if dry_run:
            return [f"would remove the extension from {path}"]
        if text is None:
            path.unlink()
            return [f"removed {path}"]
        path.write_text(text, encoding="utf-8")
        return [f"removed the extension from {path}"]

    def status(self) -> dict:
        path = _extensions_file()
        current = _read(path)
        configured = current is not None and extensions.has_extension(current)
        return {"launcher": str(path) if configured else None, "hosts": []}
