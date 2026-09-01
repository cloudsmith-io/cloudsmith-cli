from enum import Flag, auto
from typing import ClassVar

import pytest
from _pytest.mark.structures import ParameterSet

from cloudsmith_cli.core.utils import is_interactive, should_use_color


class Desired(Flag):
    NONE = 0
    COLOR = auto()
    INTERACTIVE = auto()


class TestTerminalColor:
    """Testing precedence in environment varaibles for controlling and overriding terminal
    colours"""

    env_tests: ClassVar[list[ParameterSet]] = [
        pytest.param({}, Desired.COLOR | Desired.INTERACTIVE, id="default behaviour"),
        pytest.param(
            {"NO_COLOR": ""},
            Desired.COLOR | Desired.INTERACTIVE,
            id="empty no color var",
        ),
        pytest.param({"CS_FORCE_TTY": "true"}, Desired.COLOR, id="force ANSI output"),
        pytest.param(
            {"NO_COLOR": "true", "CS_FORCE_TTY": "true"},
            Desired.NONE,
            id="force ANSI output, respects NO_COLOR",
        ),
        pytest.param({"TERM": "dumb"}, Desired.INTERACTIVE, id="no color enabled for TERM=dumb"),
        pytest.param(
            {"CI": "true"},
            Desired.COLOR,
            id="in a CI server, do not use interactive features",
        ),
        pytest.param(
            {
                "NO_COLOR": "true",
                "TERM": "dumb",
                "CS_FORCE_TTY": "true",
            },
            Desired.INTERACTIVE,
            id="test NO_COLOR always respected",
        ),
        pytest.param(
            {
                "TERM": "dumb",
                "CS_FORCE_TTY": "true",
            },
            Desired.COLOR | Desired.INTERACTIVE,
            id="ensure force tty respected over term dumb",
        ),
    ]

    @pytest.mark.parametrize("env,desired", env_tests)
    def test_no_color_environment_variables(self, env, desired):
        want_color = Desired.COLOR in desired
        assert should_use_color(env) == want_color, f"failed for environment: {env} wanted {desired}"

    @pytest.mark.parametrize("env,desired", env_tests)
    def test_no_interactive_environment_variables(self, env, desired):
        want_interactive = Desired.INTERACTIVE in desired
        assert is_interactive(env) == want_interactive, f"failed for environment {env} wanted {desired}"
