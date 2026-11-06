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

import contextlib
import os
import re
import shutil
import subprocess
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree

from ...core.cache_utils import _FIX_CONFIG_FILE_HINT, ConfigFileParseError
from .. import maven_tools
from ..launchers import is_windows
from ..maven_tools import ProjectNotFound
from . import extensions
from .mavenrc import add_block, has_block, remove_block

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

EXTENSION_PATH = f"io/cloudsmith/{extensions.ARTIFACT_ID}"
FIRST_MAVEN_WITH_USER_EXTENSIONS = (3, 10)
FIRST_MAVEN_WITH_ONE_ARGUMENT_PER_LINE = (3, 9)
MAVEN_VERSION_TIMEOUT_SECONDS = 60
_REPO_LOCAL_PROPERTY = "maven.repo.local"
_MAVEN_DEFINE_OPTIONS = ("-D", "--define")
_POSIX_JVM_ARGUMENT = re.compile(r"[^ \t\r\n]+")
_WINDOWS_JVM_ARGUMENT = re.compile(r'(?:[^ \t\r\n"]|"[^"]*"?)+')
_JAVA_SPLIT_ARGUMENT = re.compile(r"\S+", re.ASCII)
_PLACEHOLDER = re.compile(r"\$\{([^}]*)\}")
_WRAPPER_MAVEN_VERSION = re.compile(
    r"^distributionUrl\s*[=:].*/apache-maven/([\w.-]+)/", re.MULTILINE
)
INSTEAD_OF_MAVENRC = (
    "Run `cloudsmith credential-helper install maven --local` in each project "
    "(Maven 3.8 and later), or upgrade to Maven 3.10 or later and run "
    "`cloudsmith credential-helper install maven`."
)


class MavenrcNotSupported(Exception):
    """Raised when the ``mvn`` script cannot load the extension from ``~/.mavenrc``."""


def _project_dir() -> Path:
    """Return the directory where Maven reads ``.mvn``: the nearest one that has it."""
    cwd = maven_tools.current_dir()
    for directory in (cwd, *cwd.parents):
        if (directory / ".mvn").is_dir():
            return directory
    return cwd


def _project_extensions_file() -> Path:
    project_dir = _project_dir()
    # Maven finds the project root by its .mvn directory, whatever the POM is called.
    if not (project_dir / "pom.xml").is_file() and not (project_dir / ".mvn").is_dir():
        raise ProjectNotFound(
            f"No pom.xml in {project_dir}. "
            "Run the command in the root directory of a Maven project."
        )
    return project_dir / ".mvn" / "extensions.xml"


def _user_extensions_file() -> Path:
    return Path.home() / ".m2" / "extensions.xml"


def _mavenrc_file() -> Path:
    return Path.home() / ".mavenrc"


def _jvm_arguments(options: str) -> list[str]:
    """Split JVM options at spaces, tabs and new lines; ``mvn.cmd`` keeps quoted text together."""
    if is_windows():
        return [
            argument.replace('"', "")
            for argument in _WINDOWS_JVM_ARGUMENT.findall(options)
        ]
    return _POSIX_JVM_ARGUMENT.findall(options)


def _maven_definitions(arguments: list[str]) -> list[str]:
    """Return the ``name=value`` of each ``-D`` or ``--define`` option in Maven arguments."""
    definitions = []
    for previous, argument in zip(["", *arguments], arguments):
        if previous in _MAVEN_DEFINE_OPTIONS:
            definitions.append(argument)
        elif argument.startswith("--define="):
            definitions.append(argument.removeprefix("--define="))
        elif argument.startswith("-D") and argument != "-D":
            definitions.append(argument.removeprefix("-D"))
    return definitions


def _properties(definitions: list[str]) -> dict[str, str]:
    """Return the properties of ``name=value`` definitions; Maven trims each name."""
    properties = {}
    for definition in definitions:
        name, separator, value = definition.partition("=")
        if separator:
            properties[name.strip()] = value
    return properties


def _wrapper_maven_version(mvn_dir: Path) -> str | None:
    """Return the Maven version that ``mvnw`` downloads, or ``None`` without a wrapper."""
    properties = _read(mvn_dir / "wrapper" / "maven-wrapper.properties")
    match = _WRAPPER_MAVEN_VERSION.search(properties) if properties else None
    return match.group(1) if match else None


def _maven_config_repo_local(
    mvn_dir: Path, jvm_properties: dict[str, str]
) -> str | None:
    """Return ``maven.repo.local`` of ``.mvn/maven.config`` with its placeholders resolved.

    Each line of ``.mvn/maven.config`` is one argument, and Maven skips the lines
    that start with ``#``. Maven before 3.9 splits the file on whitespace instead.
    The Maven of ``mvnw`` decides, else the ``mvn`` on ``PATH``.
    """
    maven_config_file = mvn_dir / "maven.config"
    maven_config = _read(maven_config_file)
    if not maven_config:
        return None
    arguments = maven_config.splitlines()
    version = _wrapper_maven_version(mvn_dir) or _maven_version()
    if version and _major_minor(version) < FIRST_MAVEN_WITH_ONE_ARGUMENT_PER_LINE:
        arguments = _JAVA_SPLIT_ARGUMENT.findall(maven_config)
    defined = _properties(_maven_definitions(arguments))
    if _REPO_LOCAL_PROPERTY not in defined:
        return None
    root = str(mvn_dir.parent)
    properties = {
        "user.home": str(Path.home()),
        "maven.multiModuleProjectDirectory": root,
        **jvm_properties,
        **defined,
        "session.rootDirectory": root,
        "session.topDirectory": str(maven_tools.current_dir()),
    }
    return _interpolate(
        defined[_REPO_LOCAL_PROPERTY],
        f"{_REPO_LOCAL_PROPERTY} of {maven_config_file}",
        properties,
    )


def _repo_local_option(local: bool) -> str | None:
    """Return the ``maven.repo.local`` value that Maven uses.

    ``.mvn/maven.config`` overrides the JVM options. ``mvn`` puts
    ``.mvn/jvm.config`` before ``MAVEN_OPTS``, and Java uses the last value.
    """
    jvm_options = os.environ.get("MAVEN_OPTS", "")
    mvn_dir = _project_dir() / ".mvn" if local else None
    if mvn_dir:
        jvm_options = f"{_read(mvn_dir / 'jvm.config') or ''} {jvm_options}"
    jvm_properties = _properties(
        [
            argument.removeprefix("-D")
            for argument in _jvm_arguments(jvm_options)
            if argument.startswith("-D")
        ]
    )
    if mvn_dir:
        maven_config_value = _maven_config_repo_local(mvn_dir, jvm_properties)
        if maven_config_value is not None:
            return maven_config_value
    return jvm_properties.get(_REPO_LOCAL_PROPERTY)


def _resolve_placeholder(
    match: re.Match[str], where: str, properties: dict[str, str]
) -> str:
    name = match.group(1)
    env_name = name.removeprefix("env.")
    if name in properties:
        return properties[name]
    if name.startswith("env.") and env_name in os.environ:
        return os.environ[env_name]
    raise ConfigFileParseError(
        f"Cannot resolve {match.group(0)} in {where}. {_FIX_CONFIG_FILE_HINT}"
    )


def _interpolate(
    value: str,
    where: str,
    properties: dict[str, str],
    resolving: frozenset[str] = frozenset(),
) -> str:
    """Replace each ``${name}`` in ``value``, and then the placeholders in its value, as Maven does."""

    def replace(match: re.Match[str]) -> str:
        if match.group(1) in resolving:
            raise ConfigFileParseError(
                f"{match.group(0)} refers to itself in {where}. {_FIX_CONFIG_FILE_HINT}"
            )
        return _interpolate(
            _resolve_placeholder(match, where, properties),
            where,
            properties,
            resolving | {match.group(1)},
        )

    return _PLACEHOLDER.sub(replace, value)


def _settings_local_repository() -> str | None:
    """Return ``<localRepository>`` of ``~/.m2/settings.xml``, or ``None`` when it has none."""
    settings_file = Path.home() / ".m2" / "settings.xml"
    if not settings_file.exists():
        return None
    try:
        root = ElementTree.parse(settings_file).getroot()
    except ElementTree.ParseError as exc:
        raise ConfigFileParseError(
            f"Cannot parse {settings_file} as XML: {exc}. {_FIX_CONFIG_FILE_HINT}"
        ) from exc
    # {*} matches the namespace of the Maven settings, or no namespace.
    value = root.findtext("{*}localRepository", "").strip()
    if not value:
        return None
    return _interpolate(
        value,
        f"<localRepository> of {settings_file}",
        {"user.home": str(Path.home())},
    )


def _local_repository(local: bool) -> Path:
    """Return the local repository that Maven uses, in the same order of precedence."""
    location = _repo_local_option(local) or _settings_local_repository()
    if location is None:
        return Path.home() / ".m2" / "repository"
    return Path(location).absolute()


def _version_dir(repository: Path, version: str) -> Path:
    return repository / EXTENSION_PATH / version


def _read(path: Path) -> str | None:
    # Keep bytes that are not UTF-8, for example comments in ~/.mavenrc.
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="surrogateescape")


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


def _major_minor(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".")[:2])


def _old_maven_warning() -> list[str]:
    version = _maven_version()
    if version is None:
        return []
    if _major_minor(version) >= FIRST_MAVEN_WITH_USER_EXTENSIONS:
        return []
    warning = (
        f"WARNING: Maven {version} ignores {_user_extensions_file()}. "
        "Maven 3.10 and later read it. For this Maven, run "
        "`cloudsmith credential-helper install maven --local` in each project"
    )
    if not is_windows():
        warning += (
            ", or run `cloudsmith credential-helper install maven --mavenrc` once"
        )
    return [f"{warning}."]


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
    maven_tools.write_atomically(path, text.encode("utf-8", "surrogateescape"))
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
    maven_tools.write_atomically(path, text.encode("utf-8", "surrogateescape"))
    return [f"removed the extension from {path}"]


def _turn_off(path: Path, edit: Callable, dry_run: bool) -> list[str]:
    """Remove the other user-level activation, because Maven 3.10 reads both files."""
    current = _read(path)
    if current is None or not edit(current)[1]:
        return []
    return _remove(path, edit, dry_run)


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
        """Put the extension in the local repository of Maven and turn it on."""
        project_file = _project_extensions_file() if local else None
        if mavenrc and is_windows():
            raise MavenrcNotSupported(
                f"mvn.cmd on Windows does not read ~/.mavenrc. {INSTEAD_OF_MAVENRC}"
            )
        repository = _local_repository(local)
        version = maven_tools.latest_version(EXTENSION_PATH, session)
        version_dir = _version_dir(repository, version)
        jar = version_dir / f"{extensions.ARTIFACT_ID}-{version}.jar"
        if mavenrc and any(char in " \t\n" for char in str(jar)):
            raise MavenrcNotSupported(
                "The mvn script splits MAVEN_OPTS at spaces, so it cannot load "
                f"{jar}. {INSTEAD_OF_MAVENRC}"
            )
        actions = self._download(version_dir, version, dry_run, session)
        if mavenrc:
            return (
                actions
                + _add(_mavenrc_file(), partial(add_block, jar=jar), version, dry_run)
                + _turn_off(
                    _user_extensions_file(), extensions.remove_extension, dry_run
                )
            )
        add_extension = partial(extensions.add_extension, version=version)
        if project_file:
            return actions + _add(project_file, add_extension, version, dry_run)
        return (
            actions
            + _add(_user_extensions_file(), add_extension, version, dry_run)
            + _turn_off(_mavenrc_file(), remove_block, dry_run)
            + _old_maven_warning()
        )

    def _download(
        self,
        version_dir: Path,
        version: str,
        dry_run: bool,
        session: requests.Session | None,
    ) -> list[str]:
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
        candidates = [
            (_user_extensions_file(), extensions.has_extension),
            (_mavenrc_file(), has_block),
        ]
        with contextlib.suppress(ProjectNotFound):
            candidates.append(
                (_project_dir() / ".mvn" / "extensions.xml", extensions.has_extension)
            )
        for path, loads_extension in candidates:
            try:
                current = _read(path)
            except (ValueError, OSError):
                continue
            if current is not None and loads_extension(current):
                return {"launcher": str(path), "hosts": []}
        return {"launcher": None, "hosts": []}
