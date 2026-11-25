# Copyright 2026 Cloudsmith Ltd
"""
Shared code for the installers of the Cloudsmith Maven tools.

The Maven extension and the Gradle and sbt plugins get their credential from
`cloudsmith credential-helper generic`. They are published to a public
Cloudsmith repository.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree

from ..core.session import create_requests_session
from .launchers import is_windows

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

REPOSITORY_URL = "https://dl.cloudsmith.io/public/cloudsmith/maven-tools/maven/"
TIMEOUT_SECONDS = 30
TOOL_TIMEOUT_SECONDS = 60
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class ProjectNotFound(Exception):
    """The current directory does not exist or is not the root directory of a project."""


def current_dir() -> Path:
    """Return the current directory, or raise ProjectNotFound when it does not exist."""
    try:
        return Path.cwd()
    except FileNotFoundError as exc:
        raise ProjectNotFound(
            "The current directory does not exist. "
            "Change to the root directory of a project and run the command again."
        ) from exc


class ConfigFileConflict(Exception):
    """The config file has content that the installer did not write."""


class BuildToolError(Exception):
    """The build tool did not report a path that every build uses."""


def _stop(process: subprocess.Popen[str]) -> None:
    """Stop the tool and the processes that it started, such as the JVM of a launcher script."""
    if is_windows():
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        # The tool can finish between the timeout and the kill.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def tool_output(command: list[str], cwd: Path | None = None) -> str:
    """Return what the build tool prints, without colors, or an empty string when it does not run."""
    try:
        process = subprocess.Popen(
            # PATH can have a relative directory, and the tool runs in another one.
            [os.path.abspath(command[0]), *command[1:]],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError:
        return ""
    with process:
        try:
            output, _ = process.communicate(timeout=TOOL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            _stop(process)
            raise BuildToolError(
                f"{Path(command[0]).name} did not finish in {TOOL_TIMEOUT_SECONDS} "
                "seconds. Make sure that it runs, and then run the command again."
            ) from exc
        except KeyboardInterrupt:
            # The tool runs in its own session, so Ctrl+C does not reach it.
            _stop(process)
            raise
    return _ANSI_ESCAPE.sub("", output)


def ask_outside_projects(
    ask: Callable[[Path], Path | None], relative_message: str
) -> Path | None:
    """Return the path that *ask* gets from the build tool in an empty directory.

    An empty ``.mvn`` and ``settings.gradle`` make each directory a project root,
    so Maven and Gradle do not read a project above the temporary directory.
    The tool runs again in a subdirectory. A different answer means a relative
    path, which changes with the directory of each build. No second answer means
    that the tool failed.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty_dir:
        nested_dir = Path(empty_dir) / "nested"
        for project_dir in (Path(empty_dir), nested_dir):
            (project_dir / ".mvn").mkdir(parents=True)
            (project_dir / "settings.gradle").write_text("", encoding="utf-8")
        answer = ask(Path(empty_dir))
        nested_answer = ask(nested_dir) if answer else None
    if nested_answer and nested_answer != answer:
        raise BuildToolError(relative_message)
    return nested_answer


def waiting_message(tool: str, reported: str) -> str:
    """Return the message to show while the build tool starts, which can take some seconds."""
    return f"Asking {tool} for its {reported}. This can take a few seconds."


def no_answer_warning(tool: str, reported: str, default: Path) -> str:
    """Return the warning for a build tool that ran but did not report a location."""
    return (
        f"WARNING: {tool} did not report its {reported}, so the command uses {default}."
    )


def _get(artifact_path: str, session: requests.Session | None) -> bytes:
    response = (session or create_requests_session()).get(
        REPOSITORY_URL + artifact_path, timeout=TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.content


def latest_version(artifact_path: str, session: requests.Session | None = None) -> str:
    """Return the newest release of the artifact at *artifact_path*."""
    metadata_path = f"{artifact_path}/maven-metadata.xml"
    content = _get(metadata_path, session)
    try:
        metadata = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise OSError(
            f"{REPOSITORY_URL}{metadata_path} did not return Maven metadata. "
            "A proxy or a firewall can answer in place of the repository. "
            "Check your proxy settings, or use the --proxy option."
        ) from exc
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
    # Install skips a file that exists, so a failed write must not leave a partial file.
    write_atomically(destination, content)


def write_atomically(path: Path, data: bytes) -> None:
    """Write *data* to *path*, so that a failed write leaves the old file as it was."""
    # Write through a symbolic link, such as a dotfile, so that the link stays.
    target = path.resolve()
    partial = target.with_name(f"{target.name}.{os.getpid()}.part")
    # Make the copy before the data goes in, never with a wider mode than the file.
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o666
    try:
        partial.touch(mode=mode, exist_ok=False)
        partial.write_bytes(data)
        if target.exists():
            shutil.copymode(target, partial)
        partial.replace(target)
    except OSError:
        partial.unlink(missing_ok=True)
        raise


class ConfigFileInstaller:
    """Install a plugin with one config file that names its latest version."""

    name = ""
    summary = ""
    artifact_path = ""
    # The install command passes a session with its proxy and TLS settings.
    downloads_files = True
    # The install and uninstall commands pass a callback that shows the waiting message.
    ASKS_BUILD_TOOL = True
    # The build tool that reports where it reads the config file for every build.
    tool = ""
    reported = ""
    relative_message = ""

    def path(self) -> Path:
        """Return the config file that loads the plugin for every build."""
        raise NotImplementedError

    def local_path(self) -> Path:
        """Return the config file that loads the plugin for the current project."""
        raise NotImplementedError

    def reported_path(self, executable: str, cwd: Path) -> Path | None:
        """Return the config file in the location that the build tool reports in *cwd*."""
        raise NotImplementedError

    def _path_for_every_build(
        self, progress: Callable[[str], None] | None
    ) -> tuple[Path, list[str]]:
        """Return the config file that the build tool reports, and any warning."""
        executable = shutil.which(self.tool) if self.tool else None
        if executable is None:
            return self.path(), []
        if progress:
            progress(waiting_message(self.tool, self.reported))
        path = ask_outside_projects(
            partial(self.reported_path, executable), self.relative_message
        )
        if path is None:
            default = self.path()
            return default, [no_answer_warning(self.tool, self.reported, default)]
        return path, []

    def render(self, version: str) -> str:
        """Return the content of the config file for *version*."""
        raise NotImplementedError

    def _written_by_install(self, text: str) -> bool:
        placeholder = "\0"
        template = self.render(placeholder)
        before, after = (re.escape(part) for part in template.split(placeholder))
        return re.fullmatch(rf"{before}[^\s\"]+{after}", text) is not None

    def _read_own_file(self, path: Path) -> str | None:
        """Return the text of *path*, or ``None`` when there is no file."""
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
        if not self._written_by_install(text):
            raise ConfigFileConflict(
                f"{path} has settings that `cloudsmith credential-helper install "
                f"{self.name}` did not write. Move them to a different file, "
                "and then run the command again."
            )
        return text

    def install(
        self,
        *,
        dry_run: bool = False,
        local: bool = False,
        session: requests.Session | None = None,
        progress: Callable[[str], None] | None = None,
        **_options,
    ) -> list[str]:
        path, warnings = (
            (self.local_path(), []) if local else self._path_for_every_build(progress)
        )
        version = latest_version(self.artifact_path, session)
        text = self.render(version)
        if self._read_own_file(path) == text:
            return [*warnings, f"{path} already uses version {version} (no change)"]
        if dry_run:
            return [*warnings, f"would write {path} for version {version}"]
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(path, text.encode("utf-8"))
        return [*warnings, f"wrote {path} for version {version}"]

    def uninstall(
        self,
        *,
        dry_run: bool = False,
        local: bool = False,
        progress: Callable[[str], None] | None = None,
        **_options,
    ) -> list[str]:
        path, warnings = (
            (self.local_path(), []) if local else self._path_for_every_build(progress)
        )
        if self._read_own_file(path) is None:
            return [*warnings, f"{path} not found (nothing to remove)"]
        if dry_run:
            return [*warnings, f"would remove {path}"]
        path.unlink()
        return [*warnings, f"removed {path}"]

    def status(self) -> dict:
        paths = [self.path()]
        # Gradle has no local config, and the current directory is often not a project.
        with contextlib.suppress(NotImplementedError, ProjectNotFound):
            paths.append(self.local_path())
        path = next((path for path in paths if self._is_own_file(path)), None)
        return {"launcher": str(path) if path else None, "hosts": []}

    def _is_own_file(self, path: Path) -> bool:
        """Return whether *path* is a file that uninstall can remove."""
        try:
            return self._read_own_file(path) is not None
        except (ConfigFileConflict, OSError):
            return False
