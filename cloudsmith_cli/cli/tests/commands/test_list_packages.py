"""Tests for the `cloudsmith list packages` command."""

import json

import httpretty
import httpretty.core
import pytest

from ....cli.commands.main import main

API_HOST = "https://api.cloudsmith.io"
OWNER = "test-org"
REPO = "test-repo"
PACKAGES_URL = f"{API_HOST}/packages/{OWNER}/{REPO}/"
HERMETIC_ARGS = ["--api-key", "fake-api-key", "--api-host", API_HOST]
LIST_PACKAGES_COMMAND = ["list", "packages", f"{OWNER}/{REPO}"] + HERMETIC_ARGS
CONNECTED_PARAM = "include_connected_repositories"


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch):
    """Keep stray environment/config from influencing the command."""
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delenv("CLOUDSMITH_API_HOST", raising=False)
    monkeypatch.delenv("CLOUDSMITH_API_KEY", raising=False)
    monkeypatch.setattr(
        httpretty.core.fakesock.socket,
        "shutdown",
        lambda self, how: None,
        raising=False,
    )


def _package(slug, origin_repository):
    return {
        "name": f"pkg-{slug}",
        "version": "1.0.0",
        "status_str": "Completed",
        "stage_str": "Fully Synchronised",
        "namespace": OWNER,
        "repository": REPO,
        "origin_repository": origin_repository,
        "slug": slug,
    }


def register_packages():
    httpretty.register_uri(
        httpretty.GET,
        PACKAGES_URL,
        body=json.dumps(
            [_package("local1", None), _package("remote1", "connected-repo")]
        ),
        status=200,
        content_type="application/json",
    )


@httpretty.activate(allow_net_connect=False)
def test_without_include_connected_omits_param_and_origin_column(runner):
    register_packages()

    result = runner.invoke(main, LIST_PACKAGES_COMMAND, catch_exceptions=False)

    assert result.exit_code == 0
    assert CONNECTED_PARAM not in httpretty.last_request().querystring
    assert "Origin Repository" not in result.output
    assert "connected-repo" not in result.output


@httpretty.activate(allow_net_connect=False)
def test_include_connected_sends_param_with_query_and_shows_origin(runner):
    register_packages()

    result = runner.invoke(
        main,
        LIST_PACKAGES_COMMAND + ["--include-connected", "-q", "pkg", "--page-all"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    querystring = httpretty.last_request().querystring
    assert querystring[CONNECTED_PARAM] == ["True"]
    assert querystring["query"] == ["pkg"]
    assert "Origin Repository" in result.output
    assert "connected-repo" in result.output
    assert "None" not in result.output


@httpretty.activate(allow_net_connect=False)
def test_include_connected_json_output_has_origin_repository(runner):
    register_packages()

    result = runner.invoke(
        main,
        LIST_PACKAGES_COMMAND + ["--include-connected", "-F", "json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    origins = [
        package["origin_repository"] for package in json.loads(result.stdout)["data"]
    ]
    assert origins == [None, "connected-repo"]


def test_help_documents_download_url_caveat(runner):
    result = runner.invoke(main, ["list", "packages", "--help"])

    help_text = " ".join(result.output.split())
    assert "--include-connected" in help_text
    assert "point at the requesting repository" in help_text
