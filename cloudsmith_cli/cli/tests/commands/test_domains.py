# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith domains list` command."""

import json
from unittest.mock import patch

import pytest

from ....cli import config as cli_config
from ....cli.commands.domains import list_domains
from ....core import keyring as core_keyring
from ....core.api.exceptions import ApiException
from ....credential_helpers.domains import (
    domain_from_payload,
    get_cache_path,
    write_cache,
)

_PATCH_TARGET = "cloudsmith_cli.cli.commands.domains.get_workspace_domains"
_ORGS_PATCH_TARGET = "cloudsmith_cli.cli.commands.domains.list_orgs"

HERMETIC_ARGS = ["--api-key", "fake-api-key"]


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch, tmp_path):
    """Keep the developer's real environment out of these tests.

    An inherited Workspace, config file or domain cache would each replace part
    of what these tests assert on - and the CLI's Options object and
    ConfigReader's search path are both process-wide, so they are pinned per
    test rather than merely cleared.
    """
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delenv("CLOUDSMITH_WORKSPACE", raising=False)
    monkeypatch.delenv("CLOUDSMITH_API_HOST", raising=False)
    monkeypatch.delenv("CLOUDSMITH_CONFIG_FILE", raising=False)
    monkeypatch.delenv("CLOUDSMITH_API_KEY", raising=False)
    core_keyring.configure(core_keyring.KeyringSettings(no_keyring=True))
    monkeypatch.delattr(cli_config.OPTIONS, "value", raising=False)
    monkeypatch.setattr(cli_config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(cli_config.ConfigReader, "config_searchpath", ["."])
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.domains.get_default_config_path",
        lambda: str(tmp_path),
    )


def _payload(name, domain_type, scope="WORKSPACE", repository=None):
    return {
        "domain_name": name,
        "domain_type": domain_type,
        "domain_scope": scope,
        "repository": repository,
    }


def _domain(name, domain_type, scope="WORKSPACE", repository=None, workspace="acme"):
    """Build a record as the server would send it for *workspace*."""
    return domain_from_payload(
        _payload(name, domain_type, scope, repository), workspace
    )


SERVER_DOMAINS = [
    _domain("dl-prod.acme.example.com", "DOWNLOAD", "REPOSITORY", "prod"),
    _domain("dl-dev.acme.example.com", "DOWNLOAD", "REPOSITORY", "dev"),
    _domain("pypi.acme.example.com", "NATIVE_PYTHON"),
    _domain("dl.acme.example.com", "DOWNLOAD"),
    _domain("dl.cloudsmith.io", "DOWNLOAD", "GLOBAL"),
    _domain("upload.cloudsmith.io", "UPLOAD", "GLOBAL"),
    _domain("api.cloudsmith.io", "CLOUDSMITH_API", "GLOBAL"),
    _domain("maven.cloudsmith.io", "NATIVE_MAVEN", "GLOBAL"),
    _domain("python.cloudsmith.io", "NATIVE_PYTHON", "GLOBAL"),
]


def _invoke(runner, *args, domains=SERVER_DOMAINS):
    """Run the command with the domain lookup stubbed; assert a clean exit.

    Returns (result, mock_get) so a caller can read stderr or assert on how the
    lookup was called.
    """
    with patch(_PATCH_TARGET, return_value=list(domains)) as mock_get:
        result = runner.invoke(
            list_domains, [*args, *HERMETIC_ARGS], catch_exceptions=False
        )

    assert result.exit_code == 0, result.output
    return result, mock_get


def _hosts(result):
    return [entry["host"] for entry in json.loads(result.stdout)["domains"]]


def _by_host(result):
    """Index the emitted domains document by host."""
    return {entry["host"]: entry for entry in json.loads(result.stdout)["domains"]}


def test_document_has_one_schema_for_both_kinds_of_host(runner, monkeypatch):
    """Cloudsmith-owned and custom hosts share one entry schema.

    A key present on custom entries alone raises KeyError on the first
    Cloudsmith-owned host for any consumer filtering the document on it.
    """
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    result, _ = _invoke(runner)

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
        "primary": None,
        "created_at": None,
    }
    assert by_host["python.cloudsmith.io"] == {
        "host": "python.cloudsmith.io",
        "format": "python",
        "type": "default",
        "domain_type": "native_api",
        "workspace": None,
        "org": None,
        "repository": None,
        "primary": None,
        "created_at": None,
    }


@pytest.mark.parametrize(
    "host,format_,domain_type",
    [
        ("dl.cloudsmith.io", None, "download"),
        ("upload.cloudsmith.io", None, "upload"),
        ("api.cloudsmith.io", None, "cloudsmith_api"),
        ("maven.cloudsmith.io", "maven", "native_api"),
    ],
)
def test_hosts_say_what_they_serve(runner, monkeypatch, host, format_, domain_type):
    """Each host carries the purpose the server gave it."""
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    entry = _by_host(_invoke(runner)[0])[host]

    assert entry["format"] == format_
    assert entry["domain_type"] == domain_type


@pytest.mark.parametrize("source", ["env", "config", "flag"])
def test_the_resolved_workspace_is_looked_up(runner, monkeypatch, tmp_path, source):
    """However the Workspace is configured, that is the one looked up.

    The accepted spellings of the option are covered in test_org_option.py; this
    only proves the command hands what it resolved to the lookup.
    """
    args = []
    if source == "env":
        monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")
    elif source == "config":
        config = tmp_path / "config.ini"
        config.write_text("[default]\nworkspace = acme\n", encoding="utf-8")
        args = ["--config-file", str(config)]
    else:
        args = ["--workspace", "acme"]

    _, mock_get = _invoke(runner, *args)

    assert mock_get.call_args.args[0] == "acme"


def test_without_workspace_or_credential_no_lookup(runner):
    """With no Workspace and no credential there is nothing to ask the API."""
    with patch(_PATCH_TARGET) as mock_get, patch(_ORGS_PATCH_TARGET) as mock_orgs:
        result = runner.invoke(list_domains, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    mock_get.assert_not_called()
    mock_orgs.assert_not_called()
    assert json.loads(result.stdout) == {"version": 1, "domains": []}


def test_without_workspace_a_member_workspace_supplies_the_domains(runner):
    """With nothing cached, any Workspace of the credential lists the hosts.

    Every Workspace answer holds the Cloudsmith-owned hosts, so consumers that
    set no Workspace still get them.
    """
    with patch(_ORGS_PATCH_TARGET, return_value=[{"slug": "acme"}]) as mock_orgs:
        result, mock_get = _invoke(runner)

    mock_orgs.assert_called_once_with(page=1, page_size=1)
    assert mock_get.call_args.args[0] == "acme"
    assert mock_get.call_args.kwargs["strict"] is True
    assert result.stderr == ""
    assert _hosts(result) == [domain.host for domain in SERVER_DOMAINS]


def test_without_workspace_a_credential_with_no_workspace_lists_nothing(runner):
    """A credential that is a member of no Workspace has no domains to list."""
    with patch(_ORGS_PATCH_TARGET, return_value=[]):
        result, mock_get = _invoke(runner)

    mock_get.assert_not_called()
    assert _hosts(result) == []


def test_without_workspace_a_failed_member_lookup_exits_non_zero(runner):
    """A failed lookup is not shown as "no domains"."""
    with patch(
        _ORGS_PATCH_TARGET, side_effect=ApiException(401, detail="Invalid API key")
    ):
        result = runner.invoke(list_domains, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code != 0
    assert result.stdout.strip() == ""
    assert "Invalid API key" in result.stderr


def test_refresh_without_workspace_warns_that_the_cache_is_unchanged(runner):
    """--refresh needs a Workspace to fetch from."""
    write_cache(
        get_cache_path("acme"),
        "acme",
        [_payload("dl.cloudsmith.io", "DOWNLOAD", "GLOBAL")],
    )

    result, mock_get = _invoke(runner, "--refresh")

    mock_get.assert_not_called()
    assert "--refresh needs a Workspace" in result.stderr
    assert _hosts(result) == ["dl.cloudsmith.io"]


def test_lookup_is_handed_the_commands_own_settings(runner, monkeypatch):
    """The lookup runs on the command's terms, not its own defaults.

    ``strict`` so a typo'd Workspace or unreachable API cannot render as "no
    domains"; ``configure_api=False`` because `initialise_api` has already
    applied the proxy, TLS, user-agent and header settings that a narrower
    re-initialisation inside the lookup would discard; the resolved credential,
    API host and ``--refresh`` because none reaches the lookup any other way.
    """
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")
    monkeypatch.setenv("CLOUDSMITH_API_HOST", "https://api.example.com")

    _, mock_get = _invoke(runner, "--refresh")

    kwargs = mock_get.call_args.kwargs
    assert kwargs["strict"] is True
    assert kwargs["configure_api"] is False
    assert kwargs["refresh"] is True
    assert kwargs["api_host"] == "https://api.example.com"
    assert kwargs["credential"].api_key == "fake-api-key"


def test_lookup_failure_says_what_went_wrong(runner, monkeypatch):
    """A failed lookup exits non-zero naming the cause, with no partial document.

    ApiException builds Exception with no args, so interpolating one used to
    yield a message that stopped dead at the colon.
    """
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    with patch(_PATCH_TARGET, side_effect=ApiException(401, detail="Invalid API key")):
        result = runner.invoke(list_domains, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code != 0
    assert result.stdout.strip() == ""
    assert "Failed to fetch domains" in result.stderr
    assert "401" in result.stderr
    assert "Invalid API key" in result.stderr


def test_lists_cached_domains_when_no_workspace_is_configured(runner, monkeypatch):
    """A run with no Workspace lists what earlier runs cached, without any API call.

    Each Workspace's custom domains keep their attribution, and the
    Cloudsmith-owned hosts that every cached answer repeats are listed once.
    """
    called = []
    monkeypatch.setattr(_PATCH_TARGET, lambda *a, **k: called.append("api") or [])
    shared = _payload("dl.cloudsmith.io", "DOWNLOAD", "GLOBAL")
    write_cache(
        get_cache_path("widgets"),
        "widgets",
        [_payload("dl.widgets.com", "DOWNLOAD"), shared],
    )
    write_cache(
        get_cache_path("acme"), "acme", [_payload("dl.acme.com", "DOWNLOAD"), shared]
    )

    result = runner.invoke(list_domains, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert not called
    assert result.stderr == ""
    document = json.loads(result.stdout)["domains"]
    assert [(d["host"], d["workspace"]) for d in document] == [
        ("dl.acme.com", "acme"),
        ("dl.widgets.com", "widgets"),
        ("dl.cloudsmith.io", None),
    ]


def test_format_filter_keeps_that_format_and_the_formatless_hosts(runner, monkeypatch):
    """--format answers "what can I use for this format?".

    A formatless host (the download CDN, the generic upload endpoint) serves
    every format, so excluding it would hide the very host Maven resolves
    dependencies from.
    """
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    result, _ = _invoke(runner, "--format", "maven")

    assert _hosts(result) == [
        "dl-prod.acme.example.com",
        "dl-dev.acme.example.com",
        "dl.acme.example.com",
        "dl.cloudsmith.io",
        "upload.cloudsmith.io",
        "api.cloudsmith.io",
        "maven.cloudsmith.io",
    ]


def test_hosts_keep_the_server_preference_order(runner, monkeypatch):
    """The server lists domains most-preferred first, and so does the command."""
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    result, _ = _invoke(runner)

    assert _hosts(result) == [domain.host for domain in SERVER_DOMAINS]


def test_the_api_order_is_never_rearranged(runner, monkeypatch):
    """The API decides the priority, even where the CLI might expect another."""
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")
    domains = [
        _domain("dl.cloudsmith.io", "DOWNLOAD", "GLOBAL"),
        _domain("dl.acme.example.com", "DOWNLOAD"),
    ]

    result, _ = _invoke(runner, domains=domains)

    assert _hosts(result) == ["dl.cloudsmith.io", "dl.acme.example.com"]


def test_domain_type_filter_selects_hosts_by_purpose(runner, monkeypatch):
    """--domain-type answers "which host do I upload to?".

    Unlike --format, every host has exactly one purpose, so this is an exact
    match: an upload endpoint cannot stand in for the download CDN.
    """
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    result, _ = _invoke(runner, "--domain-type", "upload")

    assert _hosts(result) == ["upload.cloudsmith.io"]


def test_repo_filter_drops_other_repositories(runner, monkeypatch):
    """--repo lists the hosts usable for one repository, most-preferred first.

    A repository-scoped host names its own repository in its URLs, so it can
    never stand in for another.
    """
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    result, _ = _invoke(runner, "--repo", "prod", "--domain-type", "download")

    assert _hosts(result) == [
        "dl-prod.acme.example.com",
        "dl.acme.example.com",
        "dl.cloudsmith.io",
    ]


def test_default_shows_everything_with_no_pagination_metadata(runner, monkeypatch):
    """With no --page/--page-size given, the command defaults to --page-all.

    The combined list is small and built from a local cache, unlike other
    `list` commands backed by a live paginated endpoint, so there is no
    upside to hiding entries by default.
    """
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    result, _ = _invoke(runner)

    document = json.loads(result.stdout)
    assert "meta" not in document
    assert len(document["domains"]) == len(SERVER_DOMAINS)


def test_page_size_selects_a_page_and_reports_pagination_metadata(runner, monkeypatch):
    """Passing --page-size switches the command into paged output."""
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")
    total = len(SERVER_DOMAINS)

    result, _ = _invoke(runner, "--page-size", "2", "--page", "1")

    document = json.loads(result.stdout)
    assert len(document["domains"]) == 2
    pagination = document["meta"]["pagination"]
    assert pagination["page"] == 1
    assert pagination["page_size"] == 2
    assert pagination["results_total"] == total
    assert pagination["page_max"] == -(-total // 2)


def test_second_page_continues_where_the_first_left_off(runner, monkeypatch):
    """Successive pages walk through the full list without gaps or overlap."""
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    page_one, _ = _invoke(runner, "--page-size", "2", "--page", "1")
    page_two, _ = _invoke(runner, "--page-size", "2", "--page", "2")

    assert not set(_hosts(page_one)) & set(_hosts(page_two))
    assert json.loads(page_two.stdout)["meta"]["pagination"]["page"] == 2


def test_page_all_shows_everything_even_with_explicit_page_size(runner, monkeypatch):
    """--page-all still means "everything", overriding any --page-size given."""
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    result, _ = _invoke(runner, "--page-all")

    document = json.loads(result.stdout)
    assert "meta" not in document
    assert len(document["domains"]) == len(SERVER_DOMAINS)


def test_page_and_page_all_are_mutually_exclusive(runner, monkeypatch):
    """Explicit --page together with --page-all is rejected, as elsewhere in the CLI."""
    monkeypatch.setenv("CLOUDSMITH_WORKSPACE", "acme")

    with patch(_PATCH_TARGET, return_value=[]):
        result = runner.invoke(
            list_domains,
            ["--page", "2", "--page-all", *HERMETIC_ARGS],
            catch_exceptions=False,
        )

    assert result.exit_code != 0
    assert "--page-all" in result.output or "page-all" in result.output
