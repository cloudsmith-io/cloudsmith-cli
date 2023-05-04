# -*- coding: utf-8 -*-
import pytest
import six

from ....core.version import get_version_info, parse_version
from ...commands.main import PY2_DEPRECATION_WARNING_MSG, main


class TestMainCommand(object):
    @pytest.mark.parametrize("option", ["-V", "--version"])
    def test_main_version(self, runner, option):
        """Test the output of `cloudsmith --version`."""
        result = runner.invoke(main, [option, "--no-python-version-warning"])
        assert result.exit_code == 0
        assert (
            result.output == "Versions:\n"
            "CLI Package Version: 0.37.2\n"
            "API Package Version: 2.0.0\n"
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

        assert (PY2_DEPRECATION_WARNING_MSG in result.output) is expected
