"""Update notice wiring - Tests."""

from unittest import mock

from ...core import update_check
from ..commands import main as main_module


def test_main_arms_update_check(runner):
    with mock.patch.object(update_check, "arm") as arm_mock:
        result = runner.invoke(main_module.main, ["--version"], catch_exceptions=False)
    assert result.exit_code == 0
    arm_mock.assert_called_once()


def test_update_check_stays_silent_without_tty(runner):
    with mock.patch.object(
        update_check, "start_background_check_if_stale"
    ) as start_mock:
        result = runner.invoke(main_module.main, ["--version"], catch_exceptions=False)
    assert result.exit_code == 0
    start_mock.assert_not_called()
