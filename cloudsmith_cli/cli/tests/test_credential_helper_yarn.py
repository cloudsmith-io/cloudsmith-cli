# Copyright 2026 Cloudsmith Ltd
"""Tests for the installer of the Cloudsmith Yarn plugin."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import click.testing
import pytest

from ...cli.commands.credential_helper import manage
from ...credential_helpers import maven_tools
from ...credential_helpers.maven_tools import BuildToolError, ConfigFileConflict
from ...credential_helpers.yarn import installer
from ...credential_helpers.yarn.installer import PLUGIN_PATH, PLUGIN_URL, YarnInstaller

ENTRY = f"- path: {PLUGIN_PATH}\n"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Point the home directory at an empty directory."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.setattr(installer, "_download", lambda session: (b"plugin", "0.1.0"))
    return home_dir


@pytest.fixture()
def yarn_runs(tmp_path, monkeypatch):
    """Run in a project directory with a fake Yarn that records each command."""
    commands = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(installer.shutil, "which", lambda name: f"/bin/{name}")

    def fake_output(command, cwd=None, check=False):
        commands.append((command, cwd))
        return ""

    monkeypatch.setattr(maven_tools, "tool_output", fake_output)
    return commands


def test_install_loads_the_plugin_in_every_project(home):
    """A second install finds the plugin and the entry, and changes nothing."""
    assert YarnInstaller().install() == [
        f"wrote {home / PLUGIN_PATH} for version 0.1.0",
        f"added {PLUGIN_PATH} to the plugins in {home / '.yarnrc.yml'}",
    ]
    assert (home / ".yarnrc.yml").read_text() == f"plugins:\n  {ENTRY}"
    assert (home / PLUGIN_PATH).read_bytes() == b"plugin"
    assert "(no change)" in YarnInstaller().install()[0]


@pytest.mark.parametrize("indent", ["  ", "", "    # team plugins\n    "])
def test_install_adds_the_entry_to_the_plugins_of_the_user(home, indent):
    """The entry goes before the first item, with the indent of that item."""
    rc_file = home / ".yarnrc.yml"
    rc_file.write_text(f"plugins:\n{indent}- path: other.cjs\nnodeLinker: pnp")
    item_indent = indent.rpartition("\n")[2]

    YarnInstaller().install()

    assert rc_file.read_text() == (
        f"plugins:\n{indent}{ENTRY}{item_indent}- path: other.cjs\nnodeLinker: pnp\n"
    )


def test_install_with_plugins_on_one_line_fails(home):
    """The command does not rewrite a flow sequence, so it names the entry to add."""
    (home / ".yarnrc.yml").write_text("plugins: []\n")

    with pytest.raises(ConfigFileConflict, match=PLUGIN_PATH):
        YarnInstaller().install()


def test_dry_run_changes_nothing(home):
    assert YarnInstaller().install(dry_run=True)[0].startswith("would write")
    assert not any(home.iterdir())


def test_uninstall_removes_the_plugin_and_keeps_other_settings(home):
    """An empty plugins key goes too, and a second uninstall has nothing to remove."""
    rc_file = home / ".yarnrc.yml"
    rc_file.write_text("nodeLinker: pnp\n")
    YarnInstaller().install()

    YarnInstaller().uninstall()

    assert rc_file.read_text() == "nodeLinker: pnp\n"
    assert not (home / PLUGIN_PATH).exists()
    assert "(nothing to remove)" in YarnInstaller().uninstall()[0]


def test_uninstall_removes_the_files_and_directories_that_install_created(home):
    YarnInstaller().install()

    YarnInstaller().uninstall()

    assert not any(home.iterdir())


def test_uninstall_removes_a_hand_written_entry_and_keeps_other_plugins(home):
    """The whole item goes, and the plugins key stays while it has an item."""
    rc_file = home / ".yarnrc.yml"
    rc_file.write_text(
        f'plugins:\n# keep\n- path: "{PLUGIN_PATH}"  # mine\n'
        "- path: other.cjs\nnodeLinker: pnp\n"
    )

    YarnInstaller().uninstall()

    assert (
        rc_file.read_text() == "plugins:\n# keep\n- path: other.cjs\nnodeLinker: pnp\n"
    )


def test_install_and_uninstall_change_only_the_plugins_list(home):
    """A quoted plugins key is the same key, and the path under another setting is not an entry."""
    rc_file = home / ".yarnrc.yml"
    other_setting = f"changesetIgnorePatterns:\n  {ENTRY}"
    rc_file.write_text(f'"plugins":\n  - path: other.cjs\n{other_setting}')

    YarnInstaller().install()
    assert rc_file.read_text() == (
        f'"plugins":\n  {ENTRY}  - path: other.cjs\n{other_setting}'
    )
    YarnInstaller().uninstall()
    assert rc_file.read_text() == f'"plugins":\n  - path: other.cjs\n{other_setting}'


@pytest.mark.parametrize("command", ["install", "uninstall"])
@pytest.mark.parametrize(
    "rc_text",
    [
        f"plugins:\n  - path: {PLUGIN_PATH}\n\n    spec: url\n",
        f"plugins: [{{path: {PLUGIN_PATH}}}]\n",
        f"plugins:\n  - {{path: {PLUGIN_PATH}}}\n",
        f"plugins:\n  {ENTRY}  - checksum: abc\n    path: {PLUGIN_PATH}\n",
    ],
)
def test_an_entry_in_another_form_changes_nothing(home, command, rc_text):
    """The command names the file, and keeps the plugin that the file still loads."""
    (home / ".yarnrc.yml").write_text(rc_text)
    (home / PLUGIN_PATH).parent.mkdir(parents=True)
    (home / PLUGIN_PATH).write_bytes(b"plugin")

    with pytest.raises(ConfigFileConflict, match=".yarnrc.yml"):
        getattr(YarnInstaller(), command)()

    assert (home / ".yarnrc.yml").read_text() == rc_text
    assert (home / PLUGIN_PATH).exists()


def test_install_does_not_save_a_page_that_is_not_the_plugin():
    """A proxy can answer with its own page, which would stop Yarn in every project."""
    page = Mock(content=b"<html>", url=PLUGIN_URL)

    with pytest.raises(OSError, match="proxy"):
        installer._download(Mock(get=Mock(return_value=page)))


def test_list_finds_the_project_that_loads_the_plugin(home, tmp_path, monkeypatch):
    """Yarn reads .yarnrc.yml from the parent directories, and an unused bundle does not count."""
    for project, rc_text in (
        ("app", f"plugins:\n  - checksum: abc\n    path: {PLUGIN_PATH}\n"),
        ("old", f"plugins:\n  # - path: {PLUGIN_PATH}\n"),
    ):
        (tmp_path / project / PLUGIN_PATH).parent.mkdir(parents=True)
        (tmp_path / project / PLUGIN_PATH).write_bytes(b"plugin")
        (tmp_path / project / ".yarnrc.yml").write_text(rc_text)
        (tmp_path / project / "packages").mkdir()

    monkeypatch.chdir(tmp_path / "app" / "packages")
    assert YarnInstaller().status()["launcher"] == str(tmp_path / "app" / PLUGIN_PATH)
    monkeypatch.chdir(tmp_path / "old" / "packages")
    assert YarnInstaller().status()["launcher"] is None


def test_list_with_an_unreadable_yarnrc_shows_no_plugin(home):
    (home / ".yarnrc.yml").mkdir()

    assert YarnInstaller().status()["launcher"] is None


def test_install_local_hands_off_to_yarn(home, yarn_runs, tmp_path):
    YarnInstaller().install(local=True)

    assert yarn_runs == [(["/bin/yarn", "plugin", "import", PLUGIN_URL], tmp_path)]


@pytest.mark.parametrize(
    "yarn_answer",
    [
        BuildToolError("isn't referenced by the current configuration"),
        # Yarn removes nothing when only ~/.yarnrc.yml loads the plugin.
        "➤ YN0000: Updating the configuration...\n",
    ],
)
def test_uninstall_local_with_no_plugin_has_nothing_to_remove(
    home, yarn_runs, monkeypatch, yarn_answer
):
    def answer(command, cwd=None, check=False):
        if isinstance(yarn_answer, Exception):
            raise yarn_answer
        return yarn_answer

    monkeypatch.setattr(maven_tools, "tool_output", answer)

    assert "(nothing to remove)" in YarnInstaller().uninstall(local=True)[0]


def test_install_local_in_a_yarn_1_project_names_the_fix(home, yarn_runs, monkeypatch):
    def yarn_1(command, cwd=None, check=False):
        raise BuildToolError('error Command "plugin" not found.')

    monkeypatch.setattr(maven_tools, "tool_output", yarn_1)

    with pytest.raises(BuildToolError, match="yarn set version stable"):
        YarnInstaller().install(local=True)


def test_local_error_has_no_javascript_stack(home, yarn_runs, monkeypatch):
    def no_project(command, cwd=None, check=False):
        raise BuildToolError("UsageError: No project found\n    at Ft (yarn.js:1:2)\n")

    monkeypatch.setattr(maven_tools, "tool_output", no_project)

    with pytest.raises(BuildToolError) as error:
        YarnInstaller().install(local=True)
    assert str(error.value) == "UsageError: No project found\n"


def test_local_without_yarn_fails(home, yarn_runs, monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", lambda name: None)

    with pytest.raises(BuildToolError, match="corepack enable"):
        YarnInstaller().install(local=True)


def test_tool_output_with_check_raises_with_the_output():
    command = [sys.executable, "-c", "print('boom'); raise SystemExit(3)"]

    with pytest.raises(BuildToolError, match="boom"):
        maven_tools.tool_output(command, check=True)


def test_cli_install_shows_the_next_steps(home):
    result = click.testing.CliRunner().invoke(
        manage.install_cmd, ["yarn", "--no-discover"], catch_exceptions=False
    )

    assert result.exit_code == 0, result.output
    assert "yarn plugin runtime" in result.output
