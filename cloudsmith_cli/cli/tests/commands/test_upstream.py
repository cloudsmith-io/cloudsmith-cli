import json

import pytest

from ...commands.upstream import UPSTREAM_FORMATS, upstream
from ..utils import random_str


def assert_succeeded(result):
    """Fail with the CLI's own output when a command did not succeed.

    API errors exit through ``ctx.exit(status)``, which a ``CliRunner`` call on
    an ``AliasGroup`` reports in ``return_value`` rather than ``exit_code``.
    """
    assert result.exit_code == 0, result.output
    assert not result.return_value, result.output


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
@pytest.mark.integration
@pytest.mark.parametrize("upstream_format", UPSTREAM_FORMATS)
def test_upstream_commands(
    runner, organization, upstream_format, tmp_repository, tmp_path
):
    upstream_config = {
        # "name" and "upstream_url" are the only required properties for most formats.
        "name": f"cli-test-upstream-{upstream_format}",
        # This obviously isn't an upstream url and will not work on the server,
        # but we aren't testing the server. It must be a domain the API accepts
        # as an upstream URL, which excludes Cloudsmith's own domains.
        #
        # nix is the exception: the server validates that a nix upstream_url
        # points at a real channel under https://channels.nixos.org/, so it
        # needs a URL that passes that check rather than the generic placeholder.
        "upstream_url": (
            "https://channels.nixos.org/nixos-25.05"
            if upstream_format == "nix"
            else "https://example.org"
        ),
        # distro_version is only required for rpm and will be ignored for other formats.
        "distro_version": "fedora/35",
        # distro_versions is only required for deb and will be ignored for other formats.
        "distro_versions": ["ubuntu/xenial"],
    }

    upstream_config_file = tmp_path / (f"cli-test-upstream-{upstream_format}.json")
    upstream_config_file.write_text(str(json.dumps(upstream_config)))

    org_repo = f"{organization}/{tmp_repository['slug']}"

    # Invoke the upstream list command
    result = runner.invoke(
        upstream,
        args=[upstream_format, "ls", org_repo, "-F", "json"],
        catch_exceptions=False,
    )
    assert_succeeded(result)
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
    assert_succeeded(result)
    result_data = json.loads(result.output)["data"]
    assert result_data["name"] == upstream_config["name"]
    assert result_data["upstream_url"] == upstream_config["upstream_url"]

    # Invoke the list command again
    result = runner.invoke(
        upstream,
        args=[upstream_format, "ls", org_repo, "-F", "json"],
        catch_exceptions=False,
    )
    assert_succeeded(result)
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
    assert_succeeded(page_all)
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
    assert_succeeded(result)
    result_data = json.loads(result.output)["data"]
    assert result_data["name"] == upstream_config["name"]
    assert result_data["upstream_url"] == upstream_config["upstream_url"]

    # Invoke the list command again
    result = runner.invoke(
        upstream,
        args=[upstream_format, "ls", org_repo, "-F", "json"],
        catch_exceptions=False,
    )
    assert_succeeded(result)
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
    assert_succeeded(result)
    assert not result.output

    # Invoke the upstream list command yet again
    result = runner.invoke(
        upstream,
        args=[upstream_format, "ls", org_repo, "-F", "json"],
        catch_exceptions=False,
    )
    assert_succeeded(result)
    result_data = json.loads(result.output)["data"]
    assert not result_data  # We should have no upstreams at this point
