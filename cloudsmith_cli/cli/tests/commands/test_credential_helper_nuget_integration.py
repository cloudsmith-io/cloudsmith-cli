# Copyright 2026 Cloudsmith Ltd
"""Live integration tests for the NuGet credential provider.

These are the end-to-end checks the unit tests cannot make: that a real
``dotnet restore`` authenticates against a private Cloudsmith NuGet feed
using *only* the ``nuget-plugin-cloudsmith`` launcher, with no credentials in
any ``nuget.config``, and that a Workspace's NuGet custom domain is
discovered from the live API and authenticated.

Requires:
    * ``dotnet`` 9.0.200 or later on PATH, which is the first SDK whose NuGet
      discovers ``nuget-plugin-*`` executables on PATH (skipped otherwise).
    * ``cloudsmith`` on PATH, i.e. cloudsmith-cli installed as a console
      script, because the launcher runs it (skipped otherwise).
    * ``PYTEST_CLOUDSMITH_API_KEY``, ``PYTEST_CLOUDSMITH_API_HOST`` and
      ``PYTEST_CLOUDSMITH_ORGANIZATION``.
    * Optionally ``PYTEST_CLOUDSMITH_NUGET_HOST``: the NuGet feed host for the
      API host (defaults to the API host with ``api.`` replaced by ``nuget.``).
    * Optionally ``PYTEST_CLOUDSMITH_NUGET_CUSTOM_DOMAIN_FEED``: the v3 service
      index URL of a private feed served from one of the Workspace's NuGet
      custom domains, e.g. ``https://nuget.example.com/v3/index.json``
      (the custom-domain test is skipped otherwise).
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import pytest

from ....core.api.init import initialise_api
from ....core.api.repos import create_repo, delete_repo
from ....core.credentials.models import CredentialResult
from ....credential_helpers.common import is_standard_cloudsmith_domain
from ...commands.credential_helper.manage import install_cmd
from ...commands.push import push
from ..utils import random_str

PACKAGE_ID = "Cloudsmith.Cli.NuGetProbe"
PACKAGE_VERSION = "1.0.0"
LAUNCHER = "nuget-plugin-cloudsmith"


def _get_env_var_or_skip(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        pytest.skip(f"{key} not provided")
    return value


@pytest.fixture()
def private_repository(organization, api_host, api_key):
    """Yield a temporary private repository; repositories default to public."""
    initialise_api(
        host=api_host, credential=CredentialResult(api_key=api_key, source_name="test")
    )
    repo_data = create_repo(
        organization, {"name": random_str(), "repository_type_str": "Private"}
    )
    yield repo_data
    delete_repo(organization, repo_data["slug"])


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


def _feed_host(api_host: str) -> str:
    """Return the NuGet feed host that serves repositories for *api_host*."""
    override = os.environ.get("PYTEST_CLOUDSMITH_NUGET_HOST")
    if override:
        return override
    host = urlsplit(api_host).hostname or api_host
    if not host.startswith("api."):
        pytest.skip("set PYTEST_CLOUDSMITH_NUGET_HOST for this API host")
    return "nuget." + host[len("api.") :]


def _install(runner, bin_dir, organization, domains=()) -> None:
    """Install the launcher with the CLI, discovering custom domains live."""
    args = ["nuget", "--bin-dir", str(bin_dir), "--workspace", organization]
    args += ["--refresh"]
    for domain in domains:
        args += ["--domain", domain]
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


def _write_project(directory, framework, package_reference=None) -> None:
    """Write a minimal SDK-style project that needs nothing from nuget.org."""
    directory.mkdir(parents=True, exist_ok=True)
    reference = ""
    if package_reference:
        reference = (
            "<ItemGroup>"
            f'<PackageReference Include="{package_reference}" '
            f'Version="{PACKAGE_VERSION}" />'
            "</ItemGroup>"
        )
    (directory / f"{directory.name}.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk">'
        f"<PropertyGroup><TargetFramework>{framework}</TargetFramework>"
        "</PropertyGroup>"
        f"{reference}</Project>\n",
        encoding="utf-8",
    )


def _restore(dotnet_env, consumer, nuget_config, tmp_path, attempt):
    """Run a cache-free `dotnet restore` and return the completed process."""
    packages = tmp_path / f"packages-{attempt}"
    env = {
        **dotnet_env,
        "NUGET_PACKAGES": str(packages),
        "NUGET_HTTP_CACHE_PATH": str(tmp_path / f"http-cache-{attempt}"),
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
    organization,
    api_host,
    private_repository,
    tmp_path,
    dotnet_major,
    cloudsmith_dir,
):
    """`dotnet restore` reads a private feed with only the plugin's credentials."""
    framework = f"net{dotnet_major}.0"
    feed_host = _feed_host(api_host)
    feed = (
        f"https://{feed_host}/{organization}/{private_repository['slug']}/v3/index.json"
    )

    # Pack a tiny library and push it to the temporary repository.
    probe = tmp_path / PACKAGE_ID
    _write_project(probe, framework)
    subprocess.run(
        [
            "dotnet",
            "pack",
            str(probe),
            "-o",
            str(tmp_path / "out"),
            f"-p:PackageId={PACKAGE_ID}",
            f"-p:Version={PACKAGE_VERSION}",
        ],
        env=_env(tmp_path, []),
        capture_output=True,
        text=True,
        check=True,
    )
    nupkg = tmp_path / "out" / f"{PACKAGE_ID}.{PACKAGE_VERSION}.nupkg"
    result = runner.invoke(
        push,
        args=["nuget", f"{organization}/{private_repository['slug']}", str(nupkg)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output

    # A consumer whose only source is the feed, with no credentials for it.
    consumer = tmp_path / "Consumer"
    _write_project(consumer, framework, package_reference=PACKAGE_ID)
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

    # Install the plugin; non-standard feed hosts must be trusted explicitly.
    bin_dir = tmp_path / "bin"
    extra = () if is_standard_cloudsmith_domain(feed_host) else (feed_host,)
    _install(runner, bin_dir, organization, domains=extra)
    with_plugin = _env(tmp_path, [str(bin_dir), cloudsmith_dir])

    # The feed index can trail the push briefly, so retry a few times.
    for attempt in range(6):
        result, packages = _restore(
            with_plugin, consumer, nuget_config, tmp_path, attempt
        )
        if result.returncode == 0:
            break
        time.sleep(10)

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert (packages / PACKAGE_ID.lower() / PACKAGE_VERSION).is_dir()


def _plugin_credentials(launcher, feed, env) -> dict:
    """Ask the installed plugin for *feed*'s credentials over its protocol."""
    requests = [
        {
            "RequestId": "handshake",
            "Type": "Request",
            "Method": "Handshake",
            "Payload": {"ProtocolVersion": "2.0.0", "MinimumProtocolVersion": "2.0.0"},
        },
        {
            "RequestId": "credentials",
            "Type": "Request",
            "Method": "GetAuthenticationCredentials",
            "Payload": {
                "Uri": feed,
                "IsRetry": False,
                "IsNonInteractive": True,
                "CanShowDialog": False,
            },
        },
    ]
    result = subprocess.run(
        [str(launcher), "-Plugin"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    for line in result.stdout.splitlines():
        message = json.loads(line)
        if message["RequestId"] == "credentials":
            return message["Payload"]
    raise AssertionError(f"no credentials response:\n{result.stdout}{result.stderr}")


def _get_status(url, auth=None) -> int:
    request = urllib.request.Request(url)
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
@pytest.mark.integration
def test_plugin_authenticates_a_discovered_custom_domain(
    runner, organization, tmp_path, cloudsmith_dir
):
    """The plugin finds the Workspace's NuGet custom domain via the live API."""
    feed = _get_env_var_or_skip("PYTEST_CLOUDSMITH_NUGET_CUSTOM_DOMAIN_FEED")
    if not feed.startswith("https://"):
        pytest.skip("PYTEST_CLOUDSMITH_NUGET_CUSTOM_DOMAIN_FEED must be https")

    # No --domain: the host must come from custom-domain discovery.
    bin_dir = tmp_path / "bin"
    _install(runner, bin_dir, organization)
    env = _env(tmp_path, [str(bin_dir), cloudsmith_dir])

    payload = _plugin_credentials(bin_dir / LAUNCHER, feed, env)
    assert payload.get("ResponseCode") == "Success", payload

    # The credentials the plugin hands NuGet must open the private feed.
    assert _get_status(feed) == 401
    assert _get_status(feed, (payload["Username"], payload["Password"])) == 200
