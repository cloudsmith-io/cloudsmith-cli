# Copyright 2026 Cloudsmith Ltd
"""Tests for the built-in default domain table and its config override."""

import pytest

from ....credential_helpers.backends import BackendKind
from ....credential_helpers.default_domains import (
    BUILTIN_DOMAINS,
    CDN_HOST,
    DefaultDomain,
    builtin_host,
    load_default_domains,
    untrusted_config_declares_domains,
)


def _by_host(domains):
    """Index a list of DefaultDomain records by host."""
    return {domain.host: domain for domain in domains}


def test_builtin_table_has_expected_size():
    """The built-in table is a fixed, reviewed list."""
    assert len(BUILTIN_DOMAINS) == 21


def test_builtin_table_is_io_only():
    """Only .io hosts ship; .com mirrors and media/web hosts are excluded."""
    for domain in BUILTIN_DOMAINS:
        assert domain.host.endswith(".cloudsmith.io"), domain.host


def test_builtin_table_excludes_prd_and_api_hosts():
    """Internal -prd variants and the API endpoint are not package hosts."""
    hosts = {domain.host for domain in BUILTIN_DOMAINS}
    for host in hosts:
        assert "-prd" not in host
        assert not host.startswith("api.")
        assert not host.startswith("api-")


@pytest.mark.parametrize(
    "host,label,kind",
    [
        ("python.cloudsmith.io", "python", BackendKind.PYTHON),
        ("docker.cloudsmith.io", "docker", BackendKind.DOCKER),
        ("maven.cloudsmith.io", "maven", BackendKind.MAVEN),
        ("golang.cloudsmith.io", "go", BackendKind.GO),
        ("helm.oci.cloudsmith.io", "helm", BackendKind.HELM),
        # Serve every format, so no single BackendKind applies.
        ("dl.cloudsmith.io", "-", None),
        ("upload.cloudsmith.io", "-", None),
        ("nix.cloudsmith.io", "nix", BackendKind.NIX),
    ],
)
def test_builtin_entries_map_to_expected_kinds(host, label, kind):
    """Each built-in host carries the right label and backend kind."""
    domain = _by_host(BUILTIN_DOMAINS)[host]

    assert domain.format_label == label
    assert domain.backend_kind == kind


def test_load_returns_builtins_when_no_config(tmp_path):
    """With no config file present, the built-in table is used."""
    assert load_default_domains(config_path=tmp_path / "absent.ini") == list(
        BUILTIN_DOMAINS
    )


def test_config_section_replaces_builtins_wholesale(tmp_path):
    """A [domains] section replaces the built-in table entirely."""
    config = tmp_path / "config.ini"
    config.write_text(
        "[domains]\n"
        "packages.internal.example.com = python\n"
        "cdn.internal.example.com =\n",
        encoding="utf-8",
    )

    domains = load_default_domains(config_path=config)

    assert len(domains) == 2
    indexed = _by_host(domains)
    assert indexed["packages.internal.example.com"].backend_kind == (BackendKind.PYTHON)
    assert indexed["packages.internal.example.com"].format_label == "python"
    # An empty value means "no single format".
    assert indexed["cdn.internal.example.com"].backend_kind is None
    assert indexed["cdn.internal.example.com"].format_label == "-"


def test_config_label_without_backend_kind_is_preserved(tmp_path):
    """A label with no matching BackendKind keeps the label, with a None kind."""
    config = tmp_path / "config.ini"
    config.write_text(
        "[domains]\nwidget.internal.example.com = widget\n", encoding="utf-8"
    )

    domain = _by_host(load_default_domains(config_path=config))[
        "widget.internal.example.com"
    ]

    assert domain.format_label == "widget"
    assert domain.backend_kind is None


def test_config_without_domains_section_falls_back_to_builtins(tmp_path):
    """A config file that has no [domains] section changes nothing."""
    config = tmp_path / "config.ini"
    config.write_text(
        "[default]\napi_host = https://api.cloudsmith.io\n", encoding="utf-8"
    )

    assert load_default_domains(config_path=config) == list(BUILTIN_DOMAINS)


def test_unreadable_config_falls_back_to_builtins(tmp_path):
    """A malformed config must not break the command."""
    config = tmp_path / "config.ini"
    config.write_text("this is not valid ini [[[", encoding="utf-8")

    assert load_default_domains(config_path=config) == list(BUILTIN_DOMAINS)


def test_untrusted_cwd_config_is_not_honoured(tmp_path, monkeypatch):
    """A [domains] section in a cwd config.ini is ignored, and detectable.

    config.ini is searched in the working directory first, so a repository can
    ship one. Honouring it here would let a malicious repo declare its own host
    a Cloudsmith host and harvest a token.
    """
    monkeypatch.chdir(tmp_path)
    # Pin the trusted lookup to "nothing found" so the developer's real
    # config.ini cannot influence what this test observes.
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.default_domains._trusted_config_path",
        lambda: None,
    )
    (tmp_path / "config.ini").write_text(
        "[domains]\nevil.example.com = python\n", encoding="utf-8"
    )

    domains = load_default_domains()

    assert all(domain.host != "evil.example.com" for domain in domains)
    assert untrusted_config_declares_domains() is True


def test_untrusted_config_predicate_false_without_section(tmp_path, monkeypatch):
    """No [domains] section in the cwd config means nothing to warn about."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.ini").write_text("[default]\n", encoding="utf-8")

    assert untrusted_config_declares_domains() is False


def test_cdn_host_is_in_builtin_table():
    """The exported CDN host constant and the table stay in sync."""
    assert CDN_HOST == "dl.cloudsmith.io"
    assert any(domain.host == CDN_HOST for domain in BUILTIN_DOMAINS)


def test_builtin_host_resolves_backend_kind():
    """builtin_host maps a backend kind to its built-in service host."""
    assert builtin_host(BackendKind.MAVEN) == "maven.cloudsmith.io"
    assert builtin_host(BackendKind.PYTHON) == "python.cloudsmith.io"


def test_builtin_host_rejects_kind_without_dedicated_host():
    """Formats served only via the CDN have no dedicated built-in host."""
    with pytest.raises(ValueError):
        builtin_host(BackendKind.DEB)


def test_default_domain_is_frozen():
    """Records are immutable so callers cannot mutate the shared table."""
    domain = DefaultDomain(
        host="a.cloudsmith.io", format_label="python", backend_kind=3
    )

    with pytest.raises(Exception):
        domain.host = "b.cloudsmith.io"
