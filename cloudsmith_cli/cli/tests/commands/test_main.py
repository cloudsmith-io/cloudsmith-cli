# -*- coding: utf-8 -*-
import pytest
import six

from ....core.api.version import get_version as get_api_version
from ....core.version import get_version, get_version_info, parse_version
from ...commands.main import PY2_DEPRECATION_WARNING_MSG, main


class TestMainCommand(object):
    @pytest.mark.parametrize("option", ["-V", "--version"])
    def test_main_version(self, runner, option):
        """Test the output of `cloudsmith --version`."""
        result = runner.invoke(main, [option, "--no-python-version-warning"])
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

    @pytest.mark.parametrize("suppress_warning", [True, False])
    def test_py2_deprecation_warning(self, runner, suppress_warning):
        """Test Python 2 support deprecation warning."""
        expected = (
            six.PY2
            and (not suppress_warning)
            and (not (get_version_info() >= parse_version("1.0.0")))
        )
        args = []
        if suppress_warning:
            args.append("--no-python-version-warning")

        result = runner.invoke(main, args=args)

        # Click raises ValueError when result.stderr is accessed
        # and result.stderr_bytes hasn't been set.
        # This assertion can be simplified when we upgrade click.
        # https://github.com/pallets/click/pull/1194
        if expected:
            assert PY2_DEPRECATION_WARNING_MSG in result.stderr
        else:
            assert not result.stderr_bytes

        assert PY2_DEPRECATION_WARNING_MSG not in result.stdout
