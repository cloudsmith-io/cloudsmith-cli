# Copyright 2026 Cloudsmith Ltd
"""Tests for api_host / api_proxy allow-list validation."""

import click
import pytest
from click.core import ParameterSource

from ..config import ConfigReader, Options
from ..decorators import _guard_untrusted_endpoints, _parse_suffixes
from ..validators import (
    PUBLIC_API_HOST_SUFFIXES,
    is_trusted_api_host,
    validate_untrusted_api_host,
    validate_untrusted_api_proxy,
)


class TestIsTrustedApiHost:
    @pytest.mark.parametrize(
        "host",
        [
            "https://api.cloudsmith.io",
            "https://upload.cloudsmith.com",
            "https://cloudsmith.io",
            "https://cloudsmith.com",
            "https://api.cloudsmith.io:443/v1/",
        ],
    )
    def test_public_hosts_are_trusted(self, host):
        assert is_trusted_api_host(host) is True

    @pytest.mark.parametrize(
        "host",
        [
            "https://evil.example.com",
            "https://api.cloudsmith.io.evil.com",
            "https://api.cloudsmith.io@evil.com",
            "https://cloudsmith.io.evil.com",
            "https://notcloudsmith.io",
            "https://cloudsmith.org",
            "",
            "   ",
        ],
    )
    def test_other_hosts_are_untrusted(self, host):
        assert is_trusted_api_host(host) is False

    def test_extra_suffix_is_accepted(self):
        assert (
            is_trusted_api_host("https://api.internal.example", ["internal.example"])
            is True
        )


class TestValidateUntrustedApiHost:
    def test_trusted_host_passes(self):
        validate_untrusted_api_host("https://api.cloudsmith.io")

    def test_untrusted_host_raises_usage_error(self):
        bad_host = "https://evil.example.com"
        with pytest.raises(click.UsageError) as exc:
            validate_untrusted_api_host(bad_host)
        message = str(exc.value)
        assert bad_host in message
        assert "--config-file" in message
        for suffix in PUBLIC_API_HOST_SUFFIXES:
            assert suffix in message

    def test_extra_suffix_makes_host_pass(self):
        validate_untrusted_api_host(
            "https://api.internal.example", ["internal.example"]
        )


class TestValidateUntrustedApiProxy:
    def test_proxy_without_allowed_suffixes_raises(self):
        bad_proxy = "http://attacker.example.com:3128"
        with pytest.raises(click.UsageError) as exc:
            validate_untrusted_api_proxy(bad_proxy)
        message = str(exc.value)
        assert bad_proxy in message
        assert "--api-proxy" in message
        assert "--config-file" in message

    def test_proxy_matching_allowed_suffix_passes(self):
        validate_untrusted_api_proxy(
            "http://proxy.internal.example:3128", ["internal.example"]
        )


class TestReadRelativeConfigValue:
    def test_reads_api_host_from_relative_config(self, tmp_path, monkeypatch):
        (tmp_path / "config.ini").write_text(
            "[default]\napi_host = https://evil.example.com\n"
        )
        monkeypatch.chdir(tmp_path)
        assert (
            ConfigReader.read_relative_config_value("api_host")
            == "https://evil.example.com"
        )

    def test_strips_surrounding_quotes(self, tmp_path, monkeypatch):
        (tmp_path / "config.ini").write_text(
            '[default]\napi_host = "https://evil.example.com"\n'
        )
        monkeypatch.chdir(tmp_path)
        assert (
            ConfigReader.read_relative_config_value("api_host")
            == "https://evil.example.com"
        )

    def test_profile_section_overrides_default(self, tmp_path, monkeypatch):
        (tmp_path / "config.ini").write_text(
            "[default]\napi_host = https://a.cloudsmith.io\n"
            "[profile:ci]\napi_host = https://evil.example.com\n"
        )
        monkeypatch.chdir(tmp_path)
        assert (
            ConfigReader.read_relative_config_value("api_host", profile="ci")
            == "https://evil.example.com"
        )

    def test_missing_key_returns_none(self, tmp_path, monkeypatch):
        (tmp_path / "config.ini").write_text("[default]\napi_proxy = \n")
        monkeypatch.chdir(tmp_path)
        assert ConfigReader.read_relative_config_value("api_host") is None

    def test_no_config_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert ConfigReader.read_relative_config_value("api_host") is None


class _FakeContext:
    def __init__(self, sources, profile=None):
        self._sources = sources
        self.meta = {"profile": profile}

    def get_parameter_source(self, name):
        return self._sources.get(name, ParameterSource.DEFAULT)


def _write_cwd_config(tmp_path, monkeypatch, body):
    (tmp_path / "config.ini").write_text(body)
    monkeypatch.chdir(tmp_path)


class TestParseSuffixes:
    def test_splits_and_strips_csv(self):
        assert _parse_suffixes(" a.internal , b.internal ") == (
            "a.internal",
            "b.internal",
        )

    def test_strips_leading_dot(self):
        assert _parse_suffixes(" .internal.example , .b.com ") == (
            "internal.example",
            "b.com",
        )

    def test_none_is_empty(self):
        assert not _parse_suffixes(None)


class TestGuardUntrustedEndpoints:
    def test_untrusted_bad_host_raises(self, tmp_path, monkeypatch):
        _write_cwd_config(
            tmp_path, monkeypatch, "[default]\napi_host = https://evil.example.com\n"
        )
        opts = Options()
        opts.api_host = "https://evil.example.com"
        ctx = _FakeContext({})
        with pytest.raises(click.UsageError):
            _guard_untrusted_endpoints(ctx, opts, (), ())

    def test_untrusted_cloudsmith_host_passes(self, tmp_path, monkeypatch):
        _write_cwd_config(
            tmp_path, monkeypatch, "[default]\napi_host = https://api.cloudsmith.io\n"
        )
        opts = Options()
        opts.api_host = "https://api.cloudsmith.io"
        _guard_untrusted_endpoints(_FakeContext({}), opts, (), ())

    def test_flag_source_bypasses_enforcement(self, tmp_path, monkeypatch):
        _write_cwd_config(
            tmp_path, monkeypatch, "[default]\napi_host = https://evil.example.com\n"
        )
        opts = Options()
        opts.api_host = "https://evil.example.com"
        ctx = _FakeContext({"api_host": ParameterSource.COMMANDLINE})
        _guard_untrusted_endpoints(ctx, opts, (), ())

    def test_effective_host_differs_from_relative_is_not_enforced(
        self, tmp_path, monkeypatch
    ):
        _write_cwd_config(
            tmp_path, monkeypatch, "[default]\napi_host = https://evil.example.com\n"
        )
        opts = Options()
        opts.api_host = "https://my.dedicated.example.com"  # overridden by home config
        _guard_untrusted_endpoints(_FakeContext({}), opts, (), ())

    def test_extra_suffix_allows_untrusted_host(self, tmp_path, monkeypatch):
        _write_cwd_config(
            tmp_path,
            monkeypatch,
            "[default]\napi_host = https://api.internal.example\n",
        )
        opts = Options()
        opts.api_host = "https://api.internal.example"
        _guard_untrusted_endpoints(_FakeContext({}), opts, ("internal.example",), ())

    def test_untrusted_proxy_without_allowed_suffix_raises(self, tmp_path, monkeypatch):
        _write_cwd_config(
            tmp_path,
            monkeypatch,
            "[default]\napi_proxy = http://attacker.example.com:3128\n",
        )
        opts = Options()
        opts.api_proxy = "http://attacker.example.com:3128"
        with pytest.raises(click.UsageError):
            _guard_untrusted_endpoints(_FakeContext({}), opts, (), ())

    def test_untrusted_proxy_with_allowed_suffix_passes(self, tmp_path, monkeypatch):
        _write_cwd_config(
            tmp_path,
            monkeypatch,
            "[default]\napi_proxy = http://proxy.internal.example:3128\n",
        )
        opts = Options()
        opts.api_proxy = "http://proxy.internal.example:3128"
        _guard_untrusted_endpoints(_FakeContext({}), opts, (), ("internal.example",))

    def test_trusted_proxy_source_bypasses(self, tmp_path, monkeypatch):
        _write_cwd_config(
            tmp_path,
            monkeypatch,
            "[default]\napi_proxy = http://attacker.example.com:3128\n",
        )
        opts = Options()
        opts.api_proxy = "http://corp.example.com:3128"  # from env, differs
        ctx = _FakeContext({"api_proxy": ParameterSource.ENVIRONMENT})
        _guard_untrusted_endpoints(ctx, opts, (), ())
