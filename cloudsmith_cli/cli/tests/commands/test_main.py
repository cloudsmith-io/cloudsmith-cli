import json

import pytest

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
