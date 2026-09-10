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
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"last_check_at": 1000.0, "latest_version": "9.9.9"}, f)

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
