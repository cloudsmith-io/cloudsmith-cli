# Copyright 2026 Cloudsmith Ltd
"""Live integration tests for the NuGet credential provider.

These are the end-to-end checks the unit tests cannot make: that a real
``dotnet restore`` authenticates against a private Cloudsmith NuGet feed
using *only* the ``nuget-plugin-cloudsmith`` launcher, with no credentials in
any ``nuget.config``, both on the standard NuGet host and on a Workspace's
NuGet custom domain discovered from the live API.

The tests only read. Each case restores ``Cloudsmith.Cli.NuGetProbe`` 1.0.0
(``netstandard2.0``) from a long-lived private repository that was set up
once: ``cli-pytest-nuget`` in the standard Workspace and
``cli-pytest-custom-domain`` in the custom-domain Workspace.

Requires:
    * ``dotnet`` 9.0.200 or later on PATH, which is the first SDK whose NuGet
      discovers ``nuget-plugin-*`` executables on PATH (skipped otherwise).
    * ``cloudsmith`` on PATH, i.e. cloudsmith-cli installed as a console
      script, because the launcher runs it (skipped otherwise).
    * ``PYTEST_CLOUDSMITH_API_KEY``, ``PYTEST_CLOUDSMITH_API_HOST`` and
      ``PYTEST_CLOUDSMITH_ORGANIZATION``.
    * For the ``custom_domain`` case, ``PYTEST_CLOUDSMITH_CUSTOM_DOMAIN_WORKSPACE``
      (a Workspace with a validated NuGet custom domain) and
      ``PYTEST_CLOUDSMITH_CUSTOM_DOMAIN_API_KEY`` (a key for that Workspace).
      The case is skipped when either is missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from urllib.parse import urlsplit

import pytest

from ....core.credentials.models import CredentialResult
from ....credential_helpers.backends import BackendKind
from ....credential_helpers.custom_domains import get_format_domains
from ...commands.credential_helper.manage import install_cmd

PACKAGE_ID = "Cloudsmith.Cli.NuGetProbe"
PACKAGE_VERSION = "1.0.0"
LAUNCHER = "nuget-plugin-cloudsmith"
CASE_VARS = {
    "standard-domain": (
        "PYTEST_CLOUDSMITH_ORGANIZATION",
        "PYTEST_CLOUDSMITH_API_KEY",
    ),
    "custom-domain": (
        "PYTEST_CLOUDSMITH_CUSTOM_DOMAIN_WORKSPACE",
        "PYTEST_CLOUDSMITH_CUSTOM_DOMAIN_API_KEY",
    ),
}
CASE_REPOS = {
    "standard-domain": "cli-pytest-nuget",
    "custom-domain": "cli-pytest-custom-domain",
}


def _get_env_var_or_skip(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        pytest.skip(f"{key} not provided")
    return value


@pytest.fixture(
    params=[
        "standard-domain",
        pytest.param("custom-domain", marks=pytest.mark.custom_domain),
    ]
)
def domain_case(request) -> str:
    """Return the feed host case under test: standard or custom domain."""
    return request.param


@pytest.fixture()
def workspace(domain_case) -> str:
    """Return the Workspace configured for *domain_case*."""
    return _get_env_var_or_skip(CASE_VARS[domain_case][0])


@pytest.fixture()
def api_key(domain_case) -> str:
    """Return the API key for the Workspace of *domain_case*."""
    return _get_env_var_or_skip(CASE_VARS[domain_case][1])


@pytest.fixture()
def dotnet_major() -> int:
    """Return the .NET SDK major version, or skip if it cannot find plugins."""
    dotnet = shutil.which("dotnet")
    if not dotnet:
        pytest.skip("dotnet is not installed / not on PATH")
    output = subprocess.run(
        [dotnet, "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    version = tuple(int(part) for part in output.split("-")[0].split(".")[:3])
    if version < (9, 0, 200):
        pytest.skip(f"dotnet {output} cannot discover NuGet plugins on PATH")
    return version[0]


@pytest.fixture()
def cloudsmith_dir() -> str:
    """Return the directory holding the cloudsmith console script, or skip."""
    path = shutil.which("cloudsmith")
    if not path:
        pytest.skip("cloudsmith not on PATH (install cloudsmith-cli as a script)")
    return os.path.dirname(path)


def _feed(domain_case, workspace, repo, api_host, api_key) -> str:
    """Return the v3 index URL of *repo* on the host the test case covers."""
    if domain_case == "custom-domain":
        hosts = get_format_domains(
            workspace,
            BackendKind.NUGET,
            credential=CredentialResult(api_key=api_key, source_name="test"),
            api_host=api_host,
        )
        if not hosts:
            pytest.skip(f"{workspace} has no validated NuGet custom domain")
        # A custom domain belongs to one Workspace, so its URLs omit the slug.
        return f"https://{hosts[0]}/{repo}/v3/index.json"
    # api.cloudsmith.io -> nuget.cloudsmith.io, api-stg -> nuget-stg.
    api_hostname = urlsplit(api_host).hostname
    host = "nuget" + api_hostname.removeprefix("api")
    return f"https://{host}/{workspace}/{repo}/v3/index.json"


def _install(runner, bin_dir, workspace) -> None:
    """Install the launcher with the CLI, discovering custom domains live."""
    args = ["nuget", "--bin-dir", str(bin_dir), "--workspace", workspace]
    args += ["--refresh"]
    result = runner.invoke(install_cmd, args=args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert (bin_dir / LAUNCHER).exists()


def _env(tmp_path, path_dirs) -> dict:
    """Return an environment where only PATH can supply a NuGet plugin."""
    env = dict(os.environ)
    # These would replace PATH discovery or hand NuGet credentials directly.
    for key in ("NUGET_PLUGIN_PATHS", "VSS_NUGET_EXTERNAL_FEED_ENDPOINTS"):
        env.pop(key, None)
    env.update(
        {
            "PATH": os.pathsep.join([*path_dirs, os.environ.get("PATH", "")]),
            "NUGET_PLUGINS_CACHE_PATH": str(tmp_path / "plugins-cache"),
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
            "DOTNET_NOLOGO": "1",
        }
    )
    return env


def _write_consumer(directory, framework) -> None:
    """Write a project whose only dependency is the probe package."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{directory.name}.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk">'
        f"<PropertyGroup><TargetFramework>{framework}</TargetFramework>"
        "</PropertyGroup><ItemGroup>"
        f'<PackageReference Include="{PACKAGE_ID}" Version="{PACKAGE_VERSION}" />'
        "</ItemGroup></Project>\n",
        encoding="utf-8",
    )


def _restore(dotnet_env, consumer, nuget_config, tmp_path, label):
    """Run a cache-free `dotnet restore` and return the completed process."""
    packages = tmp_path / f"packages-{label}"
    env = {
        **dotnet_env,
        "NUGET_PACKAGES": str(packages),
        "NUGET_HTTP_CACHE_PATH": str(tmp_path / f"http-cache-{label}"),
    }
    result = subprocess.run(
        ["dotnet", "restore", str(consumer), "--configfile", str(nuget_config)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, packages


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
@pytest.mark.integration
def test_dotnet_restore_authenticates_via_plugin(
    runner,
    domain_case,
    workspace,
    api_host,
    api_key,
    tmp_path,
    dotnet_major,
    cloudsmith_dir,
):
    """`dotnet restore` reads a private feed with only the plugin's credentials."""
    feed = _feed(domain_case, workspace, CASE_REPOS[domain_case], api_host, api_key)

    # A consumer whose only source is the feed, with no credentials for it.
    consumer = tmp_path / "Consumer"
    _write_consumer(consumer, f"net{dotnet_major}.0")
    nuget_config = tmp_path / "nuget.config"
    nuget_config.write_text(
        "<configuration><packageSources><clear />"
        f'<add key="cloudsmith" value="{feed}" />'
        "</packageSources></configuration>\n",
        encoding="utf-8",
    )

    # Without the plugin a private feed must refuse the restore.
    without_plugin = _env(tmp_path, [cloudsmith_dir])
    result, _ = _restore(without_plugin, consumer, nuget_config, tmp_path, "denied")
    assert result.returncode != 0
    assert "401" in result.stdout + result.stderr, result.stdout

    # No --domain: a custom domain must come from live discovery.
    bin_dir = tmp_path / "bin"
    _install(runner, bin_dir, workspace)
    with_plugin = _env(tmp_path, [str(bin_dir), cloudsmith_dir])

    result, packages = _restore(
        with_plugin, consumer, nuget_config, tmp_path, "allowed"
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert (packages / PACKAGE_ID.lower() / PACKAGE_VERSION).is_dir()
