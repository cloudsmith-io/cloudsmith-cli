# Copyright 2026 Cloudsmith Ltd
"""Turn on the Cloudsmith Maven extension for every Maven build, or for one project.

Maven loads a build extension only from Maven Central or the local repository,
so the installer puts the extension in the local repository first. Then it lists
the extension in one of these files:

- ``~/.m2/extensions.xml`` (the default), which Maven 3.10 and later read.
- ``.mvn/extensions.xml`` of the current project (``local``), which Maven 3.8
  and later read.
- ``~/.mavenrc`` (``mavenrc``), which the ``mvn`` and ``mvnw`` scripts read.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from .. import maven_tools
from ..maven_tools import ProjectNotFound
from . import extensions
from .mavenrc import add_block, has_block, remove_block

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

EXTENSION_PATH = f"io/cloudsmith/{extensions.ARTIFACT_ID}"
FIRST_MAVEN_WITH_USER_EXTENSIONS = (3, 10)
MAVEN_VERSION_TIMEOUT_SECONDS = 60


def _project_dir() -> Path:
    """Return the directory where Maven reads ``.mvn``: the nearest one that has it."""
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        if (directory / ".mvn").is_dir():
            return directory
    return cwd


def _project_extensions_file() -> Path:
    project_dir = _project_dir()
    if not (project_dir / "pom.xml").is_file():
        raise ProjectNotFound(
            f"No pom.xml in {project_dir}. "
            "Run the command in the root directory of a Maven project."
        )
    return project_dir / ".mvn" / "extensions.xml"


def _user_extensions_file() -> Path:
    return Path.home() / ".m2" / "extensions.xml"


def _mavenrc_file() -> Path:
    return Path.home() / ".mavenrc"


def _version_dir(version: str) -> Path:
    return Path.home() / ".m2" / "repository" / EXTENSION_PATH / version


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _maven_version() -> str | None:
    """Return the version that ``mvn -v`` reports, or ``None`` when there is none."""
    mvn = shutil.which("mvn")
    if not mvn:
        return None
    try:
        result = subprocess.run(
            [mvn, "-v"],
            capture_output=True,
            text=True,
            timeout=MAVEN_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"Apache Maven (\d+(?:\.\d+)+)", result.stdout)
    return match.group(1) if match else None


def _old_maven_warning() -> list[str]:
    version = _maven_version()
    if version is None:
        return []
    major_minor = tuple(int(part) for part in version.split(".")[:2])
    if major_minor >= FIRST_MAVEN_WITH_USER_EXTENSIONS:
        return []
    warning = (
        f"WARNING: Maven {version} ignores {_user_extensions_file()}. "
        "Maven 3.10 and later read it. For this Maven, run "
        "`cloudsmith credential-helper install maven --local` in each project, "
        "or run `cloudsmith credential-helper install maven --mavenrc` once."
    )
    return [warning]


def _mark_installed(version_dir: Path, file_names: list[str]) -> None:
    """Record the files as installed, not downloaded, in ``_remote.repositories``.

    Maven does not load a build extension that this file records as downloaded
    from a repository other than Maven Central. A missing file means installed.
    """
    tracking_file = version_dir / "_remote.repositories"
    current = _read(tracking_file)
    if current is None:
        return
    lines = []
    for line in current.splitlines():
        name = line.split(">", 1)[0]
        lines.append(f"{name}>=" if name in file_names else line)
    lines += [f"{name}>=" for name in file_names if f"{name}>=" not in lines]
    tracking_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _add(path: Path, edit: Callable, version: str, dry_run: bool) -> list[str]:
    text, changed = edit(_read(path))
    if not changed:
        return [f"{path} already loads version {version} (no change)"]
    if dry_run:
        return [f"would add version {version} to {path}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return [f"added version {version} to {path}"]


def _remove(path: Path, edit: Callable, dry_run: bool) -> list[str]:
    current = _read(path)
    if current is None:
        return [f"{path} not found (nothing to remove)"]
    text, changed = edit(current)
    if not changed:
        return [f"{path} does not load the extension (nothing to remove)"]
    if dry_run:
        return [f"would remove the extension from {path}"]
    if text is None:
        path.unlink()
        return [f"removed {path}"]
    path.write_text(text, encoding="utf-8")
    return [f"removed the extension from {path}"]


class MavenInstaller:
    name = "maven"
    summary = "Maven extension that gets credentials from the Cloudsmith CLI"
    # The install command passes a session with its proxy and TLS settings.
    downloads_files = True

    def install(
        self,
        *,
        dry_run: bool = False,
        local: bool = False,
        mavenrc: bool = False,
        session: requests.Session | None = None,
        **_options,
    ) -> list[str]:
        """Put the extension in ``~/.m2/repository`` and turn it on."""
        project_file = _project_extensions_file() if local else None
        version = maven_tools.latest_version(EXTENSION_PATH, session)
        actions = self._download(version, dry_run, session)
        if mavenrc:
            jar = _version_dir(version) / f"{extensions.ARTIFACT_ID}-{version}.jar"
            return actions + _add(
                _mavenrc_file(), partial(add_block, jar=jar), version, dry_run
            )
        add_extension = partial(extensions.add_extension, version=version)
        if project_file:
            return actions + _add(project_file, add_extension, version, dry_run)
        return (
            actions
            + _add(_user_extensions_file(), add_extension, version, dry_run)
            + _old_maven_warning()
        )

    def _download(
        self, version: str, dry_run: bool, session: requests.Session | None
    ) -> list[str]:
        version_dir = _version_dir(version)
        file_names = [
            f"{extensions.ARTIFACT_ID}-{version}.{file_type}"
            for file_type in ("jar", "pom")
        ]
        actions = []
        for file_name in file_names:
            destination = version_dir / file_name
            if destination.exists():
                actions.append(f"{file_name} already in {version_dir} (no change)")
            elif dry_run:
                actions.append(f"would download {file_name} to {version_dir}")
            else:
                maven_tools.download(
                    f"{EXTENSION_PATH}/{version}/{file_name}", destination, session
                )
                actions.append(f"downloaded {file_name} to {version_dir}")
        if not dry_run:
            _mark_installed(version_dir, file_names)
        return actions

    def uninstall(
        self, *, dry_run: bool = False, local: bool = False, **_options
    ) -> list[str]:
        """Remove the extension from the files that install changes.

        The local repository is shared with other projects, so it stays as it is.
        """
        if local:
            return _remove(
                _project_extensions_file(), extensions.remove_extension, dry_run
            )
        return _remove(
            _user_extensions_file(), extensions.remove_extension, dry_run
        ) + _remove(_mavenrc_file(), remove_block, dry_run)

    def status(self) -> dict:
        candidates = (
            (_user_extensions_file(), extensions.has_extension),
            (_mavenrc_file(), has_block),
            (_project_dir() / ".mvn" / "extensions.xml", extensions.has_extension),
        )
        for path, loads_extension in candidates:
            current = _read(path)
            if current is not None and loads_extension(current):
                return {"launcher": str(path), "hosts": []}
        return {"launcher": None, "hosts": []}
