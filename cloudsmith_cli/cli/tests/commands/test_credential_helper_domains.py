# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith credential-helper domains` command."""

import json
from unittest.mock import patch

import pytest

from ....cli import config as cli_config
from ....cli.commands.credential_helper.domains import domains_cmd, format_name
from ....credential_helpers import default_domains
from ....credential_helpers.custom_domains import CustomDomain

_PATCH_TARGET = (
    "cloudsmith_cli.cli.commands.credential_helper.domains.get_custom_domains"
)

HERMETIC_ARGS = ["--api-key", "fake-api-key"]


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch):
    """Keep the developer's real environment out of these tests.

    An inherited CLOUDSMITH_ORG would trigger a live custom-domain lookup, an
    inherited CLOUDSMITH_CONFIG_FILE would supply a foreign domain table, and a
    [domains] section in the developer's real trusted config.ini would replace
    the built-in hosts these tests assert on. The CLI's Options object is a
    process-wide thread-local and ConfigReader.load_config permanently
    prepends any explicit --config-file to class-level state, so both are
    pinned per test to stop one test's organisation leaking into the next.
    """
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delenv("CLOUDSMITH_CONFIG_FILE", raising=False)
    monkeypatch.setattr(default_domains, "_trusted_config_path", lambda: None)
    monkeypatch.delattr(cli_config.OPTIONS, "value", raising=False)
    monkeypatch.setattr(cli_config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(cli_config.ConfigReader, "config_searchpath", ["."])


def _domain(host, backend_kind, enabled=True, validated=True):
    """Build a CustomDomain record for a test."""
    return CustomDomain(
        host=host,
        backend_kind=backend_kind,
        enabled=enabled,
        validated=validated,
    )


@pytest.mark.parametrize(
    "backend_kind,expected",
    [
        (3, "python"),
        (4, "maven"),
        (6, "docker"),
        (9, "npm"),
        # Download-CDN domains carry no backend kind.
        (None, "-"),
        # BackendKind is a hand-maintained mirror of the server enum; a value
        # the CLI does not know must render, not crash.
        (9999, "9999"),
    ],
)
def test_format_name(backend_kind, expected):
    """backend_kind maps to a lowercased format name, with safe fallbacks."""
    assert format_name(backend_kind) == expected


def test_document_has_exactly_version_and_domains_keys(runner):
    """The top-level document has exactly the keys `version` and `domains`."""
    with patch(_PATCH_TARGET, return_value=[]):
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert set(document.keys()) == {"version", "domains"}
    assert document["version"] == 1


def test_lists_domains_with_format_names(runner, monkeypatch):
    """Each domain appears with its host and resolved package format."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain("pypi.acme.example.com", 3),
        _domain("dl.acme.example.com", None),
    ]

    with patch(_PATCH_TARGET, return_value=records):
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    by_host = {entry["host"]: entry for entry in document["domains"]}
    assert by_host["pypi.acme.example.com"]["format"] == "python"
    assert by_host["dl.acme.example.com"]["format"] == "-"


def test_disabled_and_unvalidated_domains_are_listed(runner, monkeypatch):
    """A domain that is not usable is still present, with its state intact."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain("stale.acme.example.com", 3, enabled=False, validated=False),
        _domain("healthy.acme.example.com", 3, enabled=True, validated=True),
    ]

    with patch(_PATCH_TARGET, return_value=records):
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    by_host = {entry["host"]: entry for entry in document["domains"]}
    assert by_host["stale.acme.example.com"]["enabled"] is False
    assert by_host["stale.acme.example.com"]["validated"] is False
    assert by_host["healthy.acme.example.com"]["enabled"] is True
    assert by_host["healthy.acme.example.com"]["validated"] is True


def test_org_with_zero_custom_domains_yields_only_defaults(runner, monkeypatch):
    """An org with zero custom domains yields just the defaults."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    with patch(_PATCH_TARGET, return_value=[]):
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["version"] == 1
    hosts = {entry["host"] for entry in document["domains"]}
    assert "python.cloudsmith.io" in hosts
    assert all(entry["type"] == "default" for entry in document["domains"])


def test_custom_entry_has_exact_key_set(runner, monkeypatch):
    """A custom entry's full key set is exactly the six expected fields."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    with patch(_PATCH_TARGET, return_value=[_domain("pypi.acme.example.com", 3)]):
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    custom_entries = [
        entry for entry in document["domains"] if entry["type"] == "custom"
    ]
    assert custom_entries == [
        {
            "host": "pypi.acme.example.com",
            "format": "python",
            "backend_kind": 3,
            "enabled": True,
            "validated": True,
            "type": "custom",
        }
    ]


def test_org_resolves_from_environment(runner, monkeypatch):
    """CLOUDSMITH_ORG selects the organisation whose custom domains are listed."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme-from-env")

    with patch(_PATCH_TARGET, return_value=[]) as mock_get:
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    assert mock_get.call_args.args[0] == "acme-from-env"


def test_org_resolves_from_config_file(runner, tmp_path):
    """oidc_org in a trusted config.ini selects the organisation."""
    config = tmp_path / "config.ini"
    config.write_text("[default]\noidc_org = acme-from-config\n", encoding="utf-8")

    with patch(_PATCH_TARGET, return_value=[]) as mock_get:
        result = runner.invoke(
            domains_cmd,
            ["--config-file", str(config), *HERMETIC_ARGS],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert mock_get.call_args.args[0] == "acme-from-config"


def test_without_org_no_custom_domain_lookup(runner):
    """With no organisation configured, no custom-domain lookup is attempted."""
    with patch(_PATCH_TARGET, return_value=[]) as mock_get:
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    mock_get.assert_not_called()


def test_network_error_handling(runner, monkeypatch):
    """Network errors from get_custom_domains propagate as clear ClickException."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    network_error = ConnectionError("DNS resolution failed")

    with patch(_PATCH_TARGET, side_effect=network_error):
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code != 0
    assert "Failed to fetch custom domains for 'acme'" in result.stderr
    assert "DNS resolution failed" in result.stderr
    # Ensure no raw traceback in output
    assert "Traceback" not in result.output


def test_defaults_are_listed_alongside_custom_domains(runner, monkeypatch):
    """Built-in hosts and custom domains appear in one document, typed."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    with patch(_PATCH_TARGET, return_value=[_domain("pypi.acme.example.com", 3)]):
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    by_host = {entry["host"]: entry for entry in document["domains"]}
    assert by_host["python.cloudsmith.io"]["type"] == "default"
    assert by_host["pypi.acme.example.com"]["type"] == "custom"


def test_defaults_listed_without_org(runner):
    """Defaults need no org, so the command works unauthenticated."""
    result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    hosts = {entry["host"] for entry in document["domains"]}
    assert "python.cloudsmith.io" in hosts


def test_explicit_config_file_supplies_default_domains(runner, tmp_path):
    """An explicit --config-file is a trusted source for [domains]."""
    config = tmp_path / "config.ini"
    config.write_text(
        "[domains]\nindex.internal.example.com = python\n", encoding="utf-8"
    )

    result = runner.invoke(
        domains_cmd,
        ["--config-file", str(config), *HERMETIC_ARGS],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    hosts = {entry["host"] for entry in document["domains"]}
    # The built-in table was replaced wholesale, not merged.
    assert hosts == {"index.internal.example.com"}


def test_untrusted_config_warning_does_not_contaminate_stdout(
    runner, monkeypatch, tmp_path
):
    """A cwd config.ini's [domains] section triggers a stderr-only warning."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.ini").write_text(
        "[domains]\nindex.internal.example.com = python\n", encoding="utf-8"
    )

    result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    assert "Warning" in result.stderr
    document = json.loads(result.stdout)
    assert document["version"] == 1
    # The untrusted [domains] section was ignored, so built-in hosts remain.
    hosts = {entry["host"] for entry in document["domains"]}
    assert "python.cloudsmith.io" in hosts
