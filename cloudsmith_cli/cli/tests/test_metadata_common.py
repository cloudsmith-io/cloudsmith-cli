"""Tests for shared metadata CLI helpers."""

import io

import click
import pytest

from ..metadata_common import (
    attach_metadata_options,
    default_metadata_source_identity,
    require_metadata_content_type,
    resolve_metadata_content,
)


def test_resolve_metadata_content_optional_missing_returns_not_provided():
    metadata = resolve_metadata_content(
        content_file=None,
        inline_content=None,
        required=False,
        file_option_name="--file",
        content_option_name="--content",
    )

    assert metadata.provided is False
    assert metadata.content is None


def test_resolve_metadata_content_required_missing_raises():
    with pytest.raises(click.UsageError, match="required"):
        resolve_metadata_content(
            content_file=None,
            inline_content=None,
            required=True,
            file_option_name="--file",
            content_option_name="--content",
        )


def test_resolve_metadata_content_rejects_both_sources():
    with pytest.raises(click.UsageError, match="mutually exclusive"):
        resolve_metadata_content(
            content_file="/tmp/payload.json",
            inline_content="{}",
            required=True,
            file_option_name="--file",
            content_option_name="--content",
        )


def test_resolve_metadata_content_valid_inline_object():
    metadata = resolve_metadata_content(
        content_file=None,
        inline_content='{"x": 1}',
        required=True,
        file_option_name="--file",
        content_option_name="--content",
    )

    assert metadata.provided is True
    assert metadata.content == {"x": 1}
    assert metadata.source_label == "inline"


@pytest.mark.parametrize("raw", ["null", "[]", '"text"', "3", "true"])
def test_resolve_metadata_content_rejects_non_objects(raw):
    with pytest.raises(click.ClickException, match="JSON object"):
        resolve_metadata_content(
            content_file=None,
            inline_content=raw,
            required=True,
            file_option_name="--file",
            content_option_name="--content",
        )


def test_resolve_metadata_content_reads_stdin_once():
    stdin = io.StringIO('{"from": "stdin"}')

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "cloudsmith_cli.cli.metadata_common.click.get_text_stream",
            lambda name: stdin,
        )
        metadata = resolve_metadata_content(
            content_file="-",
            inline_content=None,
            required=True,
            file_option_name="--file",
            content_option_name="--content",
        )

    assert metadata.content == {"from": "stdin"}
    assert metadata.source_label == "stdin"
    assert stdin.read() == ""


def test_require_metadata_content_type_when_content_supplied():
    with pytest.raises(click.UsageError, match="--content-type"):
        require_metadata_content_type(
            content_type=None,
            content_provided=True,
            option_name="--content-type",
        )


def test_attach_metadata_options_defaults_source_identity():
    metadata = resolve_metadata_content(
        content_file=None,
        inline_content="{}",
        required=True,
        file_option_name="--file",
        content_option_name="--content",
    )

    resolved = attach_metadata_options(
        metadata,
        content_type="application/json",
        source_identity=None,
    )

    assert resolved.content_type == "application/json"
    assert resolved.source_identity == default_metadata_source_identity()
