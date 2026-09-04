# Copyright 2026 Cloudsmith Ltd
"""Idempotent management of the ``credentials_helper`` block in ``~/.terraformrc``.

Terraform's CLI configuration file is HCL, but the one block this helper owns is
simple and regular enough to manage as text without pulling in an HCL parser
(which would also lose the user's comments and formatting on round-trip).  The
functions here locate a ``credentials_helper "cloudsmith" { ... }`` block by
regex and add, replace, or remove *only* that block, leaving the rest of the
file byte-for-byte intact.

Terraform allows at most one ``credentials_helper`` block in the whole file, so
if a block for a *different* helper is already present these helpers refuse
rather than silently producing an invalid config.

This module is intentionally free of Click/sys imports so it can be unit-tested
without invoking the CLI machinery.
"""

from __future__ import annotations

import re

HELPER_NAME = "cloudsmith"

# Matches a whole `credentials_helper "<name>" { ... }` block, capturing the
# helper name. The body is matched non-greedily up to the first closing brace on
# its own — the block this helper writes never contains nested braces, and a
# hand-written one would not either, so a flat match is sufficient and avoids a
# full HCL parser. DOTALL lets the body span lines.
_BLOCK_RE = re.compile(
    r'credentials_helper\s+"(?P<name>[^"]+)"\s*\{.*?\}',
    re.DOTALL,
)


class TerraformrcConflictError(Exception):
    """Raised when a credentials_helper block for a different helper exists.

    Terraform permits only one ``credentials_helper`` block, so we must not add
    a second one, and we must not overwrite someone else's.
    """

    def __init__(
        self, existing_name: str, rc_path: str = "the Terraform CLI config"
    ) -> None:
        self.existing_name = existing_name
        self.rc_path = rc_path
        super().__init__(
            f"{rc_path} already configures a different credentials helper "
            f"({existing_name!r}). Terraform allows only one credentials_helper "
            "block; remove the existing one before installing the Cloudsmith "
            "helper."
        )


def render_block(args: list[str] | tuple[str, ...] = ()) -> str:
    """Render the ``credentials_helper "cloudsmith"`` block for *args*.

    Args:
        args: The values for the block's ``args = [...]`` list, e.g.
            ``["--org", "acme", "-P", "ci"]``.

    Returns:
        The HCL block as text, without a trailing newline.
    """
    rendered_args = ", ".join(f'"{a}"' for a in args)
    return f'credentials_helper "{HELPER_NAME}" {{\n  args = [{rendered_args}]\n}}'


def find_block(text: str) -> re.Match[str] | None:
    """Return the first ``credentials_helper`` block match in *text*, or None."""
    return _BLOCK_RE.search(text)


def add_or_update_block(
    text: str,
    args: list[str] | tuple[str, ...] = (),
    rc_path: str | None = None,
) -> tuple[str, bool]:
    """Return *text* with the Cloudsmith credentials_helper block installed.

    If a Cloudsmith block already exists it is replaced (so re-running with
    different ``args`` updates it); if a block for a different helper exists a
    :class:`TerraformrcConflictError` is raised; otherwise the block is appended.

    Args:
        text: Current terraformrc content ("" when the file does not exist).
        args: Values for the block's ``args`` list.
        rc_path: The resolved path of the config file, used only to make the
            conflict error message platform-accurate. Optional.

    Returns:
        A ``(new_text, changed)`` tuple; *changed* is False when the file
        already contained exactly the desired block.
    """
    block = render_block(args)
    match = find_block(text)

    if match is None:
        # No credentials_helper at all: append our block, keeping any existing
        # content and separating with a blank line.
        if text.strip() == "":
            new_text = block + "\n"
        else:
            separator = "" if text.endswith("\n") else "\n"
            new_text = f"{text}{separator}\n{block}\n"
        return new_text, new_text != text

    if match.group("name") != HELPER_NAME:
        if rc_path is not None:
            raise TerraformrcConflictError(match.group("name"), rc_path)
        raise TerraformrcConflictError(match.group("name"))

    # Replace the existing Cloudsmith block in place.
    new_text = text[: match.start()] + block + text[match.end() :]
    return new_text, new_text != text


def remove_block(text: str) -> tuple[str, bool]:
    """Return *text* with the Cloudsmith credentials_helper block removed.

    A block for a different helper is left untouched (nothing to remove).

    Args:
        text: Current terraformrc content.

    Returns:
        A ``(new_text, changed)`` tuple; *changed* is False when there was no
        Cloudsmith block to remove.
    """
    match = find_block(text)
    if match is None or match.group("name") != HELPER_NAME:
        return text, False

    # Drop the block and collapse the surrounding blank lines it leaves behind
    # so we don't accumulate whitespace across install/uninstall cycles.
    new_text = text[: match.start()] + text[match.end() :]
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    new_text = new_text.strip("\n")
    if new_text:
        new_text += "\n"
    return new_text, new_text != text
