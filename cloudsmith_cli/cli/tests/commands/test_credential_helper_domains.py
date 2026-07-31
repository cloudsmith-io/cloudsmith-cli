# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith credential-helper domains` command."""

import json
from unittest.mock import patch

import pytest

from ....cli import config as cli_config
from ....cli.commands.credential_helper.domains import domains_cmd
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


def _invoke(runner, *args, custom_domains=()):
    """Run the command with the custom-domain lookup stubbed; assert a clean exit.

    Returns (result, mock_get) so a caller can read stderr or assert on how the
    lookup was called.
    """
    with patch(_PATCH_TARGET, return_value=list(custom_domains)) as mock_get:
        result = runner.invoke(
            domains_cmd, [*args, *HERMETIC_ARGS], catch_exceptions=False
        )

    assert result.exit_code == 0, result.output
    return result, mock_get


def _by_host(result):
    """Index the emitted domains document by host."""
    return {entry["host"]: entry for entry in json.loads(result.stdout)["domains"]}


def test_document_has_exactly_version_and_domains_keys(runner):
    """The top-level document has exactly the keys `version` and `domains`."""
    result, _ = _invoke(runner)

    document = json.loads(result.stdout)
    assert set(document.keys()) == {"version", "domains"}
    assert document["version"] == 1


def test_custom_entry_has_exact_key_set(runner, monkeypatch):
    """A custom entry's full key set is exactly the six expected fields."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    result, _ = _invoke(runner, custom_domains=[_domain("pypi.acme.example.com", 3)])

    assert _by_host(result)["pypi.acme.example.com"] == {
        "host": "pypi.acme.example.com",
        "format": "python",
        "enabled": True,
        "validated": True,
        "type": "custom",
        "domain_type": "native_api",
    }


def test_custom_domains_resolve_format_and_domain_type(runner, monkeypatch):
    """A custom domain's backend kind resolves to its format and domain type."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain("pypi.acme.example.com", 3),
        _domain("dl.acme.example.com", None),
    ]

    by_host = _by_host(_invoke(runner, custom_domains=records)[0])

    assert by_host["pypi.acme.example.com"]["format"] == "python"
    assert by_host["pypi.acme.example.com"]["domain_type"] == "native_api"
    assert by_host["dl.acme.example.com"]["format"] is None
    assert by_host["dl.acme.example.com"]["domain_type"] == "download"


def test_formatless_hosts_have_null_format(runner):
    """Hosts serving no single format say so as JSON null, not a sentinel."""
    by_host = _by_host(_invoke(runner)[0])

    assert by_host["dl.cloudsmith.io"]["format"] is None
    assert by_host["upload.cloudsmith.io"]["format"] is None
    assert by_host["maven.cloudsmith.io"]["format"] == "maven"


def test_disabled_and_unvalidated_domains_are_listed(runner, monkeypatch):
    """A domain that is not usable is still present, with its state intact."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")
    records = [
        _domain("stale.acme.example.com", 3, enabled=False, validated=False),
        _domain("healthy.acme.example.com", 3, enabled=True, validated=True),
    ]

    by_host = _by_host(_invoke(runner, custom_domains=records)[0])

    assert by_host["stale.acme.example.com"]["enabled"] is False
    assert by_host["stale.acme.example.com"]["validated"] is False
    assert by_host["healthy.acme.example.com"]["enabled"] is True
    assert by_host["healthy.acme.example.com"]["validated"] is True


@pytest.mark.parametrize(
    "host,domain_type",
    [
        ("dl.cloudsmith.io", "download"),
        ("upload.cloudsmith.io", "upload"),
        ("python.cloudsmith.io", "native_api"),
    ],
)
def test_default_entries_expose_domain_type(runner, host, domain_type):
    """Built-in entries say whether they are for download, upload or the API."""
    result, _ = _invoke(runner)

    assert _by_host(result)[host]["domain_type"] == domain_type


@pytest.mark.parametrize("org", [None, "acme"])
def test_builtin_hosts_are_always_listed(runner, monkeypatch, org):
    """Built-in hosts need no organisation, and survive an empty custom lookup."""
    if org:
        monkeypatch.setenv("CLOUDSMITH_ORG", org)

    result, _ = _invoke(runner)

    assert "python.cloudsmith.io" in _by_host(result)


def test_defaults_are_listed_alongside_custom_domains(runner, monkeypatch):
    """Built-in hosts and custom domains appear in one document, typed."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    by_host = _by_host(
        _invoke(runner, custom_domains=[_domain("pypi.acme.example.com", 3)])[0]
    )

    assert by_host["python.cloudsmith.io"]["type"] == "default"
    assert by_host["pypi.acme.example.com"]["type"] == "custom"


def test_org_resolves_from_environment(runner, monkeypatch):
    """CLOUDSMITH_ORG selects the organisation whose custom domains are listed."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme-from-env")

    _, mock_get = _invoke(runner)

    assert mock_get.call_args.args[0] == "acme-from-env"


def test_org_resolves_from_config_file(runner, tmp_path):
    """oidc_org in a trusted config.ini selects the organisation."""
    config = tmp_path / "config.ini"
    config.write_text("[default]\noidc_org = acme-from-config\n", encoding="utf-8")

    _, mock_get = _invoke(runner, "--config-file", str(config))

    assert mock_get.call_args.args[0] == "acme-from-config"


def test_without_org_no_custom_domain_lookup(runner):
    """With no organisation configured, no custom-domain lookup is attempted."""
    _, mock_get = _invoke(runner)

    mock_get.assert_not_called()


def test_lookup_uses_resolved_credential(runner, monkeypatch):
    """The custom-domain lookup authenticates with the resolved credential."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    _, mock_get = _invoke(runner)

    credential = mock_get.call_args.kwargs["credential"]
    assert credential.api_key == "fake-api-key"


def test_lookup_is_strict_so_failures_are_loud(runner, monkeypatch):
    """The lookup runs in strict mode: failures raise instead of degrading.

    A best-effort lookup would silently pretend a typo'd org, missing
    permission or unreachable API means "no custom domains" (exit 0).
    """
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    _, mock_get = _invoke(runner)

    assert mock_get.call_args.kwargs["strict"] is True


def test_lookup_failure_is_a_clean_error(runner, monkeypatch):
    """A failed lookup exits non-zero with a message and no partial document."""
    monkeypatch.setenv("CLOUDSMITH_ORG", "acme")

    with patch(_PATCH_TARGET, side_effect=RuntimeError("boom")):
        result = runner.invoke(domains_cmd, HERMETIC_ARGS, catch_exceptions=False)

    assert result.exit_code != 0
    assert "Failed to fetch custom domains" in result.stderr
    assert result.stdout.strip() == ""


def test_explicit_config_file_supplies_default_domains(runner, tmp_path):
    """An explicit --config-file is a trusted source for [domains]."""
    config = tmp_path / "config.ini"
    config.write_text(
        "[domains]\nindex.internal.example.com = python\n", encoding="utf-8"
    )

    result, _ = _invoke(runner, "--config-file", str(config))

    # The built-in table was replaced wholesale, not merged.
    assert set(_by_host(result)) == {"index.internal.example.com"}


def test_untrusted_config_warning_does_not_contaminate_stdout(
    runner, monkeypatch, tmp_path
):
    """A cwd config.ini's [domains] section triggers a stderr-only warning."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.ini").write_text(
        "[domains]\nindex.internal.example.com = python\n", encoding="utf-8"
    )

    result, _ = _invoke(runner)

    assert "Warning" in result.stderr
    # The untrusted [domains] section was ignored, so built-in hosts remain.
    assert "python.cloudsmith.io" in _by_host(result)


def test_untrusted_warning_suppressed_for_explicit_config_file(
    runner, monkeypatch, tmp_path
):
    """--config-file silences the cwd warning: the explicit file is honoured.

    Warning "ignoring [domains] in ./config.ini" while honouring that very
    file (the user explicitly passed it) would claim the opposite of what
    happens.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.ini").write_text(
        "[domains]\nindex.internal.example.com = python\n", encoding="utf-8"
    )

    result, _ = _invoke(runner, "--config-file", str(tmp_path / "config.ini"))

    assert "Warning" not in result.stderr
    assert set(_by_host(result)) == {"index.internal.example.com"}
