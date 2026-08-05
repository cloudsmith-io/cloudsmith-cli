# Copyright 2026 Cloudsmith Ltd
"""Tests for the built-in default domain table and its config override."""

import pytest

from ....cli import config as cli_config
from ....credential_helpers.backends import BackendKind
from ....credential_helpers.default_domains import (
    BUILTIN_DOMAINS,
    DefaultDomain,
    DomainType,
    load_default_domains,
    untrusted_config_declares_domains,
)


def _by_host(domains):
    """Index a list of DefaultDomain records by host."""
    return {domain.host: domain for domain in domains}


@pytest.fixture
def no_trusted_config(tmp_path, monkeypatch):
    """Pin the trusted search path at an empty directory.

    ``load_default_domains`` falls back to the trusted lookup, so without this
    the developer's own ``config.ini`` decides what these tests observe.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(cli_config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(cli_config.ConfigReader, "config_searchpath", [str(empty)])


@pytest.mark.parametrize(
    "host,label,kind",
    [
        ("python.cloudsmith.io", "python", BackendKind.PYTHON),
        ("docker.cloudsmith.io", "docker", BackendKind.DOCKER),
        ("golang.cloudsmith.io", "go", BackendKind.GO),
        ("dl.cloudsmith.io", None, None),
        ("upload.cloudsmith.io", None, None),
    ],
)
def test_builtin_entries_map_to_expected_kinds(host, label, kind):
    """Each built-in host carries the right label and backend kind."""
    assert len(BUILTIN_DOMAINS) == 21

    domain = _by_host(BUILTIN_DOMAINS)[host]
    assert domain.format_label == label
    assert domain.backend_kind == kind


@pytest.mark.parametrize("exists", [False, True], ids=["absent", "no-domains-section"])
def test_a_config_declaring_no_table_falls_back_to_builtins(
    tmp_path, no_trusted_config, exists
):
    """Only a readable [domains] section replaces the built-in table."""
    config = tmp_path / "config.ini"
    if exists:
        config.write_text(
            "[default]\napi_host = https://api.cloudsmith.io\n", encoding="utf-8"
        )

    assert load_default_domains(config_path=config) == list(BUILTIN_DOMAINS)


def test_config_section_replaces_builtins_wholesale(tmp_path, no_trusted_config):
    """A [domains] section replaces the built-in table entirely."""
    config = tmp_path / "config.ini"
    config.write_text(
        "[domains]\n"
        "packages.internal.example.com = python\n"
        "cdn.internal.example.com = download\n",
        encoding="utf-8",
    )

    domains = load_default_domains(config_path=config)

    assert len(domains) == 2
    indexed = _by_host(domains)
    assert indexed["packages.internal.example.com"].backend_kind == BackendKind.PYTHON
    assert indexed["packages.internal.example.com"].domain_type is DomainType.NATIVE_API
    assert indexed["cdn.internal.example.com"].format_label is None
    assert indexed["cdn.internal.example.com"].domain_type is DomainType.DOWNLOAD


@pytest.mark.parametrize(
    "label,domain_type",
    [("download", DomainType.DOWNLOAD), ("upload", DomainType.UPLOAD)],
)
def test_config_reserved_labels_declare_formatless_hosts(
    tmp_path, no_trusted_config, label, domain_type
):
    """`download` and `upload` name the two hosts no package format names.

    A dedicated deployment has to redirect its upload endpoint, and no
    BackendKind identifies it - without a reserved label the table cannot name
    it at all.
    """
    config = tmp_path / "config.ini"
    config.write_text(
        f"[domains]\nhost.internal.example.com = {label}\n", encoding="utf-8"
    )

    domain = _by_host(load_default_domains(config_path=config))[
        "host.internal.example.com"
    ]

    assert domain.domain_type is domain_type
    assert domain.backend_kind is None


@pytest.mark.parametrize("label", ["", "widget"], ids=["empty", "unrecognised"])
def test_an_entry_naming_no_format_is_skipped(tmp_path, no_trusted_config, label):
    """A label is required, and a bad one is dropped rather than guessed at.

    Reading it as the download CDN would leave a typo'd format quietly serving
    the wrong thing, which is far harder to spot than a missing host.
    """
    config = tmp_path / "config.ini"
    config.write_text(
        f"[domains]\npackages.internal.example.com = python\n"
        f"broken.internal.example.com = {label}\n",
        encoding="utf-8",
    )

    hosts = _by_host(load_default_domains(config_path=config))

    assert set(hosts) == {"packages.internal.example.com"}


def test_a_config_that_is_not_utf8_falls_back_to_builtins(tmp_path, no_trusted_config):
    """An undecodable config.ini falls back rather than aborting the command."""
    config = tmp_path / "config.ini"
    config.write_bytes(b"[domains]\nmaven.acme.example.com = maven\n# \xe9\xe8\xf1\n")

    assert load_default_domains(config_path=config) == list(BUILTIN_DOMAINS)


def test_trusted_lookup_skips_a_config_without_a_domains_section(tmp_path, monkeypatch):
    """The table comes from the first trusted config that declares one.

    Existence is not enough: an app-dir config.ini holding only [default] api
    settings would otherwise mask the deployment's [domains] override and
    silently restore the public *.cloudsmith.io table.
    """
    without_domains = tmp_path / "app-dir"
    with_domains = tmp_path / "home-dir"
    without_domains.mkdir()
    with_domains.mkdir()
    (without_domains / "config.ini").write_text(
        "[default]\napi_host = https://api.internal.example.com\n", encoding="utf-8"
    )
    (with_domains / "config.ini").write_text(
        "[domains]\ncdn.internal.example.com = download\n", encoding="utf-8"
    )
    monkeypatch.setattr(cli_config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(
        cli_config.ConfigReader,
        "config_searchpath",
        [str(without_domains), str(with_domains)],
    )

    assert load_default_domains() == [
        DefaultDomain("cdn.internal.example.com", None, DomainType.DOWNLOAD)
    ]


def test_untrusted_cwd_config_is_not_honoured(tmp_path, monkeypatch):
    """A [domains] section in a cwd config.ini is ignored, and detectable.

    config.ini is searched in the working directory first, so a repository can
    ship one. Honouring it here would let a malicious repo declare its own host
    a Cloudsmith host and harvest a token.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.default_domains._trusted_domains",
        lambda: None,
    )
    (tmp_path / "config.ini").write_text(
        "[domains]\nevil.example.com = python\n", encoding="utf-8"
    )

    domains = load_default_domains()

    assert all(domain.host != "evil.example.com" for domain in domains)
    assert untrusted_config_declares_domains() is True
