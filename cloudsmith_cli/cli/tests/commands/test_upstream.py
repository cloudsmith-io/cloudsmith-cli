import json

import pytest

from ...commands.upstream import UPSTREAM_FORMATS, upstream
from ..utils import random_str

#: The canonical public upstream for each format. These are already indexed,
#: so the API validates them quickly, and none needs credentials. The API
#: strips trailing slashes, so none is written with one. Formats without a
#: single canonical source (generic, swift) use a small placeholder page.
UPSTREAM_URLS = {
    "alpine": "https://dl-cdn.alpinelinux.org/alpine",
    "cargo": "https://index.crates.io",
    "conda": "https://conda.anaconda.org/conda-forge",
    "cran": "https://cloud.r-project.org",
    "dart": "https://pub.dev",
    "deb": "http://archive.ubuntu.com/ubuntu",
    "docker": "https://index.docker.io",
    "generic": "https://example.org",
    "go": "https://proxy.golang.org",
    "helm": "https://charts.bitnami.com/bitnami",
    "hex": "https://repo.hex.pm",
    "huggingface": "https://huggingface.co",
    "maven": "https://repo1.maven.org/maven2",
    "nix": "https://channels.nixos.org/nixos-26.05",
    "npm": "https://registry.npmjs.org",
    "nuget": "https://api.nuget.org/v3/index.json",
    "python": "https://pypi.org",
    "rpm": "https://archives.fedoraproject.org/pub/archive/fedora/linux/releases/35/Everything/x86_64/os",
    "ruby": "https://rubygems.org",
    "swift": "https://example.org",
}


def test_every_upstream_format_has_an_upstream_url():
    assert set(UPSTREAM_URLS) == set(UPSTREAM_FORMATS)


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
        "upstream_url": UPSTREAM_URLS[upstream_format],
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
