import pytest

from ...commands.main import main


@pytest.mark.parametrize(
    "args",
    [
        ["login"],
        ["token"],
        ["login", "-l", "you@example.com", "-p", "secret"],
        ["token", "-l", "you@example.com", "-p", "secret"],
        ["login", "--help"],
        ["token", "-h"],
    ],
)
def test_login_and_token_print_removal_notice(runner, args):
    result = runner.invoke(main, args)

    assert result.return_value == 1
    assert "'cloudsmith login'" in result.stderr
    assert "'cloudsmith token'" in result.stderr
    assert "no longer available" in result.stderr
    assert "CLOUDSMITH_API_KEY" in result.stderr
    assert "cloudsmith auth" in result.stderr
    assert result.stdout == ""


def test_help_lists_neither_login_nor_token(runner):
    result = runner.invoke(main, ["--help"])
    command_names = [line.split()[0] for line in result.stdout.splitlines() if line]

    assert result.exit_code == 0
    assert "tokens" in command_names
    assert not {"login", "token", "login|token"} & set(command_names)
