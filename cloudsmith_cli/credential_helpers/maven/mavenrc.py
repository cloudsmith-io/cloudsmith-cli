# Copyright 2026 Cloudsmith Ltd
"""Add and remove the block that loads the Cloudsmith extension in ``~/.mavenrc``.

The ``mvn`` and ``mvnw`` scripts read ``~/.mavenrc`` before they start Maven. The
block adds the extension to ``maven.ext.class.path``, which every Maven version
reads. The functions change only the block, so the other lines stay as they are.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

BEGIN = "# >>> cloudsmith credential-helper install maven >>>"
END = "# <<< cloudsmith credential-helper install maven <<<"

_BLOCK_PATTERN = rf"^{re.escape(BEGIN)}\n.*?^{re.escape(END)}\n?"
_BLOCK = re.compile(_BLOCK_PATTERN, re.DOTALL | re.MULTILINE)
# Also matches the blank line that add_block puts before the block.
_BLOCK_WITH_SEPARATOR = re.compile(
    rf"(?:(?<=\n)\n)?{_BLOCK_PATTERN}", re.DOTALL | re.MULTILINE
)


def render_block(jar: Path) -> str:
    """Return the block that adds *jar* to the Maven extension class path."""
    option = "-Dmaven.ext.class.path="
    after_last = "cloudsmith_after_class_path"
    # The shell expands \ " $ and ` in double quotes, so the path escapes them.
    jar_text = re.sub(r'([\\"$`])', r"\\\1", str(jar))
    # mvn splits MAVEN_OPTS at spaces, so an option starts after a space.
    words = "cloudsmith_maven_opts"
    return (
        f"{BEGIN}\n"
        "# Java uses only the last -D value, so add the JAR to that value.\n"
        f'{words}=" $MAVEN_OPTS"\n'
        f'case "${words}" in\n'
        f'  *" {option}"*)\n'
        f'    {after_last}="${{{words}##* {option}}}"\n'
        f'    case "{os.pathsep}${{{after_last}%% *}}{os.pathsep}" in\n'
        f'      *"{os.pathsep}{jar_text}{os.pathsep}"*) ;;\n'
        f'      *) MAVEN_OPTS="${{{words}% {option}*}} {option}{jar_text}{os.pathsep}'
        f'${after_last}"\n'
        '         MAVEN_OPTS="${MAVEN_OPTS# }" ;;\n'
        "    esac ;;\n"
        f'  *) MAVEN_OPTS="$MAVEN_OPTS {option}{jar_text}" ;;\n'
        "esac\n"
        f"unset {words} {after_last}\n"
        f"{END}\n"
    )


def has_block(text: str) -> bool:
    """Return whether *text* has the block."""
    return _BLOCK.search(text) is not None


def add_block(text: str | None, jar: Path) -> tuple[str, bool]:
    """Return *text* with the block for *jar*, and whether it changed.

    A *text* of ``None`` means that there is no file yet.
    """
    block = render_block(jar)
    if not text:
        return block, True
    existing = _BLOCK.search(text)
    if existing:
        new_text = text[: existing.start()] + block + text[existing.end() :]
        return new_text, new_text != text
    separator = "\n" if text.endswith("\n") else "\n\n"
    return text + separator + block, True


def remove_block(text: str) -> tuple[str | None, bool]:
    """Return *text* without the block, and whether it changed.

    The text is ``None`` when nothing else is left, so the file is not needed.
    """
    if not has_block(text):
        return text, False
    new_text = _BLOCK_WITH_SEPARATOR.sub("", text, count=1)
    return (new_text if new_text.strip() else None), True
