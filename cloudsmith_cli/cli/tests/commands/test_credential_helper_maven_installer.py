# Copyright 2026 Cloudsmith Ltd
"""Tests for `cloudsmith credential-helper install/uninstall/list maven`."""

import pytest
from click.testing import CliRunner

from ....core.api.exceptions import ApiException
from ....credential_helpers.backends import BackendKind
from ....credential_helpers.custom_domains import CustomDomain
from ....credential_helpers.default_domains import DomainType
from ....credential_helpers.maven import config
from ....credential_helpers.maven.installer import MavenInstaller
from ...commands.credential_helper.manage import install_cmd
from ...commands.credential_helper.shell import shell_init

pytestmark = pytest.mark.usefixtures("cli_config_dir")


def custom_domain(host, backend_kind, domain_type, **overrides):
    """Build a discovered custom-domain record."""
    return CustomDomain(
        host=host,
        backend_kind=backend_kind,
        enabled=overrides.pop("enabled", True),
        validated=overrides.pop("validated", True),
        org="my-org",
        domain_type=domain_type,
        **overrides,
    )


@pytest.fixture()
def discovered(monkeypatch):
    """Control the custom domains discovery returns; append to it to add one."""
    records = []

    def fake_get_custom_domains(org, **kwargs):
        return list(records)

    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.maven.installer.get_custom_domains",
        fake_get_custom_domains,
    )
    return records


def install(credential, **kwargs):
    """Install with the defaults the CLI passes, overridden by *kwargs*."""
    return MavenInstaller().install(
        org="my-org", repo="my-repo", credential=credential, **kwargs
    )


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


def test_install_binds_the_repository_and_writes_a_shim(credential, discovered):
    actions = install(credential)

    binding = config.get_binding()
    assert (binding.owner, binding.repo) == ("my-org", "my-repo")
    assert binding.download_host == "dl.cloudsmith.io"
    assert binding.upload_host == "maven.cloudsmith.io"
    assert (config.shims_dir() / "mvn").exists()
    assert any(action.startswith("wrote shim") for action in actions)


def test_the_shim_forwards_to_cloudsmith_exec(credential, discovered):
    """The shim is what makes a bare `mvn` authenticate at all."""
    install(credential)

    assert "cloudsmith exec -- mvn" in (config.shims_dir() / "mvn").read_text()


def test_install_prints_the_deploy_snippet(credential, discovered):
    """Publishing is opt-in, so the pom.xml snippet has to be surfaced."""
    actions = install(credential)

    snippet = "\n".join(actions)
    assert "<distributionManagement>" in snippet
    assert "https://maven.cloudsmith.io/my-org/my-repo/" in snippet
    assert "<id>cloudsmith</id>" in snippet


def test_install_warns_that_the_users_own_settings_are_not_consulted(
    credential, discovered
):
    assert any("~/.m2/settings.xml" in action for action in install(credential))


def test_a_custom_server_id_reaches_both_the_binding_and_the_snippet(
    credential, discovered
):
    actions = install(credential, server_id="private-id")

    assert config.get_binding().server_id == "private-id"
    assert "<id>private-id</id>" in "\n".join(actions)


def test_install_binds_discovered_custom_domains(credential, discovered):
    """Download and upload are separate endpoints with separate domains."""
    discovered.append(custom_domain("dl.example.com", None, DomainType.DOWNLOAD))
    discovered.append(
        custom_domain("mvn.example.com", BackendKind.MAVEN, DomainType.NATIVE_API)
    )

    install(credential)

    binding = config.get_binding()
    assert binding.download_host == "dl.example.com"
    assert binding.upload_host == "mvn.example.com"


def test_an_inactive_custom_domain_is_not_bound(credential, discovered):
    """A domain that is disabled or unvalidated serves nothing."""
    discovered.append(
        custom_domain("dl.example.com", None, DomainType.DOWNLOAD, validated=False)
    )

    install(credential)

    assert config.get_binding().download_host == "dl.cloudsmith.io"


def test_a_repository_scoped_custom_domain_is_not_bound(credential, discovered):
    """Its URLs are a different shape, so it defaults rather than guessing."""
    discovered.append(
        custom_domain("dl.example.com", None, DomainType.DOWNLOAD, repository="my-repo")
    )

    install(credential)

    assert config.get_binding().download_host == "dl.cloudsmith.io"


def test_discovery_failure_warns_rather_than_binding_silently(credential, monkeypatch):
    """An unreachable API must not read as "this org has no custom domains"."""

    def raise_api_error(org, **kwargs):
        raise ApiException(status=500, detail="boom")

    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.maven.installer.get_custom_domains",
        raise_api_error,
    )

    actions = install(credential)

    assert any(
        action.startswith("WARNING: custom-domain discovery") for action in actions
    )
    assert config.get_binding().download_host == "dl.cloudsmith.io"


def test_no_discover_skips_the_api_entirely(credential, monkeypatch):
    def fail(org, **kwargs):
        raise AssertionError("discovery should not run")

    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.maven.installer.get_custom_domains", fail
    )

    install(credential, discover=False)

    assert config.get_binding() is not None


def test_dry_run_changes_nothing(credential, discovered):
    actions = install(credential, dry_run=True)

    assert config.get_binding() is None
    assert not (config.shims_dir() / "mvn").exists()
    assert any(action.startswith("would write shim") for action in actions)


# ---------------------------------------------------------------------------
# uninstall / list
# ---------------------------------------------------------------------------


def test_uninstall_removes_the_shim_and_the_binding(credential, discovered):
    install(credential)

    actions = MavenInstaller().uninstall()

    assert config.get_binding() is None
    assert not (config.shims_dir() / "mvn").exists()
    assert any(action.startswith("removed shim") for action in actions)


def test_uninstall_is_safe_when_nothing_is_installed():
    actions = MavenInstaller().uninstall()

    assert any("nothing to remove" in action for action in actions)


def test_uninstall_dry_run_changes_nothing(credential, discovered):
    install(credential)

    MavenInstaller().uninstall(dry_run=True)

    assert config.get_binding() is not None
    assert (config.shims_dir() / "mvn").exists()


def test_status_reports_the_binding(credential, discovered):
    assert MavenInstaller().status() == {"launcher": None, "hosts": []}

    install(credential)

    status = MavenInstaller().status()
    assert status["launcher"].endswith("mvn")
    assert status["hosts"][0] == "my-org/my-repo"


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_install_requires_org_and_repo():
    result = CliRunner().invoke(install_cmd, ["maven"], catch_exceptions=False)

    assert result.exit_code == 1
    assert "requires --org and --repo" in result.output


def test_shell_init_prints_the_shims_directory():
    result = CliRunner().invoke(shell_init, ["--shell", "bash"])

    assert result.exit_code == 0
    assert str(config.shims_dir()) in result.output
    assert "export PATH=" in result.output
