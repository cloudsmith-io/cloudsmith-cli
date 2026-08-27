"""CLI/Commands - Upgrade - Tests."""

import contextlib
import json
from unittest import mock

import requests

from ....core import installation, self_update, update_check
from ...commands import main as main_module


def make_manifest(version="9.9.9"):
    return {
        "version": version,
        "url": "https://dl.cloudsmith.io/example.tar.gz",
        "archive": "cloudsmith-9.9.9-macos-arm64.tar.gz",
        "sha256": "abc123",
    }


@contextlib.contextmanager
def upgrade_context(channel=installation.CHANNEL_PIP, manifest=None, target=None):
    manifest = manifest or make_manifest()
    with (
        mock.patch.object(
            update_check, "fetch_latest_manifest", return_value=manifest
        ) as fetch_mock,
        mock.patch.object(update_check, "write_cached_state") as cache_mock,
        mock.patch.object(installation, "detect_channel", return_value=channel),
        mock.patch.object(installation, "detect_target", return_value=target),
        mock.patch.object(self_update, "perform_self_update") as perform_mock,
    ):
        yield {"fetch": fetch_mock, "cache": cache_mock, "perform": perform_mock}


def invoke(runner, args=("upgrade",)):
    return runner.invoke(main_module.main, list(args), catch_exceptions=False)


def test_reports_up_to_date(runner):
    with upgrade_context(manifest=make_manifest(version="0.0.1")):
        result = invoke(runner)
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_prints_instruction_for_managed_channel(runner):
    with upgrade_context():
        result = invoke(runner)
    assert result.exit_code == 0
    assert "9.9.9" in result.output
    assert "pip install --upgrade cloudsmith-cli" in result.output


def test_self_updates_standalone(runner):
    manifest = make_manifest()
    with upgrade_context(
        channel=installation.CHANNEL_STANDALONE,
        manifest=manifest,
        target="macos-arm64",
    ) as mocks:
        result = invoke(runner)
    assert result.exit_code == 0
    mocks["perform"].assert_called_once_with(manifest)
    mocks["fetch"].assert_called_once_with(target="macos-arm64")
    assert "9.9.9" in result.output


def test_standalone_without_target_fails(runner):
    with upgrade_context(channel=installation.CHANNEL_STANDALONE, target=None):
        result = invoke(runner)
    assert result.exit_code != 0


def test_self_update_failure_reports_error(runner):
    with upgrade_context(
        channel=installation.CHANNEL_STANDALONE, target="macos-arm64"
    ) as mocks:
        mocks["perform"].side_effect = self_update.SelfUpdateError("disk full")
        result = invoke(runner)
    assert result.exit_code != 0
    assert "disk full" in result.output


def test_fetch_failure_reports_error(runner):
    with upgrade_context() as mocks:
        mocks["fetch"].side_effect = requests.ConnectionError("offline")
        result = invoke(runner)
    assert result.exit_code != 0


def test_json_output(runner):
    with upgrade_context():
        result = invoke(runner, ("upgrade", "-F", "json"))
    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert data["latest_version"] == "9.9.9"
    assert data["channel"] == "pip"


def test_update_alias(runner):
    with upgrade_context(manifest=make_manifest(version="0.0.1")):
        result = invoke(runner, ("update",))
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_refreshes_notifier_cache(runner):
    with upgrade_context() as mocks:
        invoke(runner)
    mocks["cache"].assert_called_once_with("9.9.9")


def test_invalid_manifest_version_reports_error(runner):
    with upgrade_context(manifest=make_manifest(version="not-semver")) as mocks:
        result = invoke(runner)
    assert result.exit_code != 0
    assert "Cannot compare versions" in result.output
    mocks["cache"].assert_not_called()


def test_cache_write_failure_is_ignored(runner):
    with upgrade_context() as mocks:
        mocks["cache"].side_effect = OSError("read-only")
        result = invoke(runner)
    assert result.exit_code == 0
