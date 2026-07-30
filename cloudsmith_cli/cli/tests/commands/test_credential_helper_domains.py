# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith credential-helper domains` command."""

import json
from unittest.mock import patch

import pytest

from ....cli.commands.credential_helper.domains import domains_cmd, format_name
from ....credential_helpers import default_domains
from ....credential_helpers.custom_domains import CustomDomain

_PATCH_TARGET = (
    "cloudsmith_cli.cli.commands.credential_helper.domains.get_custom_domains"
)

# Satisfies the credential chain from the flag provider so the CLI wiring tests
# never touch the developer's real credentials.ini, keyring, or the network.
HERMETIC_ARGS = ["--api-key", "fake-api-key"]


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch):
    """Keep the developer's real environment out of these tests.

    An inherited CLOUDSMITH_ORG would trigger a live custom-domain lookup, an
    inherited CLOUDSMITH_CONFIG_FILE would supply a foreign domain table, and a
    [domains] section in the developer's real trusted config.ini would replace
    the built-in hosts these tests assert on.
    """
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delenv("CLOUDSMITH_CONFIG_FILE", raising=False)
    monkeypatch.setattr(default_domains, "_trusted_config_path", lambda: None)


def _domain(host, backend_kind, enabled=True, validated=True):
    """Build a CustomDomain record for a test."""
    return CustomDomain(
        host=host,
        backend_kind=backend_kind,
        enabled=enabled,
        validated=validated,
    )


# ---------------------------------------------------------------------------
# 1. format_name — backend_kind rendering
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 2. JSON document shape
# ---------------------------------------------------------------------------


def test_document_has_exactly_version_and_domains_keys(runner):
    """The top-level document has exactly the keys `version` and `domains`."""
    with patch(_PATCH_TARGET, return_value=[]):
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert set(document.keys()) == {"version", "domains"}
    assert document["version"] == 1


def test_lists_domains_with_format_names(runner):
    """Each domain appears with its host and resolved package format."""
    records = [
        _domain("pypi.acme.example.com", 3),
        _domain("dl.acme.example.com", None),
    ]

    with patch(_PATCH_TARGET, return_value=records):
        result = runner.invoke(
            domains_cmd, ["--org", "acme", *HERMETIC_ARGS], catch_exceptions=False
        )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    by_host = {entry["host"]: entry for entry in document["domains"]}
    assert by_host["pypi.acme.example.com"]["format"] == "python"
    assert by_host["dl.acme.example.com"]["format"] == "-"


def test_disabled_and_unvalidated_domains_are_listed(runner):
    """A domain that is not usable is still present, with its state intact."""
    records = [
        _domain("stale.acme.example.com", 3, enabled=False, validated=False),
        _domain("healthy.acme.example.com", 3, enabled=True, validated=True),
    ]

    with patch(_PATCH_TARGET, return_value=records):
        result = runner.invoke(
            domains_cmd, ["--org", "acme", *HERMETIC_ARGS], catch_exceptions=False
        )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    by_host = {entry["host"]: entry for entry in document["domains"]}
    assert by_host["stale.acme.example.com"]["enabled"] is False
    assert by_host["stale.acme.example.com"]["validated"] is False
    assert by_host["healthy.acme.example.com"]["enabled"] is True
    assert by_host["healthy.acme.example.com"]["validated"] is True


def test_custom_only_with_no_custom_domains_is_empty_array(runner):
    """--custom-only with no custom domains yields an empty `domains` array."""
    with patch(_PATCH_TARGET, return_value=[]):
        result = runner.invoke(
            domains_cmd,
            ["--org", "acme", "--custom-only", *HERMETIC_ARGS],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"version": 1, "domains": []}


def test_org_with_zero_custom_domains_yields_only_defaults(runner):
    """An org with zero custom domains yields just the defaults."""
    with patch(_PATCH_TARGET, return_value=[]):
        result = runner.invoke(
            domains_cmd, ["--org", "acme", *HERMETIC_ARGS], catch_exceptions=False
        )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["version"] == 1
    hosts = {entry["host"] for entry in document["domains"]}
    assert "python.cloudsmith.io" in hosts
    assert all(entry["type"] == "default" for entry in document["domains"])


def test_custom_entry_has_exact_key_set(runner):
    """A custom entry's full key set is exactly the six expected fields."""
    with patch(_PATCH_TARGET, return_value=[_domain("pypi.acme.example.com", 3)]):
        result = runner.invoke(
            domains_cmd,
            ["--org", "acme", "--custom-only", *HERMETIC_ARGS],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["domains"] == [
        {
            "host": "pypi.acme.example.com",
            "format": "python",
            "backend_kind": 3,
            "enabled": True,
            "validated": True,
            "type": "custom",
        }
    ]


# ---------------------------------------------------------------------------
# 3. Org resolution
# ---------------------------------------------------------------------------


def test_org_falls_back_to_environment(runner, monkeypatch):
    """CLOUDSMITH_ORG is used when --org is not given."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme-from-env")

    with patch(_PATCH_TARGET, return_value=[]) as mock_get:
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    assert mock_get.call_args.args[0] == "acme-from-env"


# ---------------------------------------------------------------------------
# 4. Network error handling
# ---------------------------------------------------------------------------


def test_network_error_handling(runner):
    """Network errors from get_custom_domains propagate as clear ClickException."""
    network_error = ConnectionError("DNS resolution failed")

    with patch(_PATCH_TARGET, side_effect=network_error):
        result = runner.invoke(
            domains_cmd, ["--org", "acme", *HERMETIC_ARGS], catch_exceptions=False
        )

    assert result.exit_code != 0
    assert "Failed to fetch custom domains for 'acme'" in result.stderr
    assert "DNS resolution failed" in result.stderr
    # Ensure no raw traceback in output
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# 5. Default domains
# ---------------------------------------------------------------------------


def test_defaults_are_listed_alongside_custom_domains(runner):
    """Built-in hosts and custom domains appear in one document, typed."""
    with patch(_PATCH_TARGET, return_value=[_domain("pypi.acme.example.com", 3)]):
        result = runner.invoke(
            domains_cmd, ["--org", "acme", *HERMETIC_ARGS], catch_exceptions=False
        )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    by_host = {entry["host"]: entry for entry in document["domains"]}
    assert by_host["python.cloudsmith.io"]["type"] == "default"
    assert by_host["pypi.acme.example.com"]["type"] == "custom"


def test_custom_only_flag_hides_defaults(runner):
    """--custom-only narrows the listing to the org's custom domains."""
    with patch(_PATCH_TARGET, return_value=[_domain("pypi.acme.example.com", 3)]):
        result = runner.invoke(
            domains_cmd,
            ["--org", "acme", "--custom-only", *HERMETIC_ARGS],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    hosts = {entry["host"] for entry in document["domains"]}
    assert hosts == {"pypi.acme.example.com"}


def test_defaults_listed_without_org(runner):
    """Defaults need no org, so the command works unauthenticated."""
    result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    hosts = {entry["host"] for entry in document["domains"]}
    assert "python.cloudsmith.io" in hosts


def test_custom_only_without_org_still_errors(runner):
    """--custom-only genuinely needs an org, so the error remains."""
    result = runner.invoke(
        domains_cmd, ["--custom-only", *HERMETIC_ARGS], catch_exceptions=False
    )

    assert result.exit_code != 0
    assert "No organisation specified" in result.stderr


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


# ---------------------------------------------------------------------------
# 6. Untrusted config warning does not contaminate stdout
# ---------------------------------------------------------------------------


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
