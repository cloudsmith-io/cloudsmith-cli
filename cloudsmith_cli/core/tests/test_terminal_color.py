from enum import Flag, auto
from typing import ClassVar
from unittest.mock import patch

import pytest

from cloudsmith_cli.core import utils
from cloudsmith_cli.core.utils import (
    ColorMode,
    TTYMode,
    color_enabled,
    controlling_terminal_mode,
    is_interactive,
)


class Desired(Flag):
    NONE = 0
    COLOR = auto()
    INTERACTIVE = auto()


class TestTerminalUISuppression:
    """Testing precedence in environment variables for controlling interactivity and colour"""

    env_tests: ClassVar[list] = [
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


class TestControllingTerminalMode:
    """Tests for the check that a prompt can reach a user."""

    def test_disabled_when_dev_tty_cannot_open(self):
        with (
            patch.object(utils.sys, "platform", "linux"),
            patch.object(utils, "open", side_effect=OSError, create=True),
        ):
            assert controlling_terminal_mode() is TTYMode.DISABLED

    @pytest.mark.parametrize(
        "platform,terminal", [("linux", "/dev/tty"), ("win32", "CONIN$")]
    )
    def test_enabled_when_the_terminal_opens(self, platform, terminal):
        with (
            patch.object(utils.sys, "platform", platform),
            patch.object(utils, "open", create=True) as open_mock,
        ):
            assert controlling_terminal_mode() is TTYMode.ENABLED
        assert open_mock.call_args.args[0] == terminal
