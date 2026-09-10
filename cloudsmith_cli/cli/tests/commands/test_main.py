import json

import pytest

from ....core import update_check
from ....core.api.version import get_version as get_api_version
from ....core.version import get_version
from ...commands.main import main


class TestMainCommand:
    @pytest.mark.parametrize("option", ["-V", "--version"])
    def test_main_version(self, runner, option):
        """Test the output of `cloudsmith --version`."""
        result = runner.invoke(main, [option])
        assert result.exit_code == 0
        assert (
            result.output == "Versions:\n"
            "CLI Package Version: " + get_version() + "\n"
            "API Package Version: " + get_api_version() + "\n"
        )

    @pytest.mark.parametrize("option", ["-V", "--version"])
    @pytest.mark.parametrize(
        "format_option,format_value",
        [("-F", "json"), ("--output-format", "json")],
    )
    def test_main_version_json(self, runner, option, format_option, format_value):
        """Test the JSON output of `cloudsmith --version --output-format json`."""
        result = runner.invoke(main, [option, format_option, format_value])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert "data" in output
        assert output["data"]["cli_version"] == get_version()
        assert output["data"]["api_version"] == get_api_version()

    @pytest.mark.parametrize("option", ["-V", "--version"])
    def test_main_version_pretty_json(self, runner, option):
        """Test the pretty JSON output of `cloudsmith --version --output-format pretty_json`."""
        result = runner.invoke(main, [option, "--output-format", "pretty_json"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert "data" in output
        assert output["data"]["cli_version"] == get_version()
        assert output["data"]["api_version"] == get_api_version()
        # Verify it's formatted with indentation
        assert "    " in result.output

    @pytest.mark.parametrize("option", ["-h", "--help"])
    def test_main_help(self, runner, option):
        """Test the output of `cloudsmith --help`."""
        result = runner.invoke(main, [option])
        assert result.exit_code == 0
        # TODO: assert something specific about output
        assert result.output


class TestMainUpdateNotice:
    """The update notice is wired through `arm` on the top-level group."""

    @pytest.fixture
    def state_file(self, tmp_path, monkeypatch):
        """Point the state file at a temp path and behave like an interactive TTY."""
        import semver

        path = str(tmp_path / "update_check.json")
        monkeypatch.setattr(update_check, "get_state_file_path", lambda: path)
        monkeypatch.setattr(update_check, "stderr_is_tty", lambda: True)
        monkeypatch.setattr(
            update_check.version,
            "get_version_info",
            lambda: semver.VersionInfo.parse("1.26.0"),
        )
        monkeypatch.setattr(update_check.version, "get_version", lambda: "1.26.0")
        return path

    def _write_behind(self, path):
        # Stale check (so a check is due) + never notified + a newer version:
        # arm re-arms by bumping last_checked_at, close notifies.
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"last_checked_at": 1000.0, "latest_version": "9.9.9"}, f)

    def test_notice_prints_when_behind(self, runner, state_file):
        """A stale + behind state prints the notice at command close."""
        self._write_behind(state_file)
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "9.9.9" in result.output
        assert "cloudsmith update" in result.output

    def test_no_check_update_flag_suppresses(self, runner, state_file):
        self._write_behind(state_file)
        result = runner.invoke(main, ["--no-check-update", "--version"])
        assert result.exit_code == 0
        assert "9.9.9" not in result.output

    def test_json_output_suppresses(self, runner, state_file):
        self._write_behind(state_file)
        result = runner.invoke(main, ["-F", "json", "--version"])
        assert result.exit_code == 0
        assert "9.9.9" not in result.output
        # stdout stays valid JSON.
        json.loads(result.output)

    def test_no_network_when_behind(self, runner, state_file, monkeypatch):
        """Being behind must not trigger a fetch."""

        def boom(*args, **kwargs):
            raise AssertionError("fetch must not run when already behind")

        monkeypatch.setattr(update_check, "run_background_check", boom)
        self._write_behind(state_file)
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "9.9.9" in result.output

    def test_notifies_from_cache_when_no_fetch_due(self, runner, state_file):
        """Notice fires from cache even when the check is fresh (not due).

        Regression: a prior suppressed run may have fetched (advancing
        last_checked_at) without notifying. The next interactive run must still
        speak, driven purely by last_notified_at < last_checked_at.
        """
        with open(state_file, "w", encoding="utf-8") as f:
            # Fresh check (not due) + newer version + never notified.
            json.dump(
                {
                    "last_checked_at": 9_999_999_999.0,
                    "latest_version": "9.9.9",
                },
                f,
            )
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "9.9.9" in result.output
        # last_notified_at now stamped → throttled next time.
        with open(state_file, encoding="utf-8") as f:
            assert "last_notified_at" in json.load(f)

    def test_json_run_still_fetches(self, runner, state_file, monkeypatch):
        """-F json suppresses the notice but the daily fetch still runs."""
        calls = []

        def fake_fetch(session, now=None):
            calls.append(True)
            update_check.record_check("9.9.9", now=now)

        monkeypatch.setattr(update_check, "run_background_check", fake_fetch)
        # No state file → a fetch is due; JSON silences only the notice.
        result = runner.invoke(main, ["-F", "json", "--version"])
        assert result.exit_code == 0
        assert calls == [True]
        assert "9.9.9" not in result.output
        json.loads(result.output)
