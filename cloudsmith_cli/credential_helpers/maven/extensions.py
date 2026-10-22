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


def _find_extension(text: str) -> re.Match | None:
    for block in _EXTENSION_BLOCK.finditer(text):
        content = block.group(0)
        if f"<groupId>{GROUP_ID}</groupId>" in content and (
            f"<artifactId>{ARTIFACT_ID}</artifactId>" in content
        ):
            return block
    return None


def has_extension(text: str) -> bool:
    """Return whether *text* lists the Cloudsmith extension."""
    return _find_extension(text) is not None


def add_extension(text: str | None, version: str) -> tuple[str, bool]:
    """Return *text* with the Cloudsmith extension at *version*, and whether it changed.

    A *text* of ``None`` means that there is no file yet.
    """
    if text is None:
        return f"<extensions>\n{_render(version)}</extensions>\n", True
    block = _find_extension(text)
    if block:
        updated = _VERSION.sub(f"<version>{version}</version>", block.group(0), count=1)
        new_text = text[: block.start()] + updated + text[block.end() :]
        return new_text, new_text != text
    if _EMPTY_EXTENSIONS.search(text):
        new_text = _EMPTY_EXTENSIONS.sub(
            lambda empty: (
                f"<extensions{empty.group(1)}>\n{_render(version)}</extensions>"
            ),
            text,
            count=1,
        )
        return new_text, True
    closing = text.rfind("</extensions>")
    if closing == -1:
        raise ExtensionsFileError("The file has no <extensions> element.")
    return text[:closing] + _render(version) + text[closing:], True


def remove_extension(text: str) -> tuple[str | None, bool]:
    """Return *text* without the Cloudsmith extension, and whether it changed.

    The text is ``None`` when no other extension is left, so the file is not needed.
    """
    block = _find_extension(text)
    if not block:
        return text, False
    new_text = text[: block.start()] + text[block.end() :]
    if not _EXTENSION_BLOCK.search(new_text):
        return None, True
    return new_text, True
