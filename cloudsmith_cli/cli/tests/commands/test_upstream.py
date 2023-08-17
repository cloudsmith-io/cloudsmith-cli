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
