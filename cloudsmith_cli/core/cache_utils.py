# Copyright 2026 Cloudsmith Ltd
"""Shared utilities for on-disk credential and cache storage."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

import tomlkit

if TYPE_CHECKING:
    from collections.abc import Callable


_FIX_CONFIG_FILE_HINT = "Correct or remove the file. Then run the command again."


class ConfigFileParseError(ValueError):
    """The config file exists but does not contain a valid object."""


def _atomic_write_text(dest: str, text: str, *, mode: int = 0o600) -> None:
    """Atomically write *text* to *dest* using a sibling temp file.

    Caller is responsible for ensuring the parent directory exists.
    """
    parent = os.path.dirname(dest) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, dest)
    except (OSError, TypeError, ValueError):
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path: str | os.PathLike, data: Any, *, mode: int = 0o600) -> None:
    """Atomically write JSON to a file with restrictive permissions.

    Writes to a sibling temp file, fsyncs, sets mode, then renames over the
    destination. Concurrent readers never see a partial file. Temp file is
    removed on error. Caller is responsible for ensuring the parent directory
    exists.
    """
    dest = os.fspath(path)
    _atomic_write_text(dest, json.dumps(data), mode=mode)


def _parse_config_text(
    dest: str, text: str | None, file_format: Literal["json", "toml"]
) -> dict[str, Any]:
    """Parse *text* as a top-level object; raise ConfigFileParseError if it is not one."""
    if file_format not in ("json", "toml"):
        raise ValueError(f"Unsupported format {file_format!r}")
    if text is None or not text.strip():
        return {}
    try:
        if file_format == "json":
            parsed: Any = json.loads(text)
        else:
            # Cargo accepts a UTF-8 BOM, but tomlkit does not.
            parsed = tomlkit.loads(text.removeprefix("\ufeff"))
    except ValueError as exc:
        raise ConfigFileParseError(
            f"Cannot parse {dest} as {file_format.upper()}: {exc}."
            f" {_FIX_CONFIG_FILE_HINT}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ConfigFileParseError(
            f"Cannot use {dest}: the top-level {file_format.upper()} value is not"
            f" an object. {_FIX_CONFIG_FILE_HINT}"
        )
    return parsed


def merge_config_file(
    path: str | os.PathLike[str],
    mutate: Callable[[dict[str, Any]], None],
    *,
    backup: bool = True,
    dry_run: bool = False,
    mode: int = 0o600,
    format: Literal["json", "toml"] = "json",
) -> bool:
    """Read a JSON object file, apply *mutate* in place, and atomically write it back.

    Parameters
    ----------
    path:
        Path to the JSON file (e.g. ``~/.docker/config.json``).
    mutate:
        Callable that receives the loaded ``dict`` and modifies it in place.
        It must not return a value; changes are applied to the dict directly.
    backup:
        When ``True`` (default) and the file already existed and content will
        change, copy the prior file to ``{path}.bak`` before writing.
    dry_run:
        When ``True``, perform the read + mutate + change-detection but make
        **no** writes (no temp file, no ``.bak``, no replace).
    mode:
        File-permission bits for the written file (default ``0o600``).
    format:
        Format to read/write from. (JSON or TOML)

    Returns
    -------
    bool
        ``True`` if the file content changed (or would change under
        ``dry_run``), ``False`` otherwise.

    Raises
    ------
    ConfigFileParseError
        The file is not UTF-8, does not parse, or its top-level value is not
        an object. The function does not write the file.

    Notes
    -----
    * If the file is missing or empty, the starting value is ``{}``.
    * The function compares the data before and after *mutate*, not the text,
      so a no-op leaves a file in another valid formatting untouched.
    * Key order is preserved — ``sort_keys`` is **not** used.
    * The on-disk form is ``json.dumps(data, indent=2, ensure_ascii=False) + "\\n"``.
    * Parent directory is created (mode ``0o700``) if absent.

    Concurrency
    -----------
    This is a single-writer, install-time helper (used by
    ``credential-helper install/uninstall``).  The read-modify-write is
    last-writer-wins and is **NOT** safe against concurrent writers mutating
    the same file; do not use it on a hot path.  The atomic replace guarantees
    the file is never left partially written, but concurrent merges can drop
    each other's changes.
    """
    dest = os.fspath(path)

    # ------------------------------------------------------------------
    # 1. Read existing content
    # ------------------------------------------------------------------
    existing_text: str | None = None
    try:
        with open(dest, encoding="utf-8") as f:
            existing_text = f.read()
    except FileNotFoundError:
        existing_text = None
    except UnicodeDecodeError as exc:
        raise ConfigFileParseError(
            f"Cannot read {dest}: the file is not valid UTF-8 ({exc})."
            f" {_FIX_CONFIG_FILE_HINT}"
        ) from exc

    # ------------------------------------------------------------------
    # 2. Parse → dict (missing/empty is {}; anything unparsable is an error)
    # ------------------------------------------------------------------
    data = _parse_config_text(dest, existing_text, format)
    before = copy.deepcopy(data)

    # ------------------------------------------------------------------
    # 3. Mutate in place
    # ------------------------------------------------------------------
    mutate(data)

    # ------------------------------------------------------------------
    # 4. Stable serialisation + change detection
    # ------------------------------------------------------------------
    if data == before:
        return False

    new_text = ""

    if format == "json":
        new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    else:
        new_text = tomlkit.dumps(data)

    if dry_run:
        return True

    # ------------------------------------------------------------------
    # 5. Ensure parent directory exists
    # ------------------------------------------------------------------
    parent = os.path.dirname(dest) or "."
    os.makedirs(parent, mode=0o700, exist_ok=True)

    # ------------------------------------------------------------------
    # 6. Backup (only when file existed and content changes)
    # ------------------------------------------------------------------
    if backup and existing_text is not None:
        _atomic_write_text(dest + ".bak", existing_text, mode=0o600)

    # ------------------------------------------------------------------
    # 7. Atomic write
    # ------------------------------------------------------------------
    _atomic_write_text(dest, new_text, mode=mode)

    return True
