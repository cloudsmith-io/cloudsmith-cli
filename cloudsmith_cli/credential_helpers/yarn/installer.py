# Copyright 2026 Cloudsmith Ltd
"""Load the Cloudsmith Yarn plugin in every Yarn project of the user, or in one project."""

from __future__ import annotations

import contextlib
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from ...core.session import create_requests_session
from .. import maven_tools
from ..maven_tools import (
    BuildToolError,
    ConfigFileConflict,
    ProjectNotFound,
    current_dir,
    write_atomically,
)

if TYPE_CHECKING:
    import requests

PLUGIN_NAME = "yarn-plugin-cloudsmith-auth"
PLUGIN_URL = (
    "https://dl.cloudsmith.io/public/cloudsmith/yarn-plugins/raw/names/"
    f"{PLUGIN_NAME}/versions/latest/{PLUGIN_NAME}.cjs"
)
# Yarn reads a plugin path relative to the directory of the .yarnrc.yml file.
PLUGIN_PATH = f".yarn/plugins/{PLUGIN_NAME}.cjs"
_PLUGINS_KEY = re.compile(r"^([\"']?)plugins\1[ \t]*:([^\n]*)\n", re.MULTILINE)
_ENTRY = re.compile(
    rf"^([ \t]*)- (?:path: )?([\"']?){re.escape(PLUGIN_PATH)}\2[ \t]*(?:#[^\n]*)?\n",
    re.MULTILINE,
)
# A line of a plugins list that loads the plugin, in any form that Yarn writes.
_ACTIVE_REFERENCE = re.compile(
    rf"^[ \t]*(?:- )?(?:path: )?([\"']?){re.escape(PLUGIN_PATH)}\1[ \t]*(?:#.*)?$",
    re.MULTILINE,
)
_NEXT_LINE = re.compile(r"(?:[ \t]*(?:#[^\n]*)?\n)*([ \t]*)\S")
_NEXT_KEY = re.compile(r"^[^\s#-]", re.MULTILINE)
_ITEM = re.compile(r"^([ \t]*)- ", re.MULTILINE)
_STACK_FRAME = re.compile(r"^[ \t]+at [^\n]*\n?", re.MULTILINE)
# The first bytes of the plugin bundle.
_PLUGIN_HEADER = f'module.exports = {{name: "{PLUGIN_NAME}"'.encode()
_VERSION = re.compile(r"/versions/([^/]+)/")
_NOT_REFERENCED = "isn't referenced"
_NO_PLUGIN_COMMAND = 'Command "plugin" not found'


def _rc_file() -> Path:
    return Path.home() / ".yarnrc.yml"


def _read(path: Path) -> str:
    """Return the text of *path* with a final newline, or an empty string when there is no file."""
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    return text if text.endswith("\n") or not text else f"{text}\n"


def _write(path: Path, text: str) -> None:
    write_atomically(path, text.encode("utf-8", errors="surrogateescape"))


def _write_or_remove(path: Path, text: str) -> None:
    """Write *text* to *path*, or remove *path* when *text* is empty."""
    if text.strip():
        _write(path, text)
    else:
        path.unlink()


def _remove_with_empty_parents(plugin_file: Path) -> None:
    """Remove *plugin_file*, then .yarn/plugins and .yarn when nothing else is in them."""
    plugin_file.unlink()
    for directory in (plugin_file.parent, plugin_file.parent.parent):
        with contextlib.suppress(OSError):
            directory.rmdir()


def _plugins_list(text: str) -> tuple[re.Match[str], int] | None:
    """Return the plugins key and the end of its list, or ``None`` when there is no key."""
    key = _PLUGINS_KEY.search(text)
    if key is None:
        return None
    next_key = _NEXT_KEY.search(text, key.end())
    return key, next_key.start() if next_key else len(text)


def _find_in_list(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    """Return the first match of *pattern* in the plugins list, or ``None``."""
    plugins = _plugins_list(text)
    if plugins is None:
        return None
    key, end = plugins
    return pattern.search(text, key.end(), end)


def _entry(text: str, rc_file: Path) -> re.Match[str] | None:
    """Return the plugin item in *text*, or ``None`` when *text* does not name the plugin.

    The command changes only one ``- path:`` item that is the only reference to
    the plugin. An item with more keys, such as the spec and checksum of
    `yarn plugin import`, can have blank lines and comments between its keys.
    """
    plugins = _plugins_list(text)
    if plugins is None:
        return None
    key, end = plugins
    references = text.count(PLUGIN_PATH, key.start(), end)
    if references == 0:
        return None
    entry = _ENTRY.search(text, key.end(), end)
    if references == 1 and entry and not _has_more_keys(text, entry):
        return entry
    raise ConfigFileConflict(
        f"{rc_file} names {PLUGIN_PATH} in a form that the command does not "
        "change. Remove the plugin from the file, and then run the command again."
    )


def _has_more_keys(text: str, entry: re.Match[str]) -> bool:
    """Return whether the next line with content is indented under the *entry* item."""
    following = _NEXT_LINE.match(text, entry.end())
    return following is not None and len(following.group(1)) > len(entry.group(1))


def _loads_plugin(directory: Path) -> bool:
    """Return whether the .yarnrc.yml in *directory* loads the plugin file next to it."""
    try:
        text = _read(directory / ".yarnrc.yml")
    except OSError:
        return False
    loads = _find_in_list(_ACTIVE_REFERENCE, text) is not None
    return loads and (directory / PLUGIN_PATH).is_file()


def _with_entry(text: str, rc_file: Path) -> str:
    """Return *text* with the plugin first in its plugins list."""
    key = _PLUGINS_KEY.search(text)
    if key is None:
        return f"{text}plugins:\n  - path: {PLUGIN_PATH}\n"
    if key.group(2).split("#")[0].strip():
        raise ConfigFileConflict(
            f"{rc_file} lists its plugins on one line, which the command does not "
            f"change. Add `- path: {PLUGIN_PATH}` to the plugins, or put each "
            "plugin on its own line and run the command again."
        )
    item = _find_in_list(_ITEM, text)
    at, indent = (item.start(), item.group(1)) if item else (key.end(), "  ")
    return f"{text[:at]}{indent}- path: {PLUGIN_PATH}\n{text[at:]}"


def _without_entry(text: str, entry: re.Match[str]) -> str:
    """Return *text* without *entry*, and without the plugins key when it has no other item."""
    text = text[: entry.start()] + text[entry.end() :]
    key = _PLUGINS_KEY.search(text)
    if key is not None and _find_in_list(_ITEM, text) is None:
        text = text[: key.start()] + text[key.end() :]
    return text


def _download(session: requests.Session | None) -> tuple[bytes, str]:
    """Return the latest plugin and its version."""
    response = (session or create_requests_session()).get(
        PLUGIN_URL, timeout=maven_tools.TIMEOUT_SECONDS
    )
    response.raise_for_status()
    if not response.content.startswith(_PLUGIN_HEADER):
        raise OSError(
            f"{PLUGIN_URL} did not return the Yarn plugin. A proxy or a firewall "
            "can answer in place of Cloudsmith. Check your proxy settings, or use "
            "the --proxy option."
        )
    version = _VERSION.search(response.url)
    return response.content, version.group(1) if version else "latest"


def _yarn(*args: str) -> str:
    """Run Yarn in the current directory, and raise BuildToolError when it fails."""
    executable = shutil.which("yarn")
    if executable is None:
        raise BuildToolError(
            "Yarn is not on PATH. Install Yarn, or run `corepack enable`. "
            "Then run the command again."
        )
    try:
        return maven_tools.tool_output([executable, *args], current_dir(), check=True)
    except BuildToolError as exc:
        raise BuildToolError(_STACK_FRAME.sub("", str(exc))) from exc


class YarnInstaller:
    name = "yarn"
    summary = "Yarn plugin that gets credentials from the Cloudsmith CLI"
    # The install command passes a session with its proxy and TLS settings.
    downloads_files = True
    NEXT_STEPS = (
        (
            "Next steps: add your Cloudsmith registry to .yarnrc.yml, with no "
            "npmAuthToken. See https://github.com/cloudsmith-labs/"
            "yarn-plugin-cloudsmith-auth#step-2-add-your-cloudsmith-registry"
        ),
        f"Then run `yarn plugin runtime` in the project. The list shows {PLUGIN_NAME}.",
    )

    def install(
        self,
        *,
        dry_run: bool = False,
        local: bool = False,
        session: requests.Session | None = None,
        **_options,
    ) -> list[str]:
        if local:
            return self._import_into_project(dry_run)
        rc_file = _rc_file()
        plugin_file = Path.home() / PLUGIN_PATH
        text = _read(rc_file)
        new_text = text if _entry(text, rc_file) else _with_entry(text, rc_file)
        content, version = _download(session)
        new_plugin = not plugin_file.exists() or plugin_file.read_bytes() != content
        if new_text == text and not new_plugin:
            return [f"{rc_file} already loads version {version} (no change)"]
        wrote, added = ("would write", "would add") if dry_run else ("wrote", "added")
        actions = []
        if new_plugin:
            actions.append(f"{wrote} {plugin_file} for version {version}")
            if not dry_run:
                plugin_file.parent.mkdir(parents=True, exist_ok=True)
                write_atomically(plugin_file, content)
        if new_text != text:
            actions.append(f"{added} {PLUGIN_PATH} to the plugins in {rc_file}")
            if not dry_run:
                _write(rc_file, new_text)
        return actions

    def uninstall(
        self, *, dry_run: bool = False, local: bool = False, **_options
    ) -> list[str]:
        if local:
            return self._remove_from_project(dry_run)
        rc_file = _rc_file()
        plugin_file = Path.home() / PLUGIN_PATH
        text = _read(rc_file)
        entry = _entry(text, rc_file)
        if entry is None and not plugin_file.exists():
            return [f"{rc_file} does not load {PLUGIN_NAME} (nothing to remove)"]
        verb = "would remove" if dry_run else "removed"
        actions = []
        if entry is not None:
            actions.append(f"{verb} {PLUGIN_PATH} from the plugins in {rc_file}")
            if not dry_run:
                _write_or_remove(rc_file, _without_entry(text, entry))
        if plugin_file.exists():
            actions.append(f"{verb} {plugin_file}")
            if not dry_run:
                _remove_with_empty_parents(plugin_file)
        return actions

    def _import_into_project(self, dry_run: bool) -> list[str]:
        project_dir = current_dir()
        if dry_run:
            return [f"would run `yarn plugin import {PLUGIN_URL}` in {project_dir}"]
        try:
            _yarn("plugin", "import", PLUGIN_URL)
        except BuildToolError as exc:
            if _NO_PLUGIN_COMMAND not in str(exc):
                raise
            raise BuildToolError(
                f"{exc}\nThe project uses Yarn 1, which does not load plugins. "
                "Run `yarn set version stable` to move the project to the "
                "current Yarn, and then run the command again."
            ) from exc
        return [f"imported {PLUGIN_NAME} into the Yarn project in {project_dir}"]

    def _remove_from_project(self, dry_run: bool) -> list[str]:
        project_dir = current_dir()
        if dry_run:
            return [f"would run `yarn plugin remove {PLUGIN_NAME}` in {project_dir}"]
        try:
            output = _yarn("plugin", "remove", PLUGIN_NAME)
        except BuildToolError as exc:
            if _NOT_REFERENCED not in str(exc):
                raise
            output = ""
        # Yarn prints "Removing <file>" only when the project loads the plugin.
        if "Removing " not in output:
            not_loaded = (
                f"the Yarn project in {project_dir} does not load {PLUGIN_NAME}"
            )
            return [f"{not_loaded} (nothing to remove)"]
        return [f"removed {PLUGIN_NAME} from the Yarn project in {project_dir}"]

    def status(self) -> dict:
        # Yarn reads the .yarnrc.yml of each parent directory, and the home one.
        directories = [Path.home()]
        with contextlib.suppress(ProjectNotFound):
            directories[:0] = [current_dir(), *current_dir().parents]
        directory = next(filter(_loads_plugin, directories), None)
        launcher = str(directory / PLUGIN_PATH) if directory else None
        return {"launcher": launcher, "hosts": []}
