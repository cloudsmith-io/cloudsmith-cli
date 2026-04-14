import json

import pytest

from ...commands.upstream import UPSTREAM_FORMATS, upstream
from ..utils import random_str


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
@pytest.mark.parametrize("upstream_format", UPSTREAM_FORMATS)
def test_upstream_commands(
    runner, organization, upstream_format, tmp_repository, tmp_path
):
    upstream_config = {
        # "name" and "upstream_url" are the only required properties for most formats.
        "name": "cli-test-upstream-%s" % upstream_format,
        # This obviously isn't an upstream url and will not work on the server,
        # but we aren't testing the server.
        "upstream_url": "https://www.cloudsmith.io",
        # distro_version is only required for rpm and will be ignored for other formats.
        "distro_version": "fedora/35",
        # distro_versions is only required for deb and will be ignored for other formats.
        "distro_versions": ["ubuntu/xenial"],
    }

    upstream_config_file = tmp_path / ("cli-test-upstream-%s.json" % upstream_format)
    upstream_config_file.write_text(str(json.dumps(upstream_config)))

    org_repo = f"{organization}/{tmp_repository['slug']}"

    # Invoke the upstream list command
    result = runner.invoke(
        upstream,
        args=[upstream_format, "ls", org_repo, "-F", "json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    result_data = json.loads(result.output)["data"]
    assert not result_data  # No upstreams have been created yet

    # Create an upstream
    result = runner.invoke(
        upstream,
        args=[
            upstream_format,
            "create",
            org_repo,
            str(upstream_config_file),
            "-F",
            "json",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    result_data = json.loads(result.output)["data"]
    assert result_data["name"] == upstream_config["name"]
    assert result_data["upstream_url"] == upstream_config["upstream_url"]

    # Invoke the list command again
    result = runner.invoke(
        upstream,
        args=[upstream_format, "ls", org_repo, "-F", "json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    result_data = json.loads(result.output)["data"]
    assert (
        len(result_data) == 1
    )  # The list command output should be exactly one upstream
    result_data = result_data[0]
    assert result_data["name"] == upstream_config["name"]
    assert result_data["upstream_url"] == upstream_config["upstream_url"]

    # Minimal page-all success (no pagination args besides flag)
    page_all = runner.invoke(
        upstream,
        args=[upstream_format, "ls", org_repo, "--page-all", "-F", "json"],
        catch_exceptions=False,
    )
    assert page_all.exit_code == 0
    page_all_data = json.loads(page_all.output)["data"]
    assert len(page_all_data) == 1  # Should return the same single upstream
    assert "Invalid value for '--page-all'" not in page_all.output

    # Conflict: page-all with explicit page number
    conflict = runner.invoke(
        upstream,
        args=[
            upstream_format,
            "ls",
            org_repo,
            "--page-all",
            "--page",
            "1",
            "-F",
            "json",
        ],
        catch_exceptions=False,
    )
    assert conflict.exit_code != 0
    assert "Invalid value for '--page-all'" in conflict.output
    assert "Cannot be used with --page (-p) or --page-size (-l)." in conflict.output

    slug_perm = result_data["slug_perm"]
    assert slug_perm
    org_repo_slug_perm = f"{org_repo}/{slug_perm}"

    # Update an upstream
    upstream_config["name"] = random_str()
    upstream_config_file.write_text(str(json.dumps(upstream_config)))

    result = runner.invoke(
        upstream,
        args=[
            upstream_format,
            "update",
            org_repo_slug_perm,
            str(upstream_config_file),
            "-F",
            "json",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    result_data = json.loads(result.output)["data"]
    assert result_data["name"] == upstream_config["name"]
    assert result_data["upstream_url"] == upstream_config["upstream_url"]

    # Invoke the list command again
    result = runner.invoke(
        upstream,
        args=[upstream_format, "ls", org_repo, "-F", "json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    result_data = json.loads(result.output)["data"]
    assert (
        len(result_data) == 1
    )  # The list command output should be exactly one upstream
    result_data = result_data[0]
    assert result_data["name"] == upstream_config["name"]
    assert result_data["upstream_url"] == upstream_config["upstream_url"]

    # Delete an upstream
    result = runner.invoke(
        upstream,
        args=[upstream_format, "delete", org_repo_slug_perm, "-y", "-F", "json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert not result.output

    # Invoke the upstream list command yet again
    result = runner.invoke(
        upstream,
        args=[upstream_format, "ls", org_repo, "-F", "json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    result_data = json.loads(result.output)["data"]
    assert not result_data  # We should have no upstreams at this point


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
def test_alpine_upstream_ls_pretty_rsa_columns(
    runner, organization, tmp_repository, tmp_path
):
    """Pretty-output ls for alpine must render all four RSA columns with correct headers and values.

    Alpine is the only format with RSA verification fields (rsa_key_inline, rsa_key_url,
    rsa_verification, rsa_verification_status). These are appended to the common column set
    inside print_upstreams(), so a regression in the branching logic or header list would
    silently drop or misalign them. This test catches that by asserting against the rendered
    table text rather than JSON output.
    """
    rsa_key_url = "https://www.cloudsmith.io"
    upstream_config = {
        "name": "cli-test-upstream-alpine-rsa",
        "upstream_url": "https://www.cloudsmith.io",
        "rsa_key_url": rsa_key_url,
    }

    upstream_config_file = tmp_path / "cli-test-upstream-alpine-rsa.json"
    upstream_config_file.write_text(json.dumps(upstream_config))

    org_repo = f"{organization}/{tmp_repository['slug']}"

    # Create the upstream and capture its slug_perm for later cleanup
    create_result = runner.invoke(
        upstream,
        args=["alpine", "create", org_repo, str(upstream_config_file), "-F", "json"],
        catch_exceptions=False,
    )
    assert create_result.exit_code == 0
    slug_perm = json.loads(create_result.output)["data"]["slug_perm"]

    try:
        # Run ls with default pretty output — the path under test
        result = runner.invoke(
            upstream,
            args=["alpine", "ls", org_repo],
            catch_exceptions=False,
        )
        assert result.exit_code == 0

        # All four RSA column headers must appear in the table header row
        assert "RSA Key Inline" in result.output
        assert "RSA Key URL" in result.output
        assert (
            "RSA Verification Status" in result.output
        )  # most specific; covers "RSA Verification" too
        assert "RSA Verification" in result.output

        # The rsa_key_url value we set must appear in the data row
        assert rsa_key_url in result.output

        # Common non-RSA headers must still be present (guard against over-trimming)
        assert "Name" in result.output
        assert "Upstream Url" in result.output
        assert "Verify SSL" in result.output

    finally:
        runner.invoke(
            upstream,
            args=["alpine", "delete", f"{org_repo}/{slug_perm}", "-y"],
            catch_exceptions=False,
        )
