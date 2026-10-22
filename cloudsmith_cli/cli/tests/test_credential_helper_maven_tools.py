# Copyright 2026 Cloudsmith Ltd
"""Tests for the Maven, Gradle, and sbt installers of the Cloudsmith Maven tools.

The installers configure each build tool to load the Cloudsmith extension or
plugin, which gets its credential from `cloudsmith credential-helper generic`.
"""

from __future__ import annotations

from pathlib import Path

import click.testing
import httpretty
import httpretty.core
import pytest

from ...credential_helpers import maven_tools
from ...credential_helpers.gradle.installer import GradleInstaller
from ...credential_helpers.maven import extensions
from ...credential_helpers.maven.installer import MavenInstaller, MavenProjectNotFound
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

    def fake_download(artifact_path, destination):
        downloads.append(artifact_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"content of {artifact_path}", encoding="utf-8")

    monkeypatch.setattr(maven_tools, "latest_version", lambda artifact_path: "0.2.0")
    monkeypatch.setattr(maven_tools, "download", fake_download)
    return downloads


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


# ---------------------------------------------------------------------------
# 3. MavenInstaller
# ---------------------------------------------------------------------------


def _local_extension_dir(home: Path, version: str) -> Path:
    return home / ".m2" / "repository" / EXTENSION_PATH / version


def test_maven_install_puts_the_extension_in_the_local_repository(
    home, fake_repository, maven_project
):
    """Maven loads build extensions only from Maven Central or the local repository."""
    actions = MavenInstaller().install()

    version_dir = _local_extension_dir(home, "0.2.0")
    assert (version_dir / "cloudsmith-maven-extension-0.2.0.jar").exists()
    assert (version_dir / "cloudsmith-maven-extension-0.2.0.pom").exists()
    assert any(str(version_dir) in action for action in actions)


def test_maven_install_turns_on_the_extension_in_the_project(
    home, fake_repository, maven_project
):
    """The project's .mvn/extensions.xml lists the installed version."""
    actions = MavenInstaller().install()

    extensions_file = maven_project / ".mvn" / "extensions.xml"
    assert "<version>0.2.0</version>" in extensions_file.read_text(encoding="utf-8")
    assert any(str(extensions_file) in action for action in actions)


def test_maven_install_from_a_module_uses_the_root_project(
    home, fake_repository, maven_project, monkeypatch
):
    """Maven reads .mvn from the nearest directory above that has one."""
    (maven_project / ".mvn").mkdir()
    module = maven_project / "module"
    module.mkdir()
    (module / "pom.xml").write_text("<project/>", encoding="utf-8")
    monkeypatch.chdir(module)

    MavenInstaller().install()

    assert (maven_project / ".mvn" / "extensions.xml").exists()
    assert not (module / ".mvn").exists()


def test_maven_install_outside_a_project_fails(
    home, fake_repository, tmp_path, monkeypatch
):
    """Without a pom.xml, the install stops before it changes anything."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(MavenProjectNotFound):
        MavenInstaller().install()

    assert not (tmp_path / ".mvn").exists()
    assert not fake_repository


def test_maven_install_dry_run_changes_nothing(home, fake_repository, maven_project):
    """A dry run reports the planned changes and writes no files."""
    actions = MavenInstaller().install(dry_run=True)

    assert not (maven_project / ".mvn").exists()
    assert not (home / ".m2").exists()
    assert all(action.startswith("would ") for action in actions)


def test_maven_uninstall_removes_the_extension_from_the_project(
    home, fake_repository, maven_project
):
    """Uninstall removes the file it made, and keeps the shared local repository."""
    MavenInstaller().install()

    MavenInstaller().uninstall()

    assert not (maven_project / ".mvn" / "extensions.xml").exists()
    assert _local_extension_dir(home, "0.2.0").exists()


def test_maven_status_names_the_project_file(home, fake_repository, maven_project):
    """list shows the extensions.xml of the current project when it is set up."""
    assert MavenInstaller().status() == {"launcher": None, "hosts": []}

    MavenInstaller().install()

    extensions_file = maven_project / ".mvn" / "extensions.xml"
    assert MavenInstaller().status() == {"launcher": str(extensions_file), "hosts": []}


# ---------------------------------------------------------------------------
# 4. GradleInstaller
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


def test_gradle_uninstall_and_status(home, fake_repository):
    """Uninstall removes the init script, and status follows it."""
    script = home / ".gradle" / "init.d" / "cloudsmith.init.gradle.kts"
    GradleInstaller().install()
    assert GradleInstaller().status() == {"launcher": str(script), "hosts": []}

    GradleInstaller().uninstall()

    assert not script.exists()
    assert GradleInstaller().status() == {"launcher": None, "hosts": []}


# ---------------------------------------------------------------------------
# 5. SbtInstaller
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


def test_sbt_uninstall_and_status(home, fake_repository):
    """Uninstall removes the global plugin, and status follows it."""
    plugin_file = home / ".sbt" / "1.0" / "plugins" / "cloudsmith.sbt"
    SbtInstaller().install()
    assert SbtInstaller().status() == {"launcher": str(plugin_file), "hosts": []}

    SbtInstaller().uninstall()

    assert not plugin_file.exists()
    assert SbtInstaller().status() == {"launcher": None, "hosts": []}


# ---------------------------------------------------------------------------
# 6. CLI wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("helper", ["maven", "gradle", "sbt"])
def test_cli_install_runs_the_installer(helper, home, fake_repository, maven_project):
    """`credential-helper install <helper>` writes the config without credentials."""
    from ...cli.commands.credential_helper.manage import install_cmd

    result = click.testing.CliRunner().invoke(
        install_cmd, [helper, "--no-discover"], catch_exceptions=False
    )

    assert result.exit_code == 0, result.output
    assert "0.2.0" in result.output


def test_cli_install_maven_outside_a_project_fails_cleanly(
    home, fake_repository, tmp_path, monkeypatch
):
    """The error names the directory and the fix, without a traceback."""
    from ...cli.commands.credential_helper.manage import install_cmd

    monkeypatch.chdir(tmp_path)
    result = click.testing.CliRunner().invoke(
        install_cmd, ["maven", "--no-discover"], catch_exceptions=False
    )

    assert result.exit_code != 0
    assert "pom.xml" in result.output
