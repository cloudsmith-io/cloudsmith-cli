# Copyright 2026 Cloudsmith Ltd
"""Add and remove the Cloudsmith extension in a Maven ``.mvn/extensions.xml`` file.

The functions edit the text, so the rest of the file keeps its formatting.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree

GROUP_ID = "io.cloudsmith"
ARTIFACT_ID = "cloudsmith-maven-extension"

# XML allows spaces and new lines before the > of a tag.
_EXTENSION_BLOCK = re.compile(r"<extension\s*>.*?</extension\s*>", re.DOTALL)
_EMPTY_EXTENSIONS = re.compile(r"<extensions\b([^>]*?)\s*/>")
_CLOSING_EXTENSIONS = re.compile(r"</extensions\s*>")
_VERSION = re.compile(r"<version\s*>([^<]*)</version\s*>")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_GROUP_ID = re.compile(rf"<groupId\s*>\s*{re.escape(GROUP_ID)}\s*</groupId\s*>")
_ARTIFACT_ID = re.compile(
    rf"<artifactId\s*>\s*{re.escape(ARTIFACT_ID)}\s*</artifactId\s*>"
)


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


def _has_extension_element(text: str) -> bool:
    """Return whether *text* has an <extension> element, or is not valid XML."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return True
    return any(element.tag.rpartition("}")[2] == "extension" for element in root.iter())


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
        new_text = text[: old_version.start(1)] + version + text[old_version.end(1) :]
        return new_text, new_text != text
    empty = _EMPTY_EXTENSIONS.search(masked)
    if empty:
        opened = f"<extensions{empty.group(1)}>\n{_render(version)}</extensions>"
        return text[: empty.start()] + opened + text[empty.end() :], True
    closing = _CLOSING_EXTENSIONS.search(masked)
    if closing is None:
        raise ExtensionsFileError("The file has no <extensions> element.")
    return text[: closing.start()] + _render(version) + text[closing.start() :], True


def remove_extension(text: str) -> tuple[str | None, bool]:
    """Return *text* without the Cloudsmith extension, and whether it changed.

    The text is ``None`` when no other extension is left, so the file is not needed.
    A file that is not valid XML without the extension is kept.
    """
    masked = _without_comments(text)
    block = _find_extension(masked)
    if not block:
        return text, False
    # Read the blanks around the block from the real text, because the masked
    # text shows a comment as blanks.
    start = len(text[: block.start()].rstrip(" \t"))
    end = len(text) - len(text[block.end() :].lstrip(" \t"))
    end += text.startswith("\n", end)
    new_text = text[:start] + text[end:]
    if not _has_extension_element(new_text):
        return None, True
    return new_text, True
