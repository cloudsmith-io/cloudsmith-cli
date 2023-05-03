import pytest

from ...commands.main import main


class TestMainCommand(object):

    @pytest.mark.parametrize("option", ["-V", "--version"])
    def test_main_version(self, runner, option):
        """Test the output of `cloudsmith --version`."""
        result = runner.invoke(main, [option])
        assert result.exit_code == 0
        assert result.output == "Versions:\n" \
                                "CLI Package Version: 0.37.2\n" \
                                "API Package Version: 2.0.0\n"

    @pytest.mark.parametrize("option", ["-h", "--help"])
    def test_main_help(self, runner, option):
        """Test the output of `cloudsmith --help`."""
        result = runner.invoke(main, [option])
        assert result.exit_code == 0
        # TODO: assert something specific about output
        assert result.output
