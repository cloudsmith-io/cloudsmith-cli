# Copyright 2026 Cloudsmith Ltd
"""Add and remove the Cloudsmith extension in a Maven ``.mvn/extensions.xml`` file.

The functions edit the text, so the rest of the file keeps its formatting.
"""

from __future__ import annotations

import re

GROUP_ID = "io.cloudsmith"
ARTIFACT_ID = "cloudsmith-maven-extension"

_EXTENSION_BLOCK = re.compile(r"[ \t]*<extension>.*?</extension>[ \t]*\n?", re.DOTALL)
_EMPTY_EXTENSIONS = re.compile(r"<extensions\b([^>]*?)\s*/>")
_VERSION = re.compile(r"<version>[^<]*</version>")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_GROUP_ID = re.compile(rf"<groupId>\s*{re.escape(GROUP_ID)}\s*</groupId>")
_ARTIFACT_ID = re.compile(rf"<artifactId>\s*{re.escape(ARTIFACT_ID)}\s*</artifactId>")


class ExtensionsFileError(Exception):
    """The extensions.xml file has no <extensions> element to add to."""


def _render(version: str) -> str:
    return (
        "  <extension>\n"
        f"    <groupId>{GROUP_ID}</groupId>\n"
        f"    <artifactId>{ARTIFACT_ID}</artifactId>\n"
        f"    <version>{version}</version>\n"
        "  </extension>\n"
    )


def _without_comments(text: str) -> str:
    """Return *text* with each comment replaced by spaces, so the offsets stay the same."""
    return _COMMENT.sub(lambda comment: " " * len(comment.group(0)), text)


def _find_extension(masked: str) -> re.Match | None:
    for block in _EXTENSION_BLOCK.finditer(masked):
        if _GROUP_ID.search(block.group(0)) and _ARTIFACT_ID.search(block.group(0)):
            return block
    return None


def has_extension(text: str) -> bool:
    """Return whether *text* lists the Cloudsmith extension."""
    return _find_extension(_without_comments(text)) is not None


def add_extension(text: str | None, version: str) -> tuple[str, bool]:
    """Return *text* with the Cloudsmith extension at *version*, and whether it changed.

    A *text* of ``None`` means that there is no file yet.
    """
    if text is None:
        return f"<extensions>\n{_render(version)}</extensions>\n", True
    masked = _without_comments(text)
    block = _find_extension(masked)
    if block:
        old_version = _VERSION.search(masked, block.start(), block.end())
        if old_version is None:
            raise ExtensionsFileError("The Cloudsmith extension has no <version>.")
        new_text = (
            text[: old_version.start()]
            + f"<version>{version}</version>"
            + text[old_version.end() :]
        )
        return new_text, new_text != text
    empty = _EMPTY_EXTENSIONS.search(masked)
    if empty:
        opened = f"<extensions{empty.group(1)}>\n{_render(version)}</extensions>"
        return text[: empty.start()] + opened + text[empty.end() :], True
    closing = masked.rfind("</extensions>")
    if closing == -1:
        raise ExtensionsFileError("The file has no <extensions> element.")
    return text[:closing] + _render(version) + text[closing:], True


def remove_extension(text: str) -> tuple[str | None, bool]:
    """Return *text* without the Cloudsmith extension, and whether it changed.

    The text is ``None`` when no other extension is left, so the file is not needed.
    """
    masked = _without_comments(text)
    block = _find_extension(masked)
    if not block:
        return text, False
    if not _EXTENSION_BLOCK.search(masked[: block.start()] + masked[block.end() :]):
        return None, True
    return text[: block.start()] + text[block.end() :], True
