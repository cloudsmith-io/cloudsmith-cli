# Copyright 2026 Cloudsmith Ltd
"""Tests for the core utilities."""

import pytest

from ..utils import json_output_in_argv


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["cloudsmith", "list", "repos", "-F", "json"], True),
        (["cloudsmith", "list", "repos", "--output-format", "pretty_json"], True),
        (["cloudsmith", "list", "repos", "--output-format=json"], True),
        (["cloudsmith", "list", "repos", "-F", "pretty"], False),
        (["cloudsmith", "list", "repos"], False),
        (["cloudsmith", "list", "repos", "-F"], False),
        (["cloudsmith", "-F", "json", "-F", "pretty"], False),
        (["cloudsmith", "--output-format=pretty", "-F", "json"], True),
    ],
)
def test_json_output_in_argv(argv, expected):
    assert json_output_in_argv(argv) is expected
