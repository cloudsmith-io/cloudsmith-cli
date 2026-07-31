# Copyright 2026 Cloudsmith Ltd
"""Tests for the built-in default domain table and its config override."""

import pytest

from ....cli import config as cli_config
from ....credential_helpers.backends import BackendKind
from ....credential_helpers.default_domains import (
    BUILTIN_DOMAINS,
    DefaultDomain,
    DomainType,
    builtin_host,
    builtin_host_for_type,
    domain_type_for_backend_kind,
    format_for_backend_kind,
    load_default_domains,
    untrusted_config_declares_domains,
)


def _by_host(domains):
    """Index a list of DefaultDomain records by host."""
    return {domain.host: domain for domain in domains}


def test_builtin_table_has_expected_size():
    """The built-in table is a fixed, reviewed list."""
    assert len(BUILTIN_DOMAINS) == 21


@pytest.mark.parametrize(
    "host,label,kind",
    [
        ("python.cloudsmith.io", "python", BackendKind.PYTHON),
        ("docker.cloudsmith.io", "docker", BackendKind.DOCKER),
        ("maven.cloudsmith.io", "maven", BackendKind.MAVEN),
        ("golang.cloudsmith.io", "go", BackendKind.GO),
        ("helm.oci.cloudsmith.io", "helm", BackendKind.HELM),
        ("dl.cloudsmith.io", None, None),
        ("upload.cloudsmith.io", None, None),
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
    assert indexed["cdn.internal.example.com"].format_label is None
    assert indexed["cdn.internal.example.com"].domain_type is DomainType.DOWNLOAD
    assert indexed["packages.internal.example.com"].domain_type is DomainType.NATIVE_API


def test_config_label_without_backend_kind_is_formatless(tmp_path):
    """A label with no matching BackendKind resolves to no format at all.

    A host without a backend kind serves no single format, so its label
    cannot name one - the entry degrades to a formatless download host.
    """
    config = tmp_path / "config.ini"
    config.write_text(
        "[domains]\nwidget.internal.example.com = widget\n", encoding="utf-8"
    )

    domain = _by_host(load_default_domains(config_path=config))[
        "widget.internal.example.com"
    ]

    assert domain.format_label is None
    assert domain.backend_kind is None
    assert domain.domain_type is DomainType.DOWNLOAD


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


def test_absolute_config_file_is_not_scanned_as_untrusted(tmp_path, monkeypatch):
    """An explicit --config-file is trusted, so it must not trip the warning.

    load_config prepends an explicit path to ConfigReader.config_files, and
    joining an absolute path onto a relative search directory yields the
    absolute path - so an unfiltered scan would read a trusted file and warn
    that it was ignored.
    """
    monkeypatch.chdir(tmp_path)
    trusted = tmp_path / "explicit.ini"
    trusted.write_text("[domains]\nindex.example.com = python\n", encoding="utf-8")
    monkeypatch.setattr(
        cli_config.ConfigReader, "config_files", [str(trusted), "config.ini"]
    )
    monkeypatch.setattr(cli_config.ConfigReader, "config_searchpath", ["."])

    assert untrusted_config_declares_domains() is False


@pytest.mark.parametrize(
    "host,domain_type",
    [
        ("dl.cloudsmith.io", DomainType.DOWNLOAD),
        ("upload.cloudsmith.io", DomainType.UPLOAD),
        ("maven.cloudsmith.io", DomainType.NATIVE_API),
    ],
)
def test_builtin_entries_carry_their_domain_type(host, domain_type):
    """The two format-less hosts are download/upload; the rest are native API."""
    assert _by_host(BUILTIN_DOMAINS)[host].domain_type is domain_type


@pytest.mark.parametrize("domain_type", [DomainType.DOWNLOAD, DomainType.UPLOAD])
def test_backend_kind_requires_native_api_domain_type(domain_type):
    """A backend kind is only possible on a NATIVE_API host.

    A host with a backend kind speaks that format's native protocol, so a
    download or upload row carrying one is a contradiction and must not be
    constructible.
    """
    with pytest.raises(ValueError):
        DefaultDomain(
            host="maven.example.com",
            backend_kind=BackendKind.MAVEN,
            domain_type=domain_type,
        )


@pytest.mark.parametrize(
    "backend_kind,expected",
    [
        (BackendKind.PYTHON, "python"),
        (BackendKind.MAVEN, "maven"),
        (BackendKind.GO, "go"),
        (None, None),
        (9999, "unknown"),
    ],
)
def test_format_for_backend_kind(backend_kind, expected):
    """A kind resolves to its lowercased format name, with safe fallbacks."""
    assert format_for_backend_kind(backend_kind) == expected


def test_builtin_domains_with_a_backend_kind_are_native_api():
    """A host that serves one format is a native-API host, and vice versa.

    Guards the table against a new row whose declared type contradicts its
    backend kind - the default is NATIVE_API, so a format-less host added
    without an explicit type would otherwise be mistyped silently.
    """
    for domain in BUILTIN_DOMAINS:
        if domain.backend_kind is None:
            assert domain.domain_type is not DomainType.NATIVE_API, domain.host
        else:
            assert domain.domain_type is DomainType.NATIVE_API, domain.host


def test_builtin_host_for_type_resolves_download_and_upload():
    """The download/upload hosts are looked up by type, not by constant."""
    assert builtin_host_for_type(DomainType.DOWNLOAD) == "dl.cloudsmith.io"
    assert builtin_host_for_type(DomainType.UPLOAD) == "upload.cloudsmith.io"


def test_builtin_host_for_type_rejects_ambiguous_native_api():
    """NATIVE_API covers many hosts, so there is no single one to return."""
    with pytest.raises(ValueError):
        builtin_host_for_type(DomainType.NATIVE_API)


@pytest.mark.parametrize(
    "backend_kind,expected",
    [
        (BackendKind.MAVEN, DomainType.NATIVE_API),
        # DEB is 0 and therefore falsy: a truthiness check here would
        # misclassify it as a download host.
        (BackendKind.DEB, DomainType.NATIVE_API),
        (None, DomainType.DOWNLOAD),
    ],
)
def test_domain_type_for_backend_kind(backend_kind, expected):
    """A kind implies native API; its absence implies a download host."""
    assert domain_type_for_backend_kind(backend_kind) is expected


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
    domain = DefaultDomain(host="a.cloudsmith.io", backend_kind=BackendKind.PYTHON)

    with pytest.raises(Exception):
        domain.host = "b.cloudsmith.io"
