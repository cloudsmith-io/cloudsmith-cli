# Copyright 2026 Cloudsmith Ltd
"""Tests for the Maven, Gradle, and sbt installers of the Cloudsmith Maven tools.

The installers configure each build tool to load the Cloudsmith extension or
plugin, which gets its credential from `cloudsmith credential-helper generic`.
"""

from __future__ import annotations

import errno
import os
import re
import subprocess
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import click.testing
import httpretty
import httpretty.core
import pytest

from ...core.cache_utils import ConfigFileParseError
from ...credential_helpers import maven_tools
from ...credential_helpers.gradle.installer import GradleInstaller
from ...credential_helpers.maven import extensions, mavenrc
from ...credential_helpers.maven import installer as maven_installer
from ...credential_helpers.maven.installer import MavenInstaller, MavenrcNotSupported
from ...credential_helpers.maven_tools import ConfigFileConflict, ProjectNotFound
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
    monkeypatch.delenv("MAVEN_OPTS", raising=False)
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


@pytest.fixture(autouse=True)
def _posix(monkeypatch):
    """Run as if the platform is not Windows, so the mvn script reads ~/.mavenrc."""
    monkeypatch.setattr(maven_installer, "is_windows", lambda: False)


@pytest.fixture()
def outside_projects(tmp_path, monkeypatch):
    """Run the test from a directory that is not in a project."""
    directory = tmp_path / "work"
    directory.mkdir()
    monkeypatch.chdir(directory)
    return directory


@pytest.fixture()
def deleted_cwd(monkeypatch):
    """Run the test as if another process deleted the current directory."""

    def cwd():
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT))

    monkeypatch.setattr(Path, "cwd", staticmethod(cwd))


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
def test_latest_version_names_the_url_when_the_metadata_is_not_xml():
    """A proxy page in place of the metadata is an OSError that names the URL."""
    url = f"{maven_tools.REPOSITORY_URL}{EXTENSION_PATH}/maven-metadata.xml"
    httpretty.register_uri(httpretty.GET, url, body="<html><body>Blocked")

    with pytest.raises(OSError, match=url):
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


@httpretty.activate(allow_net_connect=False)
def test_download_leaves_no_partial_file_when_the_write_fails(tmp_path, monkeypatch):
    """A later install finds no file, so it downloads the file again."""
    httpretty.register_uri(
        httpretty.GET,
        f"{maven_tools.REPOSITORY_URL}{EXTENSION_PATH}/0.2.0/extension.jar",
        body=b"jar bytes",
    )

    def write_half_and_fail(path, data):
        with open(path, "wb") as partial_file:
            partial_file.write(data[: len(data) // 2])
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "write_bytes", write_half_and_fail)
    destination = tmp_path / "extension.jar"

    with pytest.raises(OSError, match="No space left"):
        maven_tools.download(f"{EXTENSION_PATH}/0.2.0/extension.jar", destination)

    assert list(tmp_path.iterdir()) == []


def _write_half_and_fail(path, data):
    with open(path, "wb") as partial_file:
        partial_file.write(data[: len(data) // 2])
    raise OSError(errno.ENOSPC, "No space left on device")


def test_write_atomically_keeps_the_old_file_when_the_write_fails(
    tmp_path, monkeypatch
):
    """A full disk does not leave a config file with only part of its text."""
    path = tmp_path / ".mavenrc"
    path.write_bytes(b"export A=1\n")
    monkeypatch.setattr(Path, "write_bytes", _write_half_and_fail)

    with pytest.raises(OSError, match="No space left"):
        maven_tools.write_atomically(path, b"export A=1\nexport B=2\n")

    assert path.read_bytes() == b"export A=1\n"
    assert [entry.name for entry in tmp_path.iterdir()] == [".mavenrc"]


@pytest.mark.skipif(os.name == "nt", reason="Windows has no POSIX file modes.")
def test_write_atomically_never_widens_the_mode_of_a_private_file(
    tmp_path, monkeypatch
):
    """The temporary copy of a private file is never readable by other users."""
    path = tmp_path / ".mavenrc"
    path.write_bytes(b"export SECRET=1\n")
    path.chmod(0o600)
    modes_while_writing = []
    write_bytes = Path.write_bytes

    def record_mode_and_write(partial, data):
        if partial.exists():
            modes_while_writing.append(partial.stat().st_mode & 0o777)
        else:
            modes_while_writing.append(None)
        return write_bytes(partial, data)

    monkeypatch.setattr(Path, "write_bytes", record_mode_and_write)

    maven_tools.write_atomically(path, b"export SECRET=2\n")

    assert modes_while_writing == [0o600]
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="Symbolic links need extra rights.")
def test_write_atomically_keeps_a_symbolic_link_and_the_file_mode(tmp_path):
    """A dotfile that links to another file stays a link, with the same mode."""
    target = tmp_path / "dotfiles" / "mavenrc"
    target.parent.mkdir()
    target.write_bytes(b"export A=1\n")
    target.chmod(0o600)
    link = tmp_path / ".mavenrc"
    link.symlink_to(target)

    maven_tools.write_atomically(link, b"export B=2\n")

    assert link.is_symlink()
    assert target.read_bytes() == b"export B=2\n"
    assert target.stat().st_mode & 0o777 == 0o600


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


@pytest.mark.parametrize("closing_tag", ["</extensions >", "</extensions\n>"])
def test_add_extension_finds_a_closing_tag_with_spaces(closing_tag):
    """XML allows spaces before the > of the closing tag."""
    existing = f"<extensions>\n{OTHER_EXTENSION}{closing_tag}\n"

    assert extensions.add_extension(existing, "0.1.0") == (
        f"<extensions>\n{OTHER_EXTENSION}{OUR_EXTENSION}{closing_tag}\n",
        True,
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
    ) == (f"<extensions>\n{comment}</extensions>\n", True)
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


def test_remove_extension_keeps_comments_on_the_same_lines():
    """A comment next to the Cloudsmith extension is not part of it."""
    ours = OUR_EXTENSION.rstrip("\n")
    existing = (
        f"<extensions>\n<!-- before -->{ours}<!-- after -->\n"
        f"{OTHER_EXTENSION}</extensions>\n"
    )

    text, changed = extensions.remove_extension(existing)

    assert changed is True
    assert text == (
        f"<extensions>\n<!-- before --><!-- after -->\n{OTHER_EXTENSION}</extensions>\n"
    )


def test_remove_extension_keeps_a_file_that_is_not_utf_8():
    """A byte that is not UTF-8 stops the XML check, so the file stays."""
    existing = f"<extensions>\n<!-- \udce9 -->\n{OUR_EXTENSION}{OTHER_EXTENSION}</extensions>\n"

    assert extensions.remove_extension(existing) == (
        f"<extensions>\n<!-- \udce9 -->\n{OTHER_EXTENSION}</extensions>\n",
        True,
    )


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


NAMESPACED_EXTENSION = """  <m:extension xmlns:m="http://maven.apache.org/EXTENSIONS/1.0.0">
    <m:groupId>io.cloudsmith</m:groupId>
    <m:artifactId xml:space="default">cloudsmith-maven-extension</m:artifactId>
    <m:version>0.1.0</m:version>
  </m:extension>
"""


def test_extension_with_namespaces_is_found_updated_and_removed():
    """A namespace prefix or attribute does not hide the Cloudsmith extension."""
    existing = f"<extensions>\n{NAMESPACED_EXTENSION}{OTHER_EXTENSION}</extensions>\n"

    updated, changed = extensions.add_extension(existing, "0.2.0")

    assert extensions.has_extension(existing)
    assert changed is True
    assert updated == existing.replace("<m:version>0.1.0<", "<m:version>0.2.0<")
    assert extensions.remove_extension(existing) == (
        f"<extensions>\n{OTHER_EXTENSION}</extensions>\n",
        True,
    )


@pytest.mark.parametrize(
    "existing",
    [
        '<m:extensions xmlns:m="http://maven.apache.org/EXTENSIONS/1.0.0">\n'
        "</m:extensions>\n",
        '<m:extensions xmlns:m="http://maven.apache.org/EXTENSIONS/1.0.0"/>\n',
    ],
)
def test_add_extension_uses_the_prefix_of_the_extensions_element(existing):
    """The new extension is in the same namespace as the <extensions> element."""
    text, changed = extensions.add_extension(existing, "0.2.0")

    assert changed is True
    assert text == (
        '<m:extensions xmlns:m="http://maven.apache.org/EXTENSIONS/1.0.0">\n'
        "  <m:extension>\n"
        "    <m:groupId>io.cloudsmith</m:groupId>\n"
        "    <m:artifactId>cloudsmith-maven-extension</m:artifactId>\n"
        "    <m:version>0.2.0</m:version>\n"
        "  </m:extension>\n"
        "</m:extensions>\n"
    )
    assert extensions.has_extension(text)


def test_a_self_closing_extension_is_not_the_start_of_a_block():
    """An empty <extension/> element does not join the next extension."""
    existing = f"<extensions>\n  <extension/>\n{OUR_EXTENSION}</extensions>\n"

    assert extensions.remove_extension(existing) == (
        "<extensions>\n  <extension/>\n</extensions>\n",
        True,
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
    """An entry with spaces in its tags or values is updated, not listed a second time."""
    spaced = _spaced_tags(OUR_EXTENSION).replace(
        "<groupId>io.cloudsmith</groupId>", "<groupId> io.cloudsmith </groupId>"
    )
    existing = f"<extensions>\n{spaced}</extensions>\n"

    text, changed = extensions.add_extension(existing, "0.2.0")

    assert changed is True
    assert text == existing.replace(
        "<version>0.1.0</version>", "<version>0.2.0</version>"
    )


def _spaced_child_tags(extension: str) -> str:
    for name in ("groupId", "artifactId", "version"):
        extension = extension.replace(f"<{name}>", f"<{name} >")
        extension = extension.replace(f"</{name}>", f"</{name}\n    >")
    return extension


def test_add_extension_finds_the_extension_with_spaces_in_its_child_tags():
    """XML allows spaces before the > of each child tag, so only the version changes."""
    existing = f"<extensions>\n{_spaced_child_tags(OUR_EXTENSION)}</extensions>\n"

    assert extensions.add_extension(existing, "0.2.0") == (
        existing.replace(">0.1.0<", ">0.2.0<"),
        True,
    )


def test_remove_extension_finds_the_extension_with_spaces_in_its_child_tags():
    """Status and uninstall find the entry with spaces in its child tags."""
    existing = f"<extensions>\n{_spaced_child_tags(OUR_EXTENSION)}</extensions>\n"

    assert extensions.has_extension(existing)
    assert extensions.remove_extension(existing) == (None, True)


# ---------------------------------------------------------------------------
# 3. ~/.mavenrc
# ---------------------------------------------------------------------------

JAR = Path("/home/me/.m2/repository/cloudsmith-maven-extension-0.2.0.jar")
BLOCK = mavenrc.render_block(JAR)


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


def test_remove_block_keeps_the_lines_around_it_apart():
    """Without a blank line before the block, the line before it keeps its newline."""
    assert mavenrc.remove_block(f"export A=1\n{BLOCK}export B=2\n") == (
        "export A=1\nexport B=2\n",
        True,
    )


def test_remove_the_only_block_returns_no_text():
    """When nothing else is in the file, the file is not needed."""
    assert mavenrc.remove_block(BLOCK) == (None, True)


def test_remove_block_without_a_block_changes_nothing():
    """A file without the block stays as it is."""
    assert mavenrc.remove_block("export A=1\n") == ("export A=1\n", False)


def _maven_opts_after_block(maven_opts: str, block: str = BLOCK) -> str:
    """Run the block in the shell that the mvn script uses, and return MAVEN_OPTS."""
    script = f'MAVEN_OPTS="$1"\n{block}printf %s "$MAVEN_OPTS"\n'
    result = subprocess.run(
        ["sh", "-c", script, "sh", maven_opts],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


POSIX_SHELL_ONLY = pytest.mark.skipif(
    os.name == "nt", reason="The mvn script that reads ~/.mavenrc is a POSIX script."
)


@POSIX_SHELL_ONLY
def test_block_adds_the_class_path_to_maven_opts():
    """Without a class path in MAVEN_OPTS, the block adds one with only the JAR."""
    assert _maven_opts_after_block("-Xmx1g") == f"-Xmx1g -Dmaven.ext.class.path={JAR}"


@POSIX_SHELL_ONLY
@pytest.mark.parametrize("maven_opts", ["", "-Dmaven.ext.class.path=/opt/other.jar"])
def test_block_reads_shell_characters_in_the_jar_path_as_text(maven_opts):
    """The shell does not expand or run the characters of the JAR path."""
    jar = Path('/home/a$(id)`id`"d\\e/extension.jar')
    block = mavenrc.render_block(jar)

    once = _maven_opts_after_block(maven_opts, block)

    assert f"-Dmaven.ext.class.path={jar}" in once
    assert _maven_opts_after_block(once, block) == once


@POSIX_SHELL_ONLY
def test_block_ignores_the_class_path_option_inside_another_value():
    """Java reads only an option that starts a word of MAVEN_OPTS."""
    maven_opts = "-DargLine=-Dmaven.ext.class.path=/opt/test.jar -Xmx1g"

    assert _maven_opts_after_block(maven_opts) == (
        f"{maven_opts} -Dmaven.ext.class.path={JAR}"
    )


@POSIX_SHELL_ONLY
@pytest.mark.parametrize("separator", ["\t", "\n"])
def test_block_finds_the_class_path_after_a_tab_or_a_new_line(separator):
    """mvn splits MAVEN_OPTS at tabs and new lines too."""
    maven_opts = f"-Xmx1g{separator}-Dmaven.ext.class.path=/opt/other.jar"

    assert _maven_opts_after_block(maven_opts) == (
        f"-Xmx1g -Dmaven.ext.class.path={JAR}{os.pathsep}/opt/other.jar"
    )


@POSIX_SHELL_ONLY
def test_block_keeps_the_other_extensions_in_the_class_path():
    """Java uses only the last -D value, so the block adds the JAR to that value."""
    maven_opts = "-Xmx1g -Dmaven.ext.class.path=/opt/other.jar -Dquiet=true"

    assert _maven_opts_after_block(maven_opts) == (
        f"-Xmx1g -Dmaven.ext.class.path={JAR}{os.pathsep}/opt/other.jar -Dquiet=true"
    )


@POSIX_SHELL_ONLY
@pytest.mark.parametrize(
    ("maven_opts", "expected"),
    [
        (
            f"-Dmaven.ext.class.path={JAR} -Dmaven.ext.class.path=/opt/other.jar",
            f"-Dmaven.ext.class.path={JAR} "
            f"-Dmaven.ext.class.path={JAR}{os.pathsep}/opt/other.jar",
        ),
        (
            f"-Dmaven.ext.class.path=/opt/other.jar -Dnote={JAR}",
            f"-Dmaven.ext.class.path={JAR}{os.pathsep}/opt/other.jar -Dnote={JAR}",
        ),
        (
            f"-Dmaven.ext.class.path={JAR}.old",
            f"-Dmaven.ext.class.path={JAR}{os.pathsep}{JAR}.old",
        ),
    ],
)
def test_block_looks_for_the_jar_only_in_the_last_class_path(maven_opts, expected):
    """Java uses only the last -D value, so the JAR in other text does not count."""
    assert _maven_opts_after_block(maven_opts) == expected


@POSIX_SHELL_ONLY
def test_block_does_not_add_the_jar_twice():
    """A nested mvn gets MAVEN_OPTS with the JAR, so the block leaves it as it is."""
    maven_opts = f"-Dmaven.ext.class.path={JAR}{os.pathsep}/opt/other.jar"

    assert _maven_opts_after_block(maven_opts) == maven_opts


# ---------------------------------------------------------------------------
# 4. MavenInstaller
# ---------------------------------------------------------------------------


def _local_extension_dir(home: Path, version: str) -> Path:
    return home / ".m2" / "repository" / EXTENSION_PATH / version


def _user_extensions(home: Path) -> Path:
    return home / ".m2" / "extensions.xml"


def _write_settings(home: Path, local_repository: str) -> Path:
    settings = home / ".m2" / "settings.xml"
    settings.parent.mkdir()
    settings.write_text(
        '<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0">\n'
        f"  <localRepository>{local_repository}</localRepository>\n"
        "</settings>\n",
        encoding="utf-8",
    )
    return settings


def _jar(repository: Path) -> Path:
    return (
        repository / EXTENSION_PATH / "0.2.0" / "cloudsmith-maven-extension-0.2.0.jar"
    )


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


@pytest.mark.parametrize("windows", [False, True])
def test_maven_install_warns_when_maven_ignores_user_extensions(
    windows, home, fake_repository, outside_projects, monkeypatch
):
    """Maven 3.9 and earlier ignore ~/.m2/extensions.xml, so install names the options."""
    monkeypatch.setattr(maven_installer, "_maven_version", lambda: "3.9.11")
    monkeypatch.setattr(maven_installer, "is_windows", lambda: windows)

    actions = MavenInstaller().install()

    warnings = [action for action in actions if action.startswith("WARNING")]
    assert len(warnings) == 1
    assert "3.9.11" in warnings[0]
    assert "--local" in warnings[0]
    # mvn.cmd does not read ~/.mavenrc.
    assert ("--mavenrc" in warnings[0]) is not windows
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


@pytest.mark.parametrize("local_repository", ["${user.home}/repo", "${env.M2_REPO}"])
def test_maven_install_uses_the_local_repository_of_the_user_settings(
    local_repository, home, fake_repository, outside_projects, monkeypatch
):
    """Maven reads <localRepository> from ~/.m2/settings.xml, after interpolation."""
    monkeypatch.setenv("M2_REPO", str(home / "repo"))
    _write_settings(home, local_repository)

    actions = MavenInstaller().install()

    assert _jar(home / "repo").exists()
    assert f"downloaded {_jar(home).name} to {_jar(home / 'repo').parent}" in actions


def test_maven_install_prefers_maven_repo_local_in_maven_opts(
    home, fake_repository, outside_projects, monkeypatch
):
    """-Dmaven.repo.local overrides the settings, and --mavenrc loads the JAR there."""
    _write_settings(home, "${user.home}/repo")
    monkeypatch.setenv("MAVEN_OPTS", f"-Xmx1g -Dmaven.repo.local={home / 'opts'}")

    MavenInstaller().install(mavenrc=True)

    assert _jar(home / "opts").exists()
    text = (home / ".mavenrc").read_text(encoding="utf-8")
    assert f"-Dmaven.ext.class.path={_jar(home / 'opts')}" in text


@pytest.mark.parametrize(
    ("config_file", "maven_opts"),
    [("jvm.config", ""), ("maven.config", "-Dmaven.repo.local=/elsewhere")],
)
def test_maven_install_local_reads_maven_repo_local_of_the_project(
    config_file, maven_opts, home, fake_repository, maven_project, monkeypatch
):
    """With local, the .mvn config files of the project can set the local repository."""
    monkeypatch.setenv("MAVEN_OPTS", maven_opts)
    (maven_project / ".mvn").mkdir()
    (maven_project / ".mvn" / config_file).write_text(
        f"-Dmaven.repo.local={maven_project / 'repo'}\n", encoding="utf-8"
    )

    MavenInstaller().install(local=True)

    assert _jar(maven_project / "repo").exists()


@pytest.mark.parametrize(
    ("maven_version", "maven_config", "repository"),
    [
        ("3.9.3", "# -Dmaven.repo.local=old-repo", "opts"),
        ("3.9.3", "-Dmaven.repo.local=my repo", "my repo"),
        ("3.8.8", "-Dmaven.repo.local=m2 -B", "m2"),
    ],
)
def test_maven_install_local_reads_maven_config_like_maven(
    maven_version,
    maven_config,
    repository,
    home,
    fake_repository,
    maven_project,
    monkeypatch,
):
    """Maven 3.9 reads each .mvn/maven.config line as one argument; 3.8 splits on whitespace."""
    monkeypatch.setattr(maven_installer, "_maven_version", lambda: maven_version)
    monkeypatch.setenv("MAVEN_OPTS", f"-Dmaven.repo.local={maven_project / 'opts'}")
    (maven_project / ".mvn").mkdir()
    (maven_project / ".mvn" / "maven.config").write_text(
        f"{maven_config}\n", encoding="utf-8"
    )

    MavenInstaller().install(local=True)

    assert _jar(maven_project / repository).exists()


@pytest.mark.parametrize("local_repository", ["${env.NOT_SET}", "</settings>"])
def test_maven_install_with_unusable_settings_fails(
    local_repository, home, fake_repository, outside_projects, monkeypatch
):
    """A settings file that does not parse or does not resolve stops the install."""
    monkeypatch.delenv("NOT_SET", raising=False)
    settings = _write_settings(home, local_repository)

    with pytest.raises(ConfigFileParseError, match=re.escape(str(settings))):
        MavenInstaller().install()

    assert not fake_repository


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


def test_maven_uninstall_local_finds_a_project_by_its_mvn_directory(
    home, outside_projects
):
    """Maven finds the project root by its .mvn directory, also without a pom.xml."""
    extensions_file = outside_projects / ".mvn" / "extensions.xml"
    extensions_file.parent.mkdir()
    extensions_file.write_text(
        f"<extensions>\n{OUR_EXTENSION}</extensions>\n", encoding="utf-8"
    )

    MavenInstaller().uninstall(local=True)

    assert not extensions_file.exists()


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


@pytest.mark.parametrize(("separator", "refused"), [(" ", True), ("\u00a0", False)])
def test_maven_install_with_mavenrc_refuses_a_jar_path_with_a_space(
    separator, refused, tmp_path, monkeypatch, fake_repository, outside_projects
):
    """mvn splits MAVEN_OPTS at spaces, so the JAR path would break every build."""
    home = tmp_path / f"John{separator}Smith"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    with (
        pytest.raises(MavenrcNotSupported, match="--local")
        if refused
        else nullcontext()
    ):
        MavenInstaller().install(mavenrc=True)

    assert (home / ".mavenrc").exists() is not refused
    assert bool(fake_repository) is not refused


def test_maven_install_with_mavenrc_turns_off_the_user_extensions_file(
    home, fake_repository, outside_projects
):
    """Maven 3.10 loads both, so only one of them loads the extension."""
    MavenInstaller().install()

    MavenInstaller().install(mavenrc=True)

    assert not _user_extensions(home).exists()
    assert mavenrc.has_block((home / ".mavenrc").read_text(encoding="utf-8"))


def test_maven_install_turns_off_the_mavenrc_block(
    home, fake_repository, outside_projects
):
    """Maven 3.10 loads both, so only one of them loads the extension."""
    (home / ".mavenrc").write_text('export JAVA_HOME="/opt/java"\n', encoding="utf-8")
    MavenInstaller().install(mavenrc=True)

    MavenInstaller().install()

    assert extensions.has_extension(_user_extensions(home).read_text(encoding="utf-8"))
    assert (home / ".mavenrc").read_text(encoding="utf-8") == (
        'export JAVA_HOME="/opt/java"\n'
    )


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


def test_maven_install_and_uninstall_keep_a_mavenrc_that_is_not_utf_8(
    home, fake_repository, outside_projects
):
    """The block is added and removed, and the other bytes stay as they are."""
    original = b"# \xe9\nexport A=1\n"
    (home / ".mavenrc").write_bytes(original)

    MavenInstaller().install(mavenrc=True)
    assert (home / ".mavenrc").read_bytes().startswith(original)

    MavenInstaller().uninstall()
    assert (home / ".mavenrc").read_bytes() == original


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


def test_maven_status_skips_a_file_that_cannot_be_decoded(home, outside_projects):
    """A ~/.mavenrc that is not UTF-8 does not stop `credential-helper list`."""
    (home / ".mavenrc").write_bytes(b"# \xe9\nexport A=1\n")

    assert MavenInstaller().status() == {"launcher": None, "hosts": []}


def test_maven_status_skips_a_file_that_cannot_be_read(
    home, fake_repository, outside_projects
):
    """An unreadable candidate does not hide the next file that loads the extension."""
    MavenInstaller().install(mavenrc=True)
    _user_extensions(home).mkdir(parents=True)

    assert MavenInstaller().status() == {
        "launcher": str(home / ".mavenrc"),
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


def test_gradle_uninstall_and_status(home, fake_repository):
    """Uninstall removes the init script, and status follows it."""
    script = home / ".gradle" / "init.d" / "cloudsmith.init.gradle.kts"
    GradleInstaller().install()
    assert GradleInstaller().status() == {"launcher": str(script), "hosts": []}

    GradleInstaller().uninstall()

    assert not script.exists()
    assert GradleInstaller().status() == {"launcher": None, "hosts": []}


def test_gradle_status_ignores_an_init_script_that_install_did_not_write(home):
    """Status reports only a file that uninstall can remove."""
    script = home / ".gradle" / "init.d" / "cloudsmith.init.gradle.kts"
    script.parent.mkdir(parents=True)
    script.write_text("// my own settings\n", encoding="utf-8")

    assert GradleInstaller().status() == {"launcher": None, "hosts": []}


def test_gradle_install_upgrades_an_init_script_that_it_wrote(home, fake_repository):
    """An init script for an older version gets the new version."""
    script = home / ".gradle" / "init.d" / "cloudsmith.init.gradle.kts"
    script.parent.mkdir(parents=True)
    script.write_text(GradleInstaller().render("0.1.0"), encoding="utf-8")

    GradleInstaller().install()

    assert script.read_text(encoding="utf-8") == GradleInstaller().render("0.2.0")


def test_gradle_install_keeps_an_init_script_that_is_not_utf_8(home, fake_repository):
    """A file that is not UTF-8 is not a file that install wrote."""
    script = home / ".gradle" / "init.d" / "cloudsmith.init.gradle.kts"
    script.parent.mkdir(parents=True)
    script.write_bytes(b"// \xe9\n")

    with pytest.raises(ConfigFileConflict):
        GradleInstaller().install()

    assert script.read_bytes() == b"// \xe9\n"


def test_gradle_uninstall_keeps_an_init_script_with_other_settings(
    home, fake_repository
):
    """Uninstall stops before it removes settings that install did not write."""
    script = home / ".gradle" / "init.d" / "cloudsmith.init.gradle.kts"
    script.parent.mkdir(parents=True)
    script.write_text('println("hello")\n', encoding="utf-8")

    with pytest.raises(ConfigFileConflict, match="did not write"):
        GradleInstaller().uninstall()

    assert script.read_text(encoding="utf-8") == 'println("hello")\n'


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


@pytest.mark.parametrize(
    "build_file",
    [
        "main.sbt",
        "project/build.properties",
        "project/cloudsmith.sbt",
        "project/plugins.sbt",
        "project/Build.scala",
    ],
)
def test_sbt_finds_a_project_without_a_build_sbt(outside_projects, build_file):
    """sbt reads any .sbt file in the root and the project/ directory."""
    path = outside_projects / build_file
    path.parent.mkdir(exist_ok=True)
    path.write_text("", encoding="utf-8")

    assert SbtInstaller().local_path() == (
        outside_projects / "project" / "cloudsmith.sbt"
    )


def test_sbt_install_keeps_a_plugin_file_with_other_settings(
    home, fake_repository, outside_projects
):
    """Install stops before it replaces settings that it did not write."""
    (outside_projects / "build.sbt").write_text("", encoding="utf-8")
    plugin_file = outside_projects / "project" / "cloudsmith.sbt"
    plugin_file.parent.mkdir()
    other_plugin = 'addSbtPlugin("com.example" % "sbt-other" % "1.0.0")\n'
    plugin_file.write_text(other_plugin, encoding="utf-8")

    with pytest.raises(ConfigFileConflict, match="did not write"):
        SbtInstaller().install(local=True)

    assert plugin_file.read_text(encoding="utf-8") == other_plugin


def test_sbt_install_keeps_lines_added_to_its_plugin_file(home, fake_repository):
    """A line that the user adds to the file stops a later install and uninstall."""
    plugin_file = home / ".sbt" / "1.0" / "plugins" / "cloudsmith.sbt"
    plugin_file.parent.mkdir(parents=True)
    edited = SbtInstaller().render("0.1.0") + 'addSbtPlugin("a" % "b" % "1")\n'
    plugin_file.write_text(edited, encoding="utf-8")

    with pytest.raises(ConfigFileConflict):
        SbtInstaller().install()
    with pytest.raises(ConfigFileConflict):
        SbtInstaller().uninstall()

    assert plugin_file.read_text(encoding="utf-8") == edited


def test_sbt_uninstall_and_status(home, fake_repository):
    """Uninstall removes the global plugin, and status follows it."""
    plugin_file = home / ".sbt" / "1.0" / "plugins" / "cloudsmith.sbt"
    SbtInstaller().install()
    assert SbtInstaller().status() == {"launcher": str(plugin_file), "hosts": []}

    SbtInstaller().uninstall()

    assert not plugin_file.exists()
    assert SbtInstaller().status() == {"launcher": None, "hosts": []}


def test_sbt_status_names_the_plugin_file_of_the_project(
    home, fake_repository, outside_projects
):
    """After install --local, status names project/cloudsmith.sbt."""
    assert SbtInstaller().status() == {"launcher": None, "hosts": []}
    (outside_projects / "build.sbt").write_text("", encoding="utf-8")
    SbtInstaller().install(local=True)

    assert SbtInstaller().status() == {
        "launcher": str(outside_projects / "project" / "cloudsmith.sbt"),
        "hosts": [],
    }


# ---------------------------------------------------------------------------
# 7. CLI wiring
# ---------------------------------------------------------------------------


def _invoke(command_name, args):
    from ...cli.commands.credential_helper import manage

    command = {
        "install": manage.install_cmd,
        "uninstall": manage.uninstall_cmd,
        "list": manage.list_cmd,
    }
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


def test_cli_install_maven_with_mavenrc_fails_cleanly_on_windows(
    home, fake_repository, outside_projects, monkeypatch
):
    """mvn.cmd does not read ~/.mavenrc, so the command names the other options."""
    monkeypatch.setattr(maven_installer, "is_windows", lambda: True)

    result = _invoke("install", ["maven", "--mavenrc", "--no-discover"])

    assert result.exit_code == 1
    assert "--local" in result.output
    assert not (home / ".mavenrc").exists()
    assert not fake_repository


def test_cli_install_maven_local_outside_a_project_fails_cleanly(
    home, fake_repository, outside_projects
):
    """The error names the directory and the fix, without a traceback."""
    result = _invoke("install", ["maven", "--local", "--no-discover"])

    assert result.exit_code != 0
    assert "pom.xml" in result.output


@pytest.mark.parametrize("helper", ["maven", "sbt"])
def test_cli_install_local_in_a_deleted_directory_fails_cleanly(
    helper, home, fake_repository, deleted_cwd
):
    """The error tells the user that the current directory does not exist."""
    result = _invoke("install", [helper, "--local", "--no-discover"])

    assert result.exit_code == 1
    assert "current directory does not exist" in result.output


def test_cli_list_in_a_deleted_directory_shows_every_helper(home, deleted_cwd):
    """A deleted current directory has no project, so list still runs."""
    result = _invoke("list", [])

    assert result.exit_code == 0, result.output
    assert "maven  (" in result.output
    assert "sbt  (" in result.output


@pytest.mark.parametrize("command_name", ["install", "uninstall"])
def test_cli_with_a_config_file_that_install_did_not_write_fails_cleanly(
    command_name, home, fake_repository, outside_projects
):
    """The error names the file, without a traceback."""
    plugin_file = home / ".sbt" / "1.0" / "plugins" / "cloudsmith.sbt"
    plugin_file.parent.mkdir(parents=True)
    plugin_file.write_text("// my settings\n", encoding="utf-8")

    result = _invoke(command_name, ["sbt"])

    assert result.exit_code == 1
    assert str(plugin_file) in result.output


@pytest.mark.parametrize(
    ("command_name", "helper", "option"),
    [
        ("install", "docker", "--local"),
        ("install", "gradle", "--local"),
        ("install", "sbt", "--mavenrc"),
        ("uninstall", "gradle", "--local"),
    ],
)
def test_cli_rejects_an_option_that_the_helper_does_not_have(
    command_name, helper, option, home
):
    """Click stops the command before the installer runs."""
    result = _invoke(command_name, [helper, option])

    assert result.exit_code == 2
    assert f"{option} applies only to" in result.output


def test_cli_install_rejects_local_with_mavenrc(home):
    """The two options set up different scopes, so only one is allowed."""
    result = _invoke("install", ["maven", "--local", "--mavenrc"])

    assert result.exit_code == 2
    assert "--local or --mavenrc, not both" in result.output


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
