"""Tests for the `cloudsmith list` subcommands."""

from ....cli.commands.main import main


def test_list_deps_help_shows_dependencies_summary(runner):
    result = runner.invoke(main, ["list", "deps", "--help"])

    assert result.exit_code == 0
    assert "dependencies" in result.stdout.split("\n\n")[1]
