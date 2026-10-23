# Copyright 2026 Cloudsmith Ltd
"""Tests for the credentials file edits in cli/config.py."""

import os

import pytest

from ..config import CredentialsReader


def _expected_bytes(text):
    return text.replace("\n", os.linesep).encode()


@pytest.mark.parametrize(
    "newline", ["\n", pytest.param("\r\n", marks=pytest.mark.windows)]
)
def test_clear_api_key_twice_keeps_profile_sections(tmp_path, newline):
    path = tmp_path / "credentials.ini"
    content = (
        "[default]\napi_key = defaultkey\n\n[profile:staging]\napi_key: stagingkey\n"
    )
    path.write_bytes(content.replace("\n", newline).encode())

    CredentialsReader.clear_api_key(path)
    CredentialsReader.clear_api_key(path)

    assert path.read_bytes() == _expected_bytes(
        "[default]\napi_key =\n\n[profile:staging]\napi_key =\n"
    )


def test_update_api_key_after_empty_key_keeps_profile_sections(tmp_path):
    path = tmp_path / "credentials.ini"
    path.write_text("[default]\napi_key =\n\n[profile:staging]\napi_key = stagingkey\n")

    CredentialsReader.update_api_key(path, "newkey")

    assert path.read_bytes() == _expected_bytes(
        "[default]\napi_key = newkey\n\n[profile:staging]\napi_key = newkey\n"
    )
