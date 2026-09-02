from enum import Flag, auto
from typing import ClassVar

import pytest
from _pytest.mark.structures import ParameterSet

from cloudsmith_cli.core.utils import (
    color_enabled,
    is_interactive,
    TTYMode,
    ColorMode,
)


class Desired(Flag):
    NONE = 0
    COLOR = auto()
    INTERACTIVE = auto()


class TestTerminalUISuppression:
    """Testing precedence in environment varaibles for controlling and overriding terminal
    colours"""

    env_tests: ClassVar[list[ParameterSet]] = [
        pytest.param(
            {},
            ColorMode.AUTO,
            TTYMode.ENABLED,
            Desired.COLOR | Desired.INTERACTIVE,
            id="default behaviour",
        ),
        pytest.param(
            {},
            ColorMode.NEVER,
            TTYMode.DISABLED,
            Desired.NONE,
            id="force disable tty and color mode",
        ),
        pytest.param(
            {"NO_COLOR": ""},
            ColorMode.AUTO,
            TTYMode.ENABLED,
            Desired.COLOR | Desired.INTERACTIVE,
            id="empty no color var",
        ),
        pytest.param(
            {"CLOUDSMITH_FORCE_COLOR": "true"},
            ColorMode.AUTO,
            TTYMode.ENABLED,
            Desired.COLOR | Desired.INTERACTIVE,
            id="force ANSI output",
        ),
        pytest.param(
            {"NO_COLOR": "true", "CLOUDSMITH_FORCE_COLOR": "true"},
            ColorMode.AUTO,
            TTYMode.ENABLED,
            Desired.INTERACTIVE,
            id="force ANSI output, respects NO_COLOR",
        ),
        pytest.param(
            {"TERM": "dumb"},
            ColorMode.AUTO,
            TTYMode.ENABLED,
            Desired.INTERACTIVE,
            id="no color enabled for TERM=dumb",
        ),
        pytest.param(
            {"CI": "true"},
            ColorMode.AUTO,
            TTYMode.ENABLED,
            Desired.COLOR,
            id="in a CI server, do not use interactive features",
        ),
        pytest.param(
            {"CI": "true", "NO_COLOR": "true"},
            ColorMode.AUTO,
            TTYMode.ENABLED,
            Desired.NONE,
            id="suppress interactivity and colour",
        ),
        pytest.param(
            {
                "NO_COLOR": "true",
                "TERM": "dumb",
                "CLOUDSMITH_FORCE_COLOR": "true",
            },
            ColorMode.AUTO,
            TTYMode.ENABLED,
            Desired.INTERACTIVE,
            id="test NO_COLOR always respected",
        ),
        pytest.param(
            {
                "TERM": "dumb",
                "CLOUDSMITH_FORCE_COLOR": "true",
            },
            ColorMode.AUTO,
            TTYMode.ENABLED,
            Desired.COLOR | Desired.INTERACTIVE,
            id="ensure force tty respected over term dumb",
        ),
    ]

    @pytest.mark.parametrize("env,colorMode,ttyMode,desired", env_tests)
    def test_no_color_environment_variables(
        self,
        env: dict[str, str],
        colorMode: ColorMode,
        ttyMode: TTYMode,
        desired: Desired,
    ):
        want_color = Desired.COLOR in desired
        assert color_enabled(env, colorMode, ttyMode) == want_color, (
            f"colour suppression check failed for environment: {env} wanted {desired}"
        )

    @pytest.mark.parametrize("env,colorMode,ttyMode,desired", env_tests)
    def test_no_interactive_environment_variables(
        self, env, colorMode, ttyMode, desired
    ):
        want_interactive = Desired.INTERACTIVE in desired
        assert is_interactive(env, ttyMode) == want_interactive, (
            f"interactive suppression check failed for environment {env} wanted {desired}"
        )
