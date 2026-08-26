"""Shared CLI helpers for package metadata content."""

import json
import os
from dataclasses import dataclass, replace
from typing import Any

import click

from ..core.version import get_version as get_cli_version


@dataclass(frozen=True)
class ResolvedMetadata:
    """Metadata content resolved from CLI options."""

    provided: bool
    content: dict[str, Any] | None
    content_type: str | None = None
    source_identity: str | None = None
    content_file: str | None = None
    source_label: str | None = None


class MetadataContentError(click.ClickException):
    """Raised when supplied metadata content is not a valid JSON object."""

    def __init__(self, message, *, source_label=None):
        super().__init__(message)
        self.source_label = source_label


def default_metadata_source_identity() -> str:
    """Return the default value for metadata source identity options."""
    return f"cloudsmith-cli@{get_cli_version()}"


def source_label_for(content_file):
    """Return a human-readable label for a metadata content source."""
    if content_file == "-":
        return "stdin"
    if content_file:
        return os.path.basename(content_file)
    return "inline"


def _json_type_name(value):
    if value is None:
        return "null"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _parse_json_object(raw, source_label):
    try:
        content = json.loads(raw)
    except ValueError as exc:
        raise MetadataContentError(
            f"Invalid JSON in {source_label}: {exc}",
            source_label=source_label,
        ) from exc

    if not isinstance(content, dict):
        raise MetadataContentError(
            "Metadata content must be a JSON object. Found "
            f"{_json_type_name(content)}.",
            source_label=source_label,
        )

    return content


def resolve_metadata_content(
    *,
    content_file: str | None,
    inline_content: str | None,
    required: bool,
    file_option_name: str,
    content_option_name: str,
) -> ResolvedMetadata:
    """Resolve metadata content options into a parsed JSON object."""
    if content_file is not None and inline_content is not None:
        raise click.UsageError(
            f"{file_option_name} and {content_option_name} are mutually exclusive."
        )

    if content_file is not None:
        source_label = source_label_for(content_file)
        if content_file == "-":
            raw = click.get_text_stream("stdin").read()
        else:
            with open(content_file, encoding="utf-8") as fh:
                raw = fh.read()
    elif inline_content is not None:
        source_label = source_label_for(None)
        raw = inline_content
    elif required:
        raise click.UsageError(
            f"One of {file_option_name} or {content_option_name} is required."
        )
    else:
        return ResolvedMetadata(provided=False, content=None)

    return ResolvedMetadata(
        provided=True,
        content=_parse_json_object(raw, source_label),
        content_file=content_file,
        source_label=source_label,
    )


def require_metadata_content_type(
    *,
    content_type: str | None,
    content_provided: bool,
    option_name: str,
) -> None:
    """Require content type when metadata content has been supplied."""
    if content_provided and not content_type:
        raise click.UsageError(
            f"{option_name} is required when metadata content is supplied."
        )


def attach_metadata_options(
    metadata: ResolvedMetadata,
    *,
    content_type: str | None,
    source_identity: str | None,
) -> ResolvedMetadata:
    """Return a resolved payload with content type and source identity attached."""
    if not metadata.provided:
        return metadata

    return replace(
        metadata,
        content_type=content_type,
        source_identity=source_identity or default_metadata_source_identity(),
    )
