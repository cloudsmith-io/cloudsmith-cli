# Copyright 2026 Cloudsmith Ltd
"""Tests for api_host normalization."""

import click
import pytest

from ..config import Options
from ..decorators import _guard_untrusted_endpoints
from ..validators import normalize_api_host
from .test_api_host_validation import _FakeContext, _write_cwd_config


class TestNormalizeApiHost:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("api.cloudsmith.io", "https://api.cloudsmith.io"),
            ("api.cloudsmith.io/", "https://api.cloudsmith.io"),
            ("api.cloudsmith.io:8080", "https://api.cloudsmith.io:8080"),
            ("//api.cloudsmith.io", "https://api.cloudsmith.io"),
            ("https://api.cloudsmith.io/", "https://api.cloudsmith.io"),
            ("https://api.cloudsmith.io///", "https://api.cloudsmith.io"),
            ("https://api.cloudsmith.io/v1/", "https://api.cloudsmith.io/v1"),
            ("  https://api.cloudsmith.io  ", "https://api.cloudsmith.io"),
            ("\thttps://api.cloudsmith.io\n", "https://api.cloudsmith.io"),
            ("http://localhost:8000/", "http://localhost:8000"),
            ("https://api.cloudsmith.io", "https://api.cloudsmith.io"),
        ],
    )
    def test_host_is_normalized(self, value, expected):
        assert normalize_api_host(value) == expected

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_values_pass_through(self, value):
        assert not normalize_api_host(value)


class TestOptionsApiHost:
    def test_setter_normalizes(self):
        opts = Options()
        opts.api_host = " api.cloudsmith.io/ "
        assert opts.api_host == "https://api.cloudsmith.io"

    def test_setter_accepts_none(self):
        opts = Options()
        opts.api_host = None
        assert opts.api_host is None


class TestGuardWithNormalizedHost:
    def test_untrusted_host_without_scheme_still_raises(self, tmp_path, monkeypatch):
        _write_cwd_config(
            tmp_path, monkeypatch, "[default]\napi_host = evil.example.com\n"
        )
        opts = Options()
        opts.api_host = "evil.example.com"
        with pytest.raises(click.UsageError):
            _guard_untrusted_endpoints(_FakeContext({}), opts, (), ())

    def test_trusted_host_without_scheme_passes(self, tmp_path, monkeypatch):
        _write_cwd_config(
            tmp_path, monkeypatch, "[default]\napi_host = api.cloudsmith.io/\n"
        )
        opts = Options()
        opts.api_host = "api.cloudsmith.io/"
        _guard_untrusted_endpoints(_FakeContext({}), opts, (), ())
