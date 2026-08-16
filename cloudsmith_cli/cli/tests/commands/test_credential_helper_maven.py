# Copyright 2026 Cloudsmith Ltd
"""Tests for the Maven settings.xml, stored binding and `cloudsmith exec`."""

import os
import stat
from dataclasses import replace
from xml.etree import ElementTree

import pytest

from ....credential_helpers.maven import config, runner, settings

pytestmark = pytest.mark.usefixtures("cli_config_dir")


@pytest.fixture()
def binding():
    return config.Binding(
        owner="my-org",
        repo="my-repo",
        download_host="dl.cloudsmith.io",
        upload_host="maven.cloudsmith.io",
    )


def write_fake_mvn(tmp_path, monkeypatch, script_body):
    """Put a fake `mvn` running *script_body* alone on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    mvn = bin_dir / "mvn"
    mvn.write_text(f"#!/bin/sh\n{script_body}\n")
    mvn.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


@pytest.fixture()
def fake_mvn(tmp_path, monkeypatch):
    """Put an executable that records its argv on PATH as `mvn`."""
    argv_log = tmp_path / "argv.txt"
    write_fake_mvn(tmp_path, monkeypatch, f'printf "%s\\n" "$@" > "{argv_log}"\nexit 0')
    return argv_log


def _settings_arg(argv_log):
    """Return the path Maven was handed with -s, from a recorded argv."""
    argv = argv_log.read_text().splitlines()
    return argv[argv.index("-s") + 1]


# ---------------------------------------------------------------------------
# settings.xml
# ---------------------------------------------------------------------------


def test_settings_xml_carries_the_download_repository_and_token(binding):
    """The generated file authenticates dependency resolution on its own."""
    root = ElementTree.fromstring(settings.build_settings_xml(binding, "secret"))

    server = root.find("servers/server")
    assert server.findtext("id") == "cloudsmith"
    assert server.findtext("username") == "token"
    assert server.findtext("password") == "secret"

    repository = root.find("profiles/profile/repositories/repository")
    assert repository.findtext("id") == "cloudsmith"
    assert (
        repository.findtext("url")
        == "https://dl.cloudsmith.io/basic/my-org/my-repo/maven/"
    )
    # The profile has to be active, or none of the above applies.
    assert root.findtext("activeProfiles/activeProfile") == "cloudsmith"


def test_settings_xml_escapes_the_token(binding):
    """A token is interpolated into XML, so it must not be able to break out."""
    xml = settings.build_settings_xml(binding, "a&b<c>")

    assert "a&b<c>" not in xml
    root = ElementTree.fromstring(xml)
    assert root.findtext("servers/server/password") == "a&b<c>"


def test_settings_xml_honours_the_server_id(binding):
    """--server-id renames every id, so pom.xml and settings.xml still match."""
    xml = settings.build_settings_xml(
        replace(binding, server_id="private-id"), "secret"
    )

    assert "<id>private-id</id>" in xml
    assert "<id>cloudsmith</id>" not in xml


@pytest.mark.parametrize(
    "host,expected_download,expected_upload",
    [
        (
            "dl.cloudsmith.io",
            "https://dl.cloudsmith.io/basic/my-org/my-repo/maven/",
            "https://dl.cloudsmith.io/my-org/my-repo/",
        ),
        # A custom domain is bound to one org, so the org is not in the path.
        (
            "maven.example.com",
            "https://maven.example.com/basic/my-repo/maven/",
            "https://maven.example.com/my-repo/",
        ),
    ],
)
def test_urls_include_the_org_only_on_default_hosts(
    host, expected_download, expected_upload
):
    assert settings.download_url("my-org", "my-repo", host) == expected_download
    assert settings.upload_url("my-org", "my-repo", host) == expected_upload


def test_write_settings_is_not_readable_by_others(tmp_path, binding):
    """The file holds a usable token for the lifetime of the run."""
    path = settings.write_settings(
        str(tmp_path), settings.build_settings_xml(binding, "secret")
    )

    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


# ---------------------------------------------------------------------------
# stored binding
# ---------------------------------------------------------------------------


def test_binding_round_trips(binding):
    config.set_binding(binding)

    assert config.get_binding() == binding


def test_remove_binding_reports_whether_there_was_one(binding):
    assert config.remove_binding() is False
    config.set_binding(binding)
    assert config.remove_binding() is True
    assert config.get_binding() is None


def test_unreadable_config_reads_as_no_binding(cli_config_dir):
    """A hand-edited file must not make mvn unusable machine-wide."""
    config.config_path().write_text("not an ini file [[[", encoding="utf-8")

    assert config.get_binding() is None


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


def test_run_injects_settings_and_returns_the_exit_code(binding, fake_mvn, credential):
    config.set_binding(binding)

    assert runner.run(["mvn", "clean", "install"], credential=credential) == 0

    argv = fake_mvn.read_text().splitlines()
    assert argv[0] == "-s" and argv[2:] == ["clean", "install"]


def test_run_deletes_the_settings_file_afterwards(binding, fake_mvn, credential):
    """The token must not outlive the run it was provisioned for."""
    config.set_binding(binding)

    runner.run(["mvn", "package"], credential=credential)

    assert not os.path.exists(_settings_arg(fake_mvn))


def test_run_passes_the_token_to_maven(binding, tmp_path, monkeypatch, credential):
    """The file mvn is handed is the one holding the resolved credential."""
    copy = tmp_path / "settings-seen.xml"
    write_fake_mvn(tmp_path, monkeypatch, f'/bin/cp "$2" "{copy}"\nexit 0')
    config.set_binding(binding)

    runner.run(["mvn", "package"], credential=credential)

    assert credential.api_key in copy.read_text()


@pytest.mark.parametrize("args", [["--version"], ["-v"], ["help"], ["clean", "--help"]])
def test_help_and_version_run_unwrapped(binding, fake_mvn, credential, args):
    """Nothing to authenticate, so no settings.xml is injected."""
    config.set_binding(binding)

    assert runner.run(["mvn", *args], credential=credential) == 0
    assert fake_mvn.read_text().splitlines() == args


@pytest.mark.parametrize(
    "args",
    [
        ["-s", "mine.xml", "package"],
        ["-smine.xml", "package"],
        ["--settings", "mine.xml", "package"],
        ["--settings=mine.xml", "package"],
    ],
)
def test_a_user_supplied_settings_file_wins(
    binding, fake_mvn, credential, args, capsys
):
    """Prepending our -s as well would silently shadow the user's file."""
    config.set_binding(binding)

    assert runner.run(["mvn", *args], credential=credential) == 0

    assert fake_mvn.read_text().splitlines() == args
    assert "without Cloudsmith credential injection" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["-show-version", "package"], ["-strict-checksums"]])
def test_single_dash_long_options_are_not_mistaken_for_settings(
    binding, fake_mvn, credential, args
):
    """Maven accepts long options with one dash, so -s* is not always -s."""
    config.set_binding(binding)

    runner.run(["mvn", *args], credential=credential)

    assert fake_mvn.read_text().splitlines()[:2] == ["-s", _settings_arg(fake_mvn)]


def test_a_path_qualified_maven_is_still_wrapped(
    binding, fake_mvn, credential, tmp_path
):
    """`./mvnw` is explicit intent and must not run unauthenticated."""
    config.set_binding(binding)
    wrapper = tmp_path / "bin" / "mvnw"
    wrapper.write_text((tmp_path / "bin" / "mvn").read_text())
    wrapper.chmod(0o755)

    assert runner.run([str(wrapper), "package"], credential=credential) == 0
    assert fake_mvn.read_text().splitlines()[0] == "-s"


def test_a_command_with_no_plugin_runs_unchanged(fake_mvn, tmp_path, credential):
    other = tmp_path / "bin" / "gradle"
    other.write_text((tmp_path / "bin" / "mvn").read_text())
    other.chmod(0o755)

    assert runner.run(["gradle", "build"], credential=credential) == 0
    assert fake_mvn.read_text().splitlines() == ["build"]


def test_run_reports_a_missing_binding(fake_mvn, credential, capsys):
    """The shim wraps every mvn, so this has to be a message, not a traceback."""
    assert runner.run(["mvn", "package"], credential=credential) == 2
    assert "credential-helper install maven" in capsys.readouterr().err


def test_run_warns_but_proceeds_without_a_credential(binding, fake_mvn, capsys):
    """Public repositories still resolve, so this is a warning, not an error."""
    config.set_binding(binding)

    assert runner.run(["mvn", "package"], credential=None) == 0
    assert "no credential resolved" in capsys.readouterr().err


def test_run_reports_a_missing_command(credential, capsys):
    assert runner.run(["definitely-not-installed"], credential=credential) == 127
    assert "command not found" in capsys.readouterr().err


def test_run_requires_a_command(capsys):
    assert runner.run([]) == 2
    assert "requires a command" in capsys.readouterr().err


def test_a_signalled_child_reports_the_shell_convention(
    binding, tmp_path, monkeypatch, credential
):
    """A negative returncode is not an exit status; sys.exit would truncate it."""
    write_fake_mvn(tmp_path, monkeypatch, "kill -9 $$")
    config.set_binding(binding)

    assert runner.run(["mvn", "package"], credential=credential) == 137


def test_the_shim_directory_is_excluded_when_resolving_the_binary(
    tmp_path, monkeypatch
):
    """Otherwise a shim re-invokes itself forever."""
    shims = config.shims_dir()
    shims.mkdir(parents=True)
    (shims / "mvn").write_text("#!/bin/sh\nexit 0\n")
    (shims / "mvn").chmod(0o755)
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "mvn").write_text("#!/bin/sh\nexit 0\n")
    (real_dir / "mvn").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}{os.pathsep}{real_dir}")

    resolved = runner.resolve_real_binary("mvn", str(shims))

    assert resolved == str(real_dir / "mvn")


def test_a_symlink_into_the_shim_directory_is_excluded_too(tmp_path, monkeypatch):
    """Comparison is by real path, so an aliased PATH entry does not slip past."""
    shims = config.shims_dir()
    shims.mkdir(parents=True)
    (shims / "mvn").write_text("#!/bin/sh\nexit 0\n")
    (shims / "mvn").chmod(0o755)
    alias = tmp_path / "alias"
    alias.symlink_to(shims)
    monkeypatch.setenv("PATH", str(alias))

    assert runner.resolve_real_binary("mvn", str(shims)) is None
