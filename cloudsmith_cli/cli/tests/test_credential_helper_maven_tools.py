# Copyright 2026 Cloudsmith Ltd
"""Tests for the Maven, Gradle, and sbt installers of the Cloudsmith Maven tools.

The installers configure each build tool to load the Cloudsmith extension or
plugin, which gets its credential from `cloudsmith credential-helper generic`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import click.testing
import httpretty
import httpretty.core
import pytest

from ...credential_helpers import maven_tools
from ...credential_helpers.gradle.installer import GradleInstaller
from ...credential_helpers.maven import extensions, mavenrc
from ...credential_helpers.maven import installer as maven_installer
from ...credential_helpers.maven.installer import MavenInstaller
from ...credential_helpers.maven_tools import InstallOptionError, ProjectNotFound
from ...credential_helpers.sbt.installer import SbtInstaller

EXTENSION_PATH = "io/cloudsmith/cloudsmith-maven-extension"
METADATA = """<?xml version="1.0" encoding="utf-8"?>
<metadata>
  <groupId>io.cloudsmith</groupId>
  <artifactId>cloudsmith-maven-extension</artifactId>
  <versioning>
    <latest>0.3.0-SNAPSHOT</latest>
    <release>0.2.0</release>
    <versions><version>0.1.0</version><version>0.2.0</version></versions>
  </versioning>
</metadata>
"""
OUR_EXTENSION = """  <extension>
    <groupId>io.cloudsmith</groupId>
    <artifactId>cloudsmith-maven-extension</artifactId>
    <version>0.1.0</version>
  </extension>
"""
OTHER_EXTENSION = """  <extension>
    <groupId>kr.motd.maven</groupId>
    <artifactId>os-maven-plugin</artifactId>
    <version>1.7.1</version>
  </extension>
"""


@pytest.fixture(autouse=True)
def _fake_socket_shutdown(monkeypatch):
    monkeypatch.setattr(
        httpretty.core.fakesock.socket,
        "shutdown",
        lambda self, how: None,
        raising=False,
    )


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Point the home directory at an empty directory."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.delenv("GRADLE_USER_HOME", raising=False)
    return home_dir


@pytest.fixture()
def fake_repository(monkeypatch):
    """Serve version 0.2.0 of every artifact without network access."""
    downloads = []

    def fake_download(artifact_path, destination, session=None):
        downloads.append(artifact_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"content of {artifact_path}", encoding="utf-8")

    monkeypatch.setattr(
        maven_tools, "latest_version", lambda artifact_path, session=None: "0.2.0"
    )
    monkeypatch.setattr(maven_tools, "download", fake_download)
    return downloads


@pytest.fixture(autouse=True)
def _maven_3_10(monkeypatch):
    """Run as if `mvn -v` reports Maven 3.10.0."""
    monkeypatch.setattr(maven_installer, "_maven_version", lambda: "3.10.0")


@pytest.fixture()
def outside_projects(tmp_path, monkeypatch):
    """Run the test from a directory that is not in a project."""
    directory = tmp_path / "work"
    directory.mkdir()
    monkeypatch.chdir(directory)
    return directory


@pytest.fixture()
def maven_project(tmp_path, monkeypatch):
    """Make a Maven project and run the test from its root directory."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pom.xml").write_text("<project/>", encoding="utf-8")
    monkeypatch.chdir(project)
    return project


# ---------------------------------------------------------------------------
# 1. The public maven-tools repository
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_latest_version_reads_the_release_from_the_metadata():
    """The release version is used, not a newer snapshot in <latest>."""
    httpretty.register_uri(
        httpretty.GET,
        f"{maven_tools.REPOSITORY_URL}{EXTENSION_PATH}/maven-metadata.xml",
        body=METADATA,
    )

    assert maven_tools.latest_version(EXTENSION_PATH) == "0.2.0"


def test_latest_version_uses_the_given_session():
    """The install command's proxy and TLS settings reach the download."""
    session = Mock()
    session.get.return_value.content = METADATA.encode()

    assert maven_tools.latest_version(EXTENSION_PATH, session) == "0.2.0"
    session.get.assert_called_once_with(
        f"{maven_tools.REPOSITORY_URL}{EXTENSION_PATH}/maven-metadata.xml",
        timeout=maven_tools.TIMEOUT_SECONDS,
    )


@httpretty.activate(allow_net_connect=False)
def test_latest_version_fails_with_an_os_error_when_the_artifact_is_missing():
    """A missing artifact is an OSError, which the install command reports."""
    httpretty.register_uri(
        httpretty.GET,
        f"{maven_tools.REPOSITORY_URL}{EXTENSION_PATH}/maven-metadata.xml",
        status=404,
    )

    with pytest.raises(OSError):
        maven_tools.latest_version(EXTENSION_PATH)


@httpretty.activate(allow_net_connect=False)
def test_download_writes_the_file(tmp_path):
    """The file is written to the destination, and missing directories are made."""
    httpretty.register_uri(
        httpretty.GET,
        f"{maven_tools.REPOSITORY_URL}{EXTENSION_PATH}/0.2.0/extension.jar",
        body=b"jar bytes",
    )
    destination = tmp_path / "a" / "b" / "extension.jar"

    maven_tools.download(f"{EXTENSION_PATH}/0.2.0/extension.jar", destination)

    assert destination.read_bytes() == b"jar bytes"


# ---------------------------------------------------------------------------
# 2. .mvn/extensions.xml
# ---------------------------------------------------------------------------


def test_add_extension_makes_a_new_file():
    """Without a file, the result lists only the Cloudsmith extension."""
    text, changed = extensions.add_extension(None, "0.1.0")

    assert changed is True
    assert text == f"<extensions>\n{OUR_EXTENSION}</extensions>\n"


def test_add_extension_keeps_other_extensions():
    """The Cloudsmith extension is added after the extensions already listed."""
    existing = f'<?xml version="1.0"?>\n<extensions>\n{OTHER_EXTENSION}</extensions>\n'

    text, changed = extensions.add_extension(existing, "0.1.0")

    assert changed is True
    assert text == (
        f'<?xml version="1.0"?>\n<extensions>\n{OTHER_EXTENSION}{OUR_EXTENSION}'
        "</extensions>\n"
    )


def test_add_extension_to_an_empty_element():
    """A self-closing <extensions/> element is opened to hold the extension."""
    text, changed = extensions.add_extension("<extensions/>\n", "0.1.0")

    assert changed is True
    assert text == f"<extensions>\n{OUR_EXTENSION}</extensions>\n"


def test_add_extension_updates_the_version():
    """An older version of the Cloudsmith extension is changed in place."""
    existing = f"<extensions>\n{OUR_EXTENSION}{OTHER_EXTENSION}</extensions>\n"

    text, changed = extensions.add_extension(existing, "0.2.0")

    assert changed is True
    assert text == existing.replace(
        "<version>0.1.0</version>", "<version>0.2.0</version>"
    )


def test_add_extension_with_the_same_version_changes_nothing():
    """Installing the same version again leaves the file as it is."""
    existing = f"<extensions>\n{OUR_EXTENSION}</extensions>\n"

    assert extensions.add_extension(existing, "0.1.0") == (existing, False)


def test_add_extension_ignores_a_commented_out_extension():
    """A Cloudsmith extension in a comment is not active, so a new entry is added."""
    comment = f"  <!--\n{OUR_EXTENSION}  -->\n"
    existing = f"<extensions>\n{comment}</extensions>\n"

    text, changed = extensions.add_extension(existing, "0.2.0")

    assert changed is True
    assert text == (
        f"<extensions>\n{comment}"
        f"{OUR_EXTENSION.replace('0.1.0', '0.2.0')}</extensions>\n"
    )


def test_add_extension_finds_the_extension_with_spaces_in_the_tags():
    """Maven trims the values, so spaces inside a tag do not make a second entry."""
    spaced = OUR_EXTENSION.replace(
        "<groupId>io.cloudsmith</groupId>", "<groupId> io.cloudsmith </groupId>"
    )
    existing = f"<extensions>\n{spaced}</extensions>\n"

    text, changed = extensions.add_extension(existing, "0.2.0")

    assert changed is True
    assert text == existing.replace(
        "<version>0.1.0</version>", "<version>0.2.0</version>"
    )


def test_add_extension_ignores_a_version_in_a_comment():
    """Only the <version> element of the extension changes."""
    existing = f"<extensions>\n{OUR_EXTENSION}</extensions>\n".replace(
        "  <extension>\n", "  <extension>\n    <!-- <version>0.0.1</version> -->\n"
    )

    text, _ = extensions.add_extension(existing, "0.2.0")

    assert "<!-- <version>0.0.1</version> -->" in text
    assert "<version>0.2.0</version>" in text


def test_remove_extension_ignores_a_commented_out_extension():
    """A commented-out entry is not removed, and does not count as another extension."""
    comment = f"  <!--\n{OTHER_EXTENSION}  -->\n"

    assert extensions.remove_extension(
        f"<extensions>\n{comment}{OUR_EXTENSION}</extensions>\n"
    ) == (None, True)
    assert extensions.remove_extension(f"<extensions>\n{comment}</extensions>\n") == (
        f"<extensions>\n{comment}</extensions>\n",
        False,
    )


def test_remove_extension_keeps_other_extensions():
    """Only the Cloudsmith extension is removed."""
    existing = f"<extensions>\n{OTHER_EXTENSION}{OUR_EXTENSION}</extensions>\n"

    text, changed = extensions.remove_extension(existing)

    assert changed is True
    assert text == f"<extensions>\n{OTHER_EXTENSION}</extensions>\n"


def test_remove_the_only_extension_returns_no_text():
    """When nothing else is listed, the file is not needed."""
    assert extensions.remove_extension(
        f"<extensions>\n{OUR_EXTENSION}</extensions>\n"
    ) == (None, True)


def test_remove_extension_without_the_extension_changes_nothing():
    """A file without the Cloudsmith extension stays as it is."""
    existing = f"<extensions>\n{OTHER_EXTENSION}</extensions>\n"

    assert extensions.remove_extension(existing) == (existing, False)


def _spaced_tags(extension: str) -> str:
    return extension.replace("<extension>", "<extension >").replace(
        "</extension>", "</extension\n  >"
    )


def test_remove_extension_keeps_an_extension_with_spaces_in_its_tags():
    """XML allows spaces before the > of a tag, so the other extension still counts."""
    other = _spaced_tags(OTHER_EXTENSION)

    assert extensions.remove_extension(
        f"<extensions>\n{OUR_EXTENSION}{other}</extensions>\n"
    ) == (f"<extensions>\n{other}</extensions>\n", True)


def test_remove_extension_keeps_a_file_that_cannot_be_parsed():
    """When the rest of the file is not valid XML, the file stays."""
    broken = "  <extension>\n    <groupId>kr.motd.maven</groupId>\n"
    existing = f"<extensions>\n{OUR_EXTENSION}{broken}</extensions>\n"

    assert extensions.remove_extension(existing) == (
        f"<extensions>\n{broken}</extensions>\n",
        True,
    )


def test_add_extension_finds_the_extension_with_spaces_in_its_tags():
    """An entry with spaces in its tags is updated, not listed a second time."""
    existing = f"<extensions>\n{_spaced_tags(OUR_EXTENSION)}</extensions>\n"

    text, changed = extensions.add_extension(existing, "0.2.0")

    assert changed is True
    assert text == existing.replace(
        "<version>0.1.0</version>", "<version>0.2.0</version>"
    )


# ---------------------------------------------------------------------------
# 3. ~/.mavenrc
# ---------------------------------------------------------------------------

JAR = Path("/home/me/.m2/repository/cloudsmith-maven-extension-0.2.0.jar")
BLOCK = (
    "# >>> cloudsmith credential-helper install maven >>>\n"
    f'MAVEN_OPTS="$MAVEN_OPTS -Dmaven.ext.class.path={JAR}"\n'
    "# <<< cloudsmith credential-helper install maven <<<\n"
)


def test_add_block_makes_a_new_file():
    """Without a file, the result is only the block."""
    assert mavenrc.add_block(None, JAR) == (BLOCK, True)


def test_add_block_keeps_the_existing_lines():
    """The block goes after the lines of the user, after a blank line."""
    existing = 'export JAVA_HOME="/opt/java"'

    assert mavenrc.add_block(existing, JAR) == (f"{existing}\n\n{BLOCK}", True)


def test_add_block_replaces_an_older_block_in_place():
    """An upgrade changes the block, and the lines around it stay as they are."""
    older = BLOCK.replace("0.2.0", "0.1.0")

    assert mavenrc.add_block(f"export A=1\n\n{older}export B=2\n", JAR) == (
        f"export A=1\n\n{BLOCK}export B=2\n",
        True,
    )


def test_add_block_with_the_same_jar_changes_nothing():
    """Installing the same version again leaves the file as it is."""
    existing = f"export A=1\n\n{BLOCK}"

    assert mavenrc.add_block(existing, JAR) == (existing, False)


def test_remove_block_keeps_the_other_lines():
    """Only the block, and the blank line that install added before it, go."""
    assert mavenrc.remove_block(f"export A=1\n\n{BLOCK}export B=2\n") == (
        "export A=1\nexport B=2\n",
        True,
    )


def test_remove_the_only_block_returns_no_text():
    """When nothing else is in the file, the file is not needed."""
    assert mavenrc.remove_block(BLOCK) == (None, True)


def test_remove_block_without_a_block_changes_nothing():
    """A file without the block stays as it is."""
    assert mavenrc.remove_block("export A=1\n") == ("export A=1\n", False)


# ---------------------------------------------------------------------------
# 4. MavenInstaller
# ---------------------------------------------------------------------------


def _local_extension_dir(home: Path, version: str) -> Path:
    return home / ".m2" / "repository" / EXTENSION_PATH / version


def _user_extensions(home: Path) -> Path:
    return home / ".m2" / "extensions.xml"


def test_maven_install_puts_the_extension_in_the_local_repository(
    home, fake_repository, outside_projects
):
    """Maven loads build extensions only from Maven Central or the local repository."""
    actions = MavenInstaller().install()

    version_dir = _local_extension_dir(home, "0.2.0")
    assert (version_dir / "cloudsmith-maven-extension-0.2.0.jar").exists()
    assert (version_dir / "cloudsmith-maven-extension-0.2.0.pom").exists()
    assert any(str(version_dir) in action for action in actions)


def test_maven_install_turns_on_the_extension_for_every_build(
    home, fake_repository, outside_projects
):
    """By default, ~/.m2/extensions.xml lists the extension for Maven 3.10 and later."""
    actions = MavenInstaller().install()

    text = _user_extensions(home).read_text(encoding="utf-8")
    assert "<version>0.2.0</version>" in text
    assert not (outside_projects / ".mvn").exists()
    assert not [action for action in actions if action.startswith("WARNING")]


def test_maven_install_warns_when_maven_ignores_user_extensions(
    home, fake_repository, outside_projects, monkeypatch
):
    """Maven 3.9 and earlier ignore ~/.m2/extensions.xml, so install names the options."""
    monkeypatch.setattr(maven_installer, "_maven_version", lambda: "3.9.11")

    actions = MavenInstaller().install()

    warnings = [action for action in actions if action.startswith("WARNING")]
    assert len(warnings) == 1
    assert "3.9.11" in warnings[0]
    assert "--local" in warnings[0]
    assert "--mavenrc" in warnings[0]
    assert _user_extensions(home).exists()


def test_maven_install_marks_the_files_as_installed(
    home, fake_repository, outside_projects
):
    """Maven does not load an extension that it records as downloaded from a repository."""
    version_dir = _local_extension_dir(home, "0.2.0")
    version_dir.mkdir(parents=True)
    for file_type in ("jar", "pom"):
        file_name = f"cloudsmith-maven-extension-0.2.0.{file_type}"
        (version_dir / file_name).write_text("from a repository", encoding="utf-8")
    (version_dir / "_remote.repositories").write_text(
        "#NOTE: a comment\n"
        "cloudsmith-maven-extension-0.2.0.jar>cloudsmith=\n"
        "cloudsmith-maven-extension-0.2.0-sources.jar>cloudsmith=\n",
        encoding="utf-8",
    )

    MavenInstaller().install()

    assert (version_dir / "_remote.repositories").read_text(encoding="utf-8") == (
        "#NOTE: a comment\n"
        "cloudsmith-maven-extension-0.2.0.jar>=\n"
        "cloudsmith-maven-extension-0.2.0-sources.jar>cloudsmith=\n"
        "cloudsmith-maven-extension-0.2.0.pom>=\n"
    )


def test_maven_install_local_turns_on_the_extension_in_the_project(
    home, fake_repository, maven_project
):
    """With local, the project's .mvn/extensions.xml lists the extension."""
    actions = MavenInstaller().install(local=True)

    extensions_file = maven_project / ".mvn" / "extensions.xml"
    assert "<version>0.2.0</version>" in extensions_file.read_text(encoding="utf-8")
    assert any(str(extensions_file) in action for action in actions)
    assert not _user_extensions(home).exists()


def test_maven_install_local_from_a_module_uses_the_root_project(
    home, fake_repository, maven_project, monkeypatch
):
    """Maven reads .mvn from the nearest directory above that has one."""
    (maven_project / ".mvn").mkdir()
    module = maven_project / "module"
    module.mkdir()
    (module / "pom.xml").write_text("<project/>", encoding="utf-8")
    monkeypatch.chdir(module)

    MavenInstaller().install(local=True)

    assert (maven_project / ".mvn" / "extensions.xml").exists()
    assert not (module / ".mvn").exists()


def test_maven_install_local_outside_a_project_fails(
    home, fake_repository, outside_projects
):
    """Without a pom.xml, the install stops before it changes anything."""
    with pytest.raises(ProjectNotFound, match="pom.xml"):
        MavenInstaller().install(local=True)

    assert not (outside_projects / ".mvn").exists()
    assert not fake_repository


def test_maven_install_with_mavenrc_adds_a_block(
    home, fake_repository, outside_projects
):
    """--mavenrc loads the extension in Maven 3.9 and earlier, and keeps the lines there."""
    (home / ".mavenrc").write_text('export JAVA_HOME="/opt/java"\n', encoding="utf-8")

    MavenInstaller().install(mavenrc=True)

    jar = _local_extension_dir(home, "0.2.0") / "cloudsmith-maven-extension-0.2.0.jar"
    text = (home / ".mavenrc").read_text(encoding="utf-8")
    assert text.startswith('export JAVA_HOME="/opt/java"\n')
    assert f"-Dmaven.ext.class.path={jar}" in text
    # Maven 3.10 would load the extension twice from both files.
    assert not _user_extensions(home).exists()


def test_maven_install_with_local_and_mavenrc_fails(
    home, fake_repository, maven_project
):
    """The two options set up different scopes, so only one is allowed."""
    with pytest.raises(InstallOptionError):
        MavenInstaller().install(local=True, mavenrc=True)


def test_maven_install_dry_run_changes_nothing(home, fake_repository, maven_project):
    """A dry run reports the planned changes and writes no files."""
    actions = [
        *MavenInstaller().install(dry_run=True),
        *MavenInstaller().install(dry_run=True, local=True),
        *MavenInstaller().install(dry_run=True, mavenrc=True),
    ]

    assert not (maven_project / ".mvn").exists()
    assert not (home / ".m2").exists()
    assert not (home / ".mavenrc").exists()
    assert all(action.startswith("would ") for action in actions)


def test_maven_uninstall_removes_only_what_install_added(
    home, fake_repository, outside_projects
):
    """Other extensions and other .mavenrc lines stay, and so does the local repository."""
    _user_extensions(home).parent.mkdir()
    _user_extensions(home).write_text(
        f"<extensions>\n{OTHER_EXTENSION}</extensions>\n", encoding="utf-8"
    )
    (home / ".mavenrc").write_text("export A=1\n", encoding="utf-8")
    MavenInstaller().install()
    MavenInstaller().install(mavenrc=True)

    MavenInstaller().uninstall()

    assert _user_extensions(home).read_text(encoding="utf-8") == (
        f"<extensions>\n{OTHER_EXTENSION}</extensions>\n"
    )
    assert (home / ".mavenrc").read_text(encoding="utf-8") == "export A=1\n"
    assert _local_extension_dir(home, "0.2.0").exists()


def test_maven_uninstall_local_removes_the_extension_from_the_project(
    home, fake_repository, maven_project
):
    """Uninstall with local removes the file that install with local made."""
    MavenInstaller().install(local=True)

    MavenInstaller().uninstall(local=True)

    assert not (maven_project / ".mvn" / "extensions.xml").exists()


def test_maven_status_names_the_file_that_loads_the_extension(
    home, fake_repository, maven_project
):
    """list shows the user-wide file first, then the file of the current project."""
    assert MavenInstaller().status() == {"launcher": None, "hosts": []}

    MavenInstaller().install(local=True)
    project_file = maven_project / ".mvn" / "extensions.xml"
    assert MavenInstaller().status() == {"launcher": str(project_file), "hosts": []}

    MavenInstaller().install()
    assert MavenInstaller().status() == {
        "launcher": str(_user_extensions(home)),
        "hosts": [],
    }


# ---------------------------------------------------------------------------
# 5. GradleInstaller
# ---------------------------------------------------------------------------


def test_gradle_install_writes_an_init_script(home, fake_repository):
    """The init script applies the plugin to the settings of every build."""
    actions = GradleInstaller().install()

    script = home / ".gradle" / "init.d" / "cloudsmith.init.gradle.kts"
    text = script.read_text(encoding="utf-8")
    assert f'maven {{ url = uri("{maven_tools.REPOSITORY_URL}") }}' in text
    assert 'classpath("io.cloudsmith:cloudsmith-gradle-plugin:0.2.0")' in text
    assert "pluginManager.apply(io.cloudsmith.gradle.CloudsmithPlugin::class.java)" in (
        text
    )
    assert any(str(script) in action for action in actions)


def test_gradle_install_uses_gradle_user_home(
    home, fake_repository, tmp_path, monkeypatch
):
    """GRADLE_USER_HOME moves the init.d directory."""
    monkeypatch.setenv("GRADLE_USER_HOME", str(tmp_path / "gradle-home"))

    GradleInstaller().install()

    assert (tmp_path / "gradle-home" / "init.d" / "cloudsmith.init.gradle.kts").exists()


def test_gradle_install_local_explains_the_settings_plugin(home, fake_repository):
    """Gradle has no project init scripts, so the error shows what to add instead."""
    with pytest.raises(InstallOptionError, match="settings.gradle.kts"):
        GradleInstaller().install(local=True)

    assert not (home / ".gradle").exists()


def test_gradle_uninstall_and_status(home, fake_repository):
    """Uninstall removes the init script, and status follows it."""
    script = home / ".gradle" / "init.d" / "cloudsmith.init.gradle.kts"
    GradleInstaller().install()
    assert GradleInstaller().status() == {"launcher": str(script), "hosts": []}

    GradleInstaller().uninstall()

    assert not script.exists()
    assert GradleInstaller().status() == {"launcher": None, "hosts": []}


# ---------------------------------------------------------------------------
# 6. SbtInstaller
# ---------------------------------------------------------------------------


def test_sbt_install_writes_a_global_plugin(home, fake_repository):
    """sbt 1 loads global plugins for every build from ~/.sbt/1.0/plugins."""
    actions = SbtInstaller().install()

    plugin_file = home / ".sbt" / "1.0" / "plugins" / "cloudsmith.sbt"
    text = plugin_file.read_text(encoding="utf-8")
    assert (
        f'resolvers += "cloudsmith-maven-tools" at "{maven_tools.REPOSITORY_URL}"'
        in (text)
    )
    assert 'addSbtPlugin("io.cloudsmith" % "sbt-cloudsmith" % "0.2.0")' in text
    assert any(str(plugin_file) in action for action in actions)


def test_sbt_install_local_writes_a_project_plugin(
    home, fake_repository, outside_projects
):
    """sbt loads every .sbt file in project/, so the build's own files stay as they are."""
    (outside_projects / "build.sbt").write_text("", encoding="utf-8")

    SbtInstaller().install(local=True)

    plugin_file = outside_projects / "project" / "cloudsmith.sbt"
    text = plugin_file.read_text(encoding="utf-8")
    assert 'addSbtPlugin("io.cloudsmith" % "sbt-cloudsmith" % "0.2.0")' in text
    assert not (home / ".sbt").exists()

    SbtInstaller().uninstall(local=True)

    assert not plugin_file.exists()


def test_sbt_install_local_outside_a_project_fails(
    home, fake_repository, outside_projects
):
    """Without a build.sbt, the install stops before it changes anything."""
    with pytest.raises(ProjectNotFound, match="build.sbt"):
        SbtInstaller().install(local=True)

    assert not (outside_projects / "project").exists()


def test_sbt_uninstall_and_status(home, fake_repository):
    """Uninstall removes the global plugin, and status follows it."""
    plugin_file = home / ".sbt" / "1.0" / "plugins" / "cloudsmith.sbt"
    SbtInstaller().install()
    assert SbtInstaller().status() == {"launcher": str(plugin_file), "hosts": []}

    SbtInstaller().uninstall()

    assert not plugin_file.exists()
    assert SbtInstaller().status() == {"launcher": None, "hosts": []}


# ---------------------------------------------------------------------------
# 7. CLI wiring
# ---------------------------------------------------------------------------


def _invoke(command_name, args):
    from ...cli.commands.credential_helper import manage

    command = {"install": manage.install_cmd, "uninstall": manage.uninstall_cmd}
    return click.testing.CliRunner().invoke(
        command[command_name], args, catch_exceptions=False
    )


@pytest.mark.parametrize("helper", ["maven", "gradle", "sbt"])
def test_cli_install_runs_the_installer(helper, home, fake_repository, maven_project):
    """`credential-helper install <helper>` writes the config without credentials."""
    result = _invoke("install", [helper, "--no-discover"])

    assert result.exit_code == 0, result.output
    assert "0.2.0" in result.output


def test_cli_install_and_uninstall_maven_local(home, fake_repository, maven_project):
    """--local reaches the installer for install and for uninstall."""
    extensions_file = maven_project / ".mvn" / "extensions.xml"

    assert _invoke("install", ["maven", "--local", "--no-discover"]).exit_code == 0
    assert extensions_file.exists()
    assert _invoke("uninstall", ["maven", "--local"]).exit_code == 0
    assert not extensions_file.exists()


def test_cli_install_maven_with_mavenrc(home, fake_repository, outside_projects):
    """--mavenrc reaches the Maven installer."""
    result = _invoke("install", ["maven", "--mavenrc", "--no-discover"])

    assert result.exit_code == 0, result.output
    assert (home / ".mavenrc").exists()


def test_cli_install_maven_local_outside_a_project_fails_cleanly(
    home, fake_repository, outside_projects
):
    """The error names the directory and the fix, without a traceback."""
    result = _invoke("install", ["maven", "--local", "--no-discover"])

    assert result.exit_code != 0
    assert "pom.xml" in result.output


def test_cli_install_gradle_local_shows_the_settings_plugin(home, fake_repository):
    """The error shows the plugins block to add to settings.gradle.kts."""
    result = _invoke("install", ["gradle", "--local", "--no-discover"])

    assert result.exit_code != 0
    assert 'id("io.cloudsmith.gradle-plugin")' in result.output


@pytest.mark.parametrize("option", ["--local", "--mavenrc"])
def test_cli_install_rejects_an_option_that_the_helper_does_not_have(option, home):
    """Other helpers fail with a clear error, not with a TypeError."""
    result = _invoke("install", ["docker", option, "--no-discover"])

    assert result.exit_code != 0
    assert f"{option} is not supported for docker" in result.output


@pytest.mark.parametrize("helper", ["maven", "gradle", "sbt"])
def test_cli_install_downloads_with_the_tls_settings_of_the_command(
    helper, home, outside_projects
):
    """--without-ssl-verify-strict also applies to the downloads of the Maven tools."""
    from ...cli.commands.credential_helper import manage

    download_session = Mock()
    sessions = []

    def record_latest_version(artifact_path, session=None):
        sessions.append(session)
        return "0.2.0"

    def record_download(artifact_path, destination, session=None):
        sessions.append(session)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("content", encoding="utf-8")

    with (
        patch.object(maven_tools, "latest_version", record_latest_version),
        patch.object(maven_tools, "download", record_download),
        patch.object(
            manage, "create_requests_session", return_value=download_session
        ) as create_session,
    ):
        result = _invoke(
            "install", [helper, "--without-ssl-verify-strict", "--no-discover"]
        )

    assert result.exit_code == 0, result.output
    assert create_session.call_args.kwargs["ssl_verify_strict"] is False
    # The session for the public repository gets no --api-headers.
    assert "headers" not in create_session.call_args.kwargs
    assert sessions
    assert all(session is download_session for session in sessions)
