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

    @pytest.mark.parametrize("option", ["-h", "--help"])
    def test_main_help(self, runner, option):
        """Test the output of `cloudsmith --help`."""
        result = runner.invoke(main, [option])
        assert result.exit_code == 0
        # TODO: assert something specific about output
        assert result.output
