import json
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from ....cli.commands.update import update
from ....core import installation

_MOD = "cloudsmith_cli.cli.commands.update"

CURRENT = "1.26.0"
NEWER = "2.0.0"


def _manifest(version, **extra):
    manifest = {
        "version": version,
        "url": f"https://dl.example.com/cloudsmith-{version}.tar.gz",
        "sha256": "0" * 64,
    }
    manifest.update(extra)
    return manifest


def invoke_update(
    runner,
    *,
    channel,
    latest,
    target="linux-x86_64-gnu",
    args=None,
    manifest=None,
    self_update_supported=True,
):
    """Invoke the update command with all external effects mocked."""
    manifest = manifest or _manifest(latest)
    with ExitStack() as stack:
        stack.enter_context(patch(f"{_MOD}.get_version", return_value=CURRENT))
        stack.enter_context(
            patch(f"{_MOD}.installation.detect_channel", return_value=channel)
        )
        stack.enter_context(
            patch(f"{_MOD}.installation.detect_target", return_value=target)
        )
        stack.enter_context(
            patch(
                f"{_MOD}.installation.self_update_supported",
                return_value=self_update_supported,
            )
        )
        stack.enter_context(patch(f"{_MOD}.create_requests_session"))
        stack.enter_context(
            patch(
                f"{_MOD}.update_check.fetch_latest_manifest",
                return_value=manifest,
            )
        )
        record = stack.enter_context(
            patch(f"{_MOD}.update_check.record_checked_and_notified")
        )
        self_update = stack.enter_context(
            patch(f"{_MOD}.self_update.perform_self_update")
        )
        result = runner.invoke(update, args or [], catch_exceptions=False)
    return result, record, self_update


class TestUpToDate:
    def test_up_to_date_exits_zero(self, runner):
        result, record, self_update = invoke_update(
            runner, channel=installation.CHANNEL_PIP, latest=CURRENT
        )
        assert result.exit_code == 0
        assert "up to date" in result.output
        record.assert_called_once_with(CURRENT)
        self_update.assert_not_called()

    def test_up_to_date_json(self, runner):
        result, _record, _su = invoke_update(
            runner,
            channel=installation.CHANNEL_STANDALONE,
            latest=CURRENT,
            args=["-F", "json"],
        )
        payload = json.loads(result.output)["data"]
        assert payload["up_to_date"] is True
        assert payload["current_version"] == CURRENT
        assert payload["latest_version"] == CURRENT


class TestPackageManagerChannel:
    def test_prints_instruction(self, runner):
        result, record, self_update = invoke_update(
            runner, channel=installation.CHANNEL_PIP, latest=NEWER
        )
        assert result.exit_code == 0
        assert "pip install --upgrade cloudsmith-cli" in result.output
        record.assert_called_once_with(NEWER)
        self_update.assert_not_called()

    def test_json_has_upgrade_command(self, runner):
        result, _record, _su = invoke_update(
            runner,
            channel=installation.CHANNEL_HOMEBREW,
            latest=NEWER,
            args=["-F", "json"],
        )
        payload = json.loads(result.output)["data"]
        assert payload["channel"] == installation.CHANNEL_HOMEBREW
        assert "brew" in payload["upgrade_command"]


class TestStandaloneSelfUpdate:
    def test_self_update_with_yes(self, runner):
        result, record, self_update = invoke_update(
            runner,
            channel=installation.CHANNEL_STANDALONE,
            latest=NEWER,
            args=["--yes"],
        )
        assert result.exit_code == 0
        assert "now at version 2.0.0" in result.output
        record.assert_called_once_with(NEWER)
        self_update.assert_called_once()

    def test_prompt_declined(self, runner):
        # No --yes and no TTY forcing: patch stderr_is_tty True so the prompt
        # is actually shown, then feed "n".
        manifest = _manifest(NEWER)
        with ExitStack() as stack:
            stack.enter_context(patch(f"{_MOD}.get_version", return_value=CURRENT))
            stack.enter_context(
                patch(
                    f"{_MOD}.installation.detect_channel",
                    return_value=installation.CHANNEL_STANDALONE,
                )
            )
            stack.enter_context(
                patch(
                    f"{_MOD}.installation.detect_target",
                    return_value="linux-x86_64-gnu",
                )
            )
            stack.enter_context(
                patch(
                    f"{_MOD}.installation.self_update_supported",
                    return_value=True,
                )
            )
            stack.enter_context(patch(f"{_MOD}.create_requests_session"))
            stack.enter_context(
                patch(
                    f"{_MOD}.update_check.fetch_latest_manifest",
                    return_value=manifest,
                )
            )
            stack.enter_context(
                patch(f"{_MOD}.update_check.record_checked_and_notified")
            )
            stack.enter_context(
                patch(f"{_MOD}.update_check.stderr_is_tty", return_value=True)
            )
            self_update = stack.enter_context(
                patch(f"{_MOD}.self_update.perform_self_update")
            )
            result = runner.invoke(update, [], input="n\n", catch_exceptions=False)
        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()
        self_update.assert_not_called()

    def test_self_update_error_reported(self, runner):
        from ....core import self_update as su_mod

        manifest = _manifest(NEWER)
        with ExitStack() as stack:
            stack.enter_context(patch(f"{_MOD}.get_version", return_value=CURRENT))
            stack.enter_context(
                patch(
                    f"{_MOD}.installation.detect_channel",
                    return_value=installation.CHANNEL_STANDALONE,
                )
            )
            stack.enter_context(
                patch(
                    f"{_MOD}.installation.detect_target",
                    return_value="linux-x86_64-gnu",
                )
            )
            stack.enter_context(
                patch(
                    f"{_MOD}.installation.self_update_supported",
                    return_value=True,
                )
            )
            stack.enter_context(patch(f"{_MOD}.create_requests_session"))
            stack.enter_context(
                patch(
                    f"{_MOD}.update_check.fetch_latest_manifest",
                    return_value=manifest,
                )
            )
            stack.enter_context(
                patch(f"{_MOD}.update_check.record_checked_and_notified")
            )
            stack.enter_context(
                patch(
                    f"{_MOD}.self_update.perform_self_update",
                    side_effect=su_mod.SelfUpdateError("boom"),
                )
            )
            result = runner.invoke(update, ["--yes"])
        assert result.exit_code != 0
        assert "boom" in result.output


class TestStandaloneManualUpdate:
    """Windows standalone: no self-update; print the manifest URL + sha256."""

    def test_prints_url_and_sha_exits_zero(self, runner):
        manifest = _manifest(NEWER)
        result, _record, self_update = invoke_update(
            runner,
            channel=installation.CHANNEL_STANDALONE,
            latest=NEWER,
            target="windows-x86_64",
            manifest=manifest,
            self_update_supported=False,
        )
        assert result.exit_code == 0
        assert manifest["url"] in result.output
        assert manifest["sha256"] in result.output
        assert "Windows" in result.output
        self_update.assert_not_called()

    def test_json_outcome_manual(self, runner):
        manifest = _manifest(NEWER)
        result, _record, self_update = invoke_update(
            runner,
            channel=installation.CHANNEL_STANDALONE,
            latest=NEWER,
            target="windows-x86_64",
            manifest=manifest,
            self_update_supported=False,
            args=["-F", "json"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)["data"]
        assert payload["outcome"] == "manual"
        assert payload["download_url"] == manifest["url"]
        assert payload["sha256"] == manifest["sha256"]
        self_update.assert_not_called()


class TestChecksRegardlessOfState:
    def test_records_timestamps_even_when_up_to_date(self, runner):
        _result, record, _su = invoke_update(
            runner, channel=installation.CHANNEL_PIP, latest=CURRENT
        )
        record.assert_called_once_with(CURRENT)

    def test_standalone_without_target_errors(self, runner):
        result, _record, self_update = invoke_update(
            runner,
            channel=installation.CHANNEL_STANDALONE,
            latest=NEWER,
            target=None,
        )
        assert result.exit_code != 0
        assert "supported platform" in result.output
        self_update.assert_not_called()
