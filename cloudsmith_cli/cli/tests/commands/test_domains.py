# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith domains list` command."""

import json
from unittest.mock import patch

import pytest

from ....cli import config as cli_config
from ....cli.commands.domains import list_domains
from ....core.api.exceptions import ApiException
from ....credential_helpers.backends import BackendKind
from ....credential_helpers.custom_domains import (
    CustomDomain,
    get_cache_path,
    write_cache,
)
from ....credential_helpers.default_domains import DomainType

_PATCH_TARGET = "cloudsmith_cli.cli.commands.domains.get_custom_domains"

HERMETIC_ARGS = ["--api-key", "fake-api-key"]


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch, tmp_path):
    """Keep the developer's real environment out of these tests.

    An inherited organisation, config file, [domains] table or custom-domain
    cache would each replace part of what these tests assert on - and the CLI's
    Options object and ConfigReader's search path are both process-wide, so
    they are pinned per test rather than merely cleared.
    """
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delenv("CLOUDSMITH_CONFIG_FILE", raising=False)
    monkeypatch.delattr(cli_config.OPTIONS, "value", raising=False)
    monkeypatch.setattr(cli_config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(cli_config.ConfigReader, "config_searchpath", ["."])
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.custom_domains.get_default_config_path",
        lambda: str(tmp_path),
    )


def _domain(
    host,
    backend_kind,
    org="acme",
    repository=None,
    created_at=None,
    domain_type=None,
    enabled=True,
    validated=True,
    primary=True,
):
    """Build a CustomDomain record for a test.

    The server classifies every domain, so a record stands in for one it sent:
    a host serving a package format speaks that format's protocol, and the
    format-less ones default to the CDN unless the caller says otherwise.
    """
    if domain_type is None:
        domain_type = (
            DomainType.NATIVE_API if backend_kind is not None else DomainType.DOWNLOAD
        )
    return CustomDomain(
        host=host,
        backend_kind=backend_kind,
        enabled=enabled,
        validated=validated,
        org=org,
        repository=repository,
        domain_type=domain_type,
        created_at=created_at,
        primary=primary,
    )


def _invoke(runner, *args, custom_domains=()):
    """Run the command with the custom-domain lookup stubbed; assert a clean exit.

    Returns (result, mock_get) so a caller can read stderr or assert on how the
    lookup was called.
    """
    with patch(_PATCH_TARGET, return_value=list(custom_domains)) as mock_get:
        result = runner.invoke(
            list_domains, [*args, *HERMETIC_ARGS], catch_exceptions=False
        )

    assert result.exit_code == 0, result.output
    return result, mock_get


def _by_host(result):
    """Index the emitted domains document by host."""
    return {entry["host"]: entry for entry in json.loads(result.stdout)["domains"]}


def test_document_has_one_schema_for_both_kinds_of_host(runner, monkeypatch):
    """Built-in and custom hosts share one entry schema, under a versioned document.

    A key present on custom entries alone raises KeyError on the first built-in
    host for any consumer filtering the document on it.
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    result, _ = _invoke(
        runner,
        custom_domains=[
            _domain("pypi.acme.example.com", 3, created_at="2026-02-06T00:00:00Z")
        ],
    )

    document = json.loads(result.stdout)
    assert set(document) == {"version", "domains"}
    assert document["version"] == 1
    assert len({frozenset(entry) for entry in document["domains"]}) == 1

    by_host = _by_host(result)
    assert by_host["pypi.acme.example.com"] == {
        "host": "pypi.acme.example.com",
        "format": "python",
        "type": "custom",
        "domain_type": "native_api",
        "workspace": "acme",
        "org": "acme",
        "repository": None,
        "primary": True,
        "created_at": "2026-02-06T00:00:00Z",
    }
    assert by_host["python.cloudsmith.io"] == {
        "host": "python.cloudsmith.io",
        "format": "python",
        "type": "default",
        "domain_type": "native_api",
        "workspace": None,
        "org": None,
        "repository": None,
        "primary": True,
        "created_at": None,
    }


@pytest.mark.parametrize(
    "host,format_,domain_type",
    [
        ("dl.cloudsmith.io", None, "download"),
        ("upload.cloudsmith.io", None, "upload"),
        ("maven.cloudsmith.io", "maven", "native_api"),
    ],
)
def test_builtin_hosts_say_what_they_serve(runner, host, format_, domain_type):
    """The two format-less hosts are download/upload; the rest are native API."""
    entry = _by_host(_invoke(runner)[0])[host]

    assert entry["format"] == format_
    assert entry["domain_type"] == domain_type


@pytest.mark.parametrize("source", ["env", "config", "flag"])
def test_the_resolved_organisation_is_looked_up(runner, monkeypatch, tmp_path, source):
    """However the organisation is configured, that is the one looked up.

    The accepted spellings of the option are covered in test_org_option.py; this
    only proves the command hands what it resolved to the lookup.
    """
    args = []
    if source == "env":
        monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    elif source == "config":
        config = tmp_path / "config.ini"
        config.write_text("[default]\norg = acme\n", encoding="utf-8")
        args = ["--config-file", str(config)]
    else:
        args = ["--org", "acme"]

    _, mock_get = _invoke(runner, *args)

    assert mock_get.call_args.args[0] == "acme"


def test_without_org_no_custom_domain_lookup(runner):
    """With no organisation configured, no custom-domain lookup is attempted."""
    _, mock_get = _invoke(runner)

    mock_get.assert_not_called()


def test_lookup_is_handed_the_commands_own_settings(runner, monkeypatch):
    """The lookup runs on the command's terms, not its own defaults.

    ``strict`` so a typo'd org or unreachable API cannot render as "no custom
    domains"; ``configure_api=False`` because `initialise_api` has already
    applied the proxy, TLS, user-agent and header settings that a narrower
    re-initialisation inside the lookup would discard; the resolved credential
    and ``--refresh`` because neither reaches the lookup any other way.
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    _, mock_get = _invoke(runner, "--refresh")

    kwargs = mock_get.call_args.kwargs
    assert kwargs["strict"] is True
    assert kwargs["configure_api"] is False
    assert kwargs["refresh"] is True
    assert kwargs["credential"].api_key == "fake-api-key"


def test_lookup_failure_says_what_went_wrong(runner, monkeypatch):
    """A failed lookup exits non-zero naming the cause, with no partial document.

    ApiException builds Exception with no args, so interpolating one used to
    yield a message that stopped dead at the colon.
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    with patch(_PATCH_TARGET, side_effect=ApiException(401, detail="Invalid API key")):
        result = runner.invoke(list_domains, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code != 0
    assert result.stdout.strip() == ""
    assert "Failed to fetch custom domains" in result.stderr
    assert "401" in result.stderr
    assert "Invalid API key" in result.stderr


def test_explicit_config_file_supplies_default_domains(runner, tmp_path):
    """An explicit --config-file is a trusted source for [domains]."""
    config = tmp_path / "config.ini"
    config.write_text(
        "[domains]\nindex.internal.example.com = python\n", encoding="utf-8"
    )

    result, _ = _invoke(runner, "--config-file", str(config))

    assert set(_by_host(result)) == {"index.internal.example.com"}


def test_untrusted_config_section_is_ignored_with_a_warning(
    runner, monkeypatch, tmp_path
):
    """A cwd config.ini cannot replace the host table, and says so on stderr.

    That file travels with whatever repository is checked out, and this table
    decides which hosts may receive a credential.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.ini").write_text(
        "[domains]\nindex.internal.example.com = python\n", encoding="utf-8"
    )

    result, _ = _invoke(runner)

    assert "Warning" in result.stderr
    assert "python.cloudsmith.io" in _by_host(result)
    assert "index.internal.example.com" not in _by_host(result)


def test_lists_cached_domains_when_no_organisation_is_configured(
    runner, monkeypatch, tmp_path
):
    """A run with no org lists what earlier runs cached, without any API call.

    Attribution comes from the record, not the filename: the cache filename is
    a sanitised slug and cannot be relied on.
    """
    called = []
    monkeypatch.setattr(_PATCH_TARGET, lambda *a, **k: called.append("api") or [])
    write_cache(get_cache_path("acme"), [_domain("dl.acme.com", None, org="acme")])
    write_cache(
        get_cache_path("widgets"), [_domain("dl.widgets.com", None, org="widgets")]
    )

    result = runner.invoke(list_domains, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert not called
    custom = [d for d in json.loads(result.output)["domains"] if d["type"] == "custom"]
    assert {(d["host"], d["org"]) for d in custom} == {
        ("dl.acme.com", "acme"),
        ("dl.widgets.com", "widgets"),
    }


def test_format_filter_keeps_that_format_and_the_formatless_hosts(runner, monkeypatch):
    """--format answers "what can I use for this format?".

    A formatless host (the download CDN, the generic upload endpoint) serves
    every format, so excluding it would hide the very host Maven resolves
    dependencies from.
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain("mvn.acme.example.com", int(BackendKind.MAVEN)),
        _domain("pypi.acme.example.com", int(BackendKind.PYTHON)),
        _domain("dl.acme.example.com", None),
    ]

    by_host = _by_host(_invoke(runner, "--format", "maven", custom_domains=records)[0])

    assert "mvn.acme.example.com" in by_host
    assert "dl.acme.example.com" in by_host
    assert "pypi.acme.example.com" not in by_host
    # Built-ins are filtered on the same rule.
    assert "maven.cloudsmith.io" in by_host
    assert "python.cloudsmith.io" not in by_host
    assert "dl.cloudsmith.io" in by_host


def test_custom_domains_are_listed_before_the_builtin_hosts(runner, monkeypatch):
    """An organisation's own hosts come first; the built-ins are the fallback.

    A caller reading the document top-down should reach the host bound to its
    organisation before the public one that merely also works.
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    result, _ = _invoke(runner, custom_domains=[_domain("dl.acme.example.com", None)])

    types = [entry["type"] for entry in json.loads(result.stdout)["domains"]]
    assert types == ["custom"] + ["default"] * (len(types) - 1)


def test_a_domain_that_cannot_serve_traffic_is_not_listed(runner, monkeypatch):
    """The listing answers what is usable, so a host serving nothing is out.

    It needs both flags: a domain is usable only when it is enabled *and*
    validated. Under ``--repo`` this also keeps a dead host off the top of the
    list, since one bound to the repository outranks an organisation-wide one
    whatever its state.
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain("dl.acme.example.com", None),
        _domain("disabled.acme.example.com", None, enabled=False),
        _domain("unvalidated.acme.example.com", None, validated=False),
    ]

    by_host = _by_host(_invoke(runner, custom_domains=records)[0])

    assert "dl.acme.example.com" in by_host
    assert "disabled.acme.example.com" not in by_host
    assert "unvalidated.acme.example.com" not in by_host


def test_domain_type_filter_selects_hosts_by_purpose(runner, monkeypatch):
    """--domain-type answers "which host do I upload to?".

    Unlike --format, every host has exactly one purpose, so this is an exact
    match: an upload endpoint cannot stand in for the download CDN, and a
    native-API host speaks one package format's protocol and neither.
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain("up.acme.example.com", None, domain_type=DomainType.UPLOAD),
        _domain("dl.acme.example.com", None, domain_type=DomainType.DOWNLOAD),
        _domain("mvn.acme.example.com", int(BackendKind.MAVEN)),
    ]

    by_host = _by_host(
        _invoke(runner, "--domain-type", "upload", custom_domains=records)[0]
    )

    assert set(by_host) == {"upload.cloudsmith.io", "up.acme.example.com"}


def test_repo_filter_drops_other_repositories_and_ranks_the_rest(runner, monkeypatch):
    """--repo lists the hosts usable for one repository, most-preferred first.

    A repository-scoped host names its own repository in its URLs, so it can
    never stand in for another; an organisation-wide one serves every
    repository but ranks behind the domain bound to this one. The first custom
    entry is what Cloudsmith would actually bind.
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain("dl.acme.example.com", None, created_at="2020-01-01T00:00:00Z"),
        _domain("dl-dev.acme.example.com", None, repository="dev"),
        _domain("dl-prod.acme.example.com", None, repository="prod"),
    ]

    result, _ = _invoke(runner, "--repo", "prod", custom_domains=records)

    document = json.loads(result.stdout)["domains"]
    customs = [entry["host"] for entry in document if entry["type"] == "custom"]
    assert customs == ["dl-prod.acme.example.com", "dl.acme.example.com"]
    # A built-in host serves every repository, so it survives the filter.
    assert "dl.cloudsmith.io" in {entry["host"] for entry in document}


def test_custom_domains_are_ranked_by_precedence_without_repo(runner, monkeypatch):
    """Precedence orders the custom entries whether or not --repo is given.

    The first custom entry is the host Cloudsmith would bind, so sorting by host
    without --repo would disagree with the credential path about which is active.
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain(
            "alpha.acme.example.com",
            BackendKind.DOCKER,
            created_at="2020-01-01T00:00:00Z",
            primary=False,
        ),
        _domain(
            "zeta.acme.example.com",
            BackendKind.DOCKER,
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    result, _ = _invoke(runner, "--format", "docker", custom_domains=records)

    customs = [
        entry["host"]
        for entry in json.loads(result.stdout)["domains"]
        if entry["type"] == "custom"
    ]
    assert customs == ["zeta.acme.example.com", "alpha.acme.example.com"]


def test_default_shows_everything_with_no_pagination_metadata(runner, monkeypatch):
    """With no --page/--page-size given, the command defaults to --page-all.

    The combined list is small and built from a local cache, unlike other
    `list` commands backed by a live paginated endpoint, so there is no
    upside to hiding entries by default.
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [_domain(f"h{i}.acme.example.com", None) for i in range(5)]

    result, _ = _invoke(runner, custom_domains=records)

    document = json.loads(result.stdout)
    assert "meta" not in document
    assert len([e for e in document["domains"] if e["type"] == "custom"]) == 5


def test_page_size_selects_a_page_and_reports_pagination_metadata(runner, monkeypatch):
    """Passing --page-size switches the command into paged output."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain(
            f"h{i}.acme.example.com", None, created_at=f"2020-01-{i + 1:02d}T00:00:00Z"
        )
        for i in range(5)
    ]

    unpaged, _ = _invoke(runner, custom_domains=records)
    total = len(json.loads(unpaged.stdout)["domains"])

    result, _ = _invoke(
        runner, "--page-size", "2", "--page", "1", custom_domains=records
    )

    document = json.loads(result.stdout)
    assert len(document["domains"]) == 2
    pagination = document["meta"]["pagination"]
    assert pagination["page"] == 1
    assert pagination["page_size"] == 2
    assert pagination["results_total"] == total
    assert pagination["page_max"] == -(-total // 2)


def test_second_page_continues_where_the_first_left_off(runner, monkeypatch):
    """Successive pages walk through the full list without gaps or overlap."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain(
            f"h{i}.acme.example.com", None, created_at=f"2020-01-{i + 1:02d}T00:00:00Z"
        )
        for i in range(5)
    ]

    page_one, _ = _invoke(
        runner, "--page-size", "2", "--page", "1", custom_domains=records
    )
    page_two, _ = _invoke(
        runner, "--page-size", "2", "--page", "2", custom_domains=records
    )

    hosts_one = [e["host"] for e in json.loads(page_one.stdout)["domains"]]
    hosts_two = [e["host"] for e in json.loads(page_two.stdout)["domains"]]
    assert not set(hosts_one) & set(hosts_two)
    assert json.loads(page_two.stdout)["meta"]["pagination"]["page"] == 2


def test_page_all_shows_everything_even_with_explicit_page_size(runner, monkeypatch):
    """--page-all still means "everything", overriding any --page-size given."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [_domain(f"h{i}.acme.example.com", None) for i in range(5)]

    result, _ = _invoke(runner, "--page-all", custom_domains=records)

    document = json.loads(result.stdout)
    assert "meta" not in document
    assert len([e for e in document["domains"] if e["type"] == "custom"]) == 5


def test_page_and_page_all_are_mutually_exclusive(runner, monkeypatch):
    """Explicit --page together with --page-all is rejected, as elsewhere in the CLI."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    with patch(_PATCH_TARGET, return_value=[]):
        result = runner.invoke(
            list_domains,
            ["--page", "2", "--page-all", *HERMETIC_ARGS],
            catch_exceptions=False,
        )

    assert result.exit_code != 0
    assert "--page-all" in result.output or "page-all" in result.output


def test_cached_domains_from_several_orgs_are_grouped_by_org(runner, tmp_path):
    """Cross-org cached records are never interleaved into one ranking.

    A no-org listing spans whatever earlier runs cached, and ranking one
    organisation's hosts against another's expresses a preference the server
    never made.
    """
    write_cache(
        get_cache_path("acme"),
        [_domain("mvn.acme.example.com", BackendKind.MAVEN, org="acme")],
    )
    write_cache(
        get_cache_path("bravo"),
        [
            _domain(
                "mvn.bravo.example.com",
                BackendKind.MAVEN,
                org="bravo",
                created_at="2001-01-01T00:00:00Z",
            )
        ],
    )

    result, _ = _invoke(runner, "--format", "maven")

    customs = [
        entry["host"]
        for entry in json.loads(result.stdout)["domains"]
        if entry["type"] == "custom"
    ]
    assert customs == ["mvn.acme.example.com", "mvn.bravo.example.com"]
