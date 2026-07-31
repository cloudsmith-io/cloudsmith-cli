# Copyright 2026 Cloudsmith Ltd
"""Tests for the Maven shell-plugin credential helper (config, settings.xml,
shims, shell-init, runner, installer, and CLI wiring)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import click.testing
import pytest

from ....cli.commands.credential_helper.manage import install_cmd, list_cmd
from ....cli.commands.credential_helper.shell import shell_init
from ....cli.commands.exec_ import exec_
from ....core.credentials.models import CredentialResult
from ....credential_helpers.backends import BackendKind
from ....credential_helpers.common import is_standard_cloudsmith_host, repo_path_segment
from ....credential_helpers.custom_domains import CustomDomain
from ....credential_helpers.maven.installer import MavenInstaller
from ....credential_helpers.shellplugin import config, maven, plugin, runner
from ....credential_helpers.shellplugin.maven import (
    MavenPlugin,
    build_settings_xml,
    download_url,
    upload_url,
)
from ....credential_helpers.shellplugin.runner import resolve_real_binary
from ....credential_helpers.shellplugin.shellinit import detect_shell, generate_init
from ....credential_helpers.shellplugin.shims import remove_shim, write_shim

# ---------------------------------------------------------------------------
# 1. config — PluginEntry + package-managers.ini
# ---------------------------------------------------------------------------


@pytest.fixture()
def _home(tmp_path, monkeypatch):
    """Point the CLI config dir at a tmp dir so package-managers.ini/shims land under it."""
    monkeypatch.setattr(
        "cloudsmith_cli.credential_helpers.shellplugin.config.get_default_config_path",
        lambda: str(tmp_path),
    )
    return tmp_path


def test_config_path_and_shims_dir_in_config_dir(_home):
    """config_path() and shims_dir() live in the CLI config directory."""
    assert config.config_path() == _home / "package-managers.ini"
    assert config.shims_dir() == _home / "shims"


def test_load_plugins_missing_file_returns_empty(_home):
    """load_plugins() returns {} when package-managers.ini does not exist."""
    assert config.load_plugins() == {}


def test_set_then_get_plugin_roundtrip(_home):
    """set_plugin persists every field; get_plugin reads it back."""
    # Every host differs from its default, so a field that is silently dropped
    # comes back as the default rather than matching.
    entry = config.PluginEntry(
        owner="acme",
        repo="prod",
        cdn_host="dl.acme.example.com",
        upload_host="maven.acme.example.com",
        registry_id="acme-registry",
    )
    config.set_plugin("maven", entry)

    loaded = config.get_plugin("maven")
    assert loaded == entry
    # Persisted on disk as an INI section in the CLI config dir.
    text = config.config_path().read_text(encoding="utf-8")
    assert "[package-manager:maven]" in text
    assert "owner = acme" in text
    assert "cdn_host = dl.acme.example.com" in text


def test_get_plugin_absent_returns_none(_home):
    """get_plugin returns None for a format with no entry."""
    assert config.get_plugin("maven") is None


def test_remove_plugin(_home):
    """remove_plugin deletes the entry (True), and is a no-op (False) afterwards."""
    config.set_plugin("maven", config.PluginEntry(owner="acme", repo="prod"))
    assert config.remove_plugin("maven") is True
    assert config.get_plugin("maven") is None
    assert config.remove_plugin("maven") is False


def test_plugin_entry_from_dict_tolerates_missing_optionals(_home):
    """PluginEntry.from_dict fills defaults for absent host/registry_id keys."""
    entry = config.PluginEntry.from_dict({"owner": "acme", "repo": "prod"})
    assert entry.owner == "acme"
    assert entry.repo == "prod"
    assert entry.cdn_host == "dl.cloudsmith.io"
    assert entry.upload_host == "maven.cloudsmith.io"
    assert entry.registry_id == "cloudsmith"


# ---------------------------------------------------------------------------
# 2. maven.build_settings_xml + MavenPlugin
# ---------------------------------------------------------------------------


def test_build_settings_xml_server_and_active_profile():
    """settings.xml carries one <server> + an active download <profile>."""
    xml = build_settings_xml(
        owner="acme",
        repo="prod",
        token="k_abc",
        cdn_host="dl.cloudsmith.io",
        server_id="cloudsmith",
    )

    assert "<id>cloudsmith</id>" in xml
    assert "<username>token</username>" in xml
    assert "<password>k_abc</password>" in xml
    # Download repository + plugin repository point at the CDN basic endpoint.
    assert "https://dl.cloudsmith.io/basic/acme/prod/maven/" in xml
    assert "<repository>" in xml
    assert "<pluginRepository>" in xml
    # Profile is active by default.
    assert "<activeProfile>cloudsmith</activeProfile>" in xml


def test_build_settings_xml_custom_cdn_host_is_org_scoped():
    """A custom download domain is org-scoped: the <org> segment is dropped."""
    xml = build_settings_xml(
        owner="acme",
        repo="prod",
        token="k_abc",
        cdn_host="dl.acme.example.com",
        server_id="my-cs",
    )
    # Custom domain → /basic/<repo>/maven/ (no <org>); default keeps the org.
    assert "https://dl.acme.example.com/basic/prod/maven/" in xml
    assert "/basic/acme/prod/maven/" not in xml
    assert "<id>my-cs</id>" in xml
    assert "<activeProfile>my-cs</activeProfile>" in xml


def test_repo_path_segment_org_scoping():
    """Standard hosts keep <owner>/<repo>; custom domains drop the org."""
    assert is_standard_cloudsmith_host("dl.cloudsmith.io") is True
    assert is_standard_cloudsmith_host("maven.cloudsmith.com") is True
    assert is_standard_cloudsmith_host("dl-prod.iduffy.cloudsmith.sh") is False

    assert repo_path_segment("acme", "prod", "dl.cloudsmith.io") == "acme/prod"
    assert repo_path_segment("acme", "prod", "dl-prod.iduffy.example.sh") == "prod"


def test_maven_download_url_default_keeps_org_custom_drops_it():
    """download_url keeps <org> for dl.cloudsmith.io, drops it for custom domains."""
    assert (
        download_url("acme", "prod", "dl.cloudsmith.io")
        == "https://dl.cloudsmith.io/basic/acme/prod/maven/"
    )
    assert (
        download_url("acme", "prod", "dl.acme.example.com")
        == "https://dl.acme.example.com/basic/prod/maven/"
    )


def test_maven_upload_url_default_keeps_org_custom_drops_it():
    """upload_url keeps <org> for maven.cloudsmith.io, drops it for custom domains."""
    assert (
        upload_url("acme", "prod", "maven.cloudsmith.io")
        == "https://maven.cloudsmith.io/acme/prod/"
    )
    assert (
        upload_url("acme", "prod", "maven.acme.example.com")
        == "https://maven.acme.example.com/prod/"
    )


def test_build_settings_xml_escapes_token():
    """A token with XML metacharacters is escaped in the password element."""
    xml = build_settings_xml(
        owner="acme",
        repo="prod",
        token="a<b&c",
        cdn_host="dl.cloudsmith.io",
        server_id="cloudsmith",
    )
    assert "<password>a&lt;b&amp;c</password>" in xml
    assert "a<b&c" not in xml


def test_maven_plugin_identity_and_skip_auth():
    """MavenPlugin exposes name/binary_name and skips auth for help/version."""
    plugin = MavenPlugin()
    assert plugin.name == "maven"
    assert plugin.binary_name == "mvn"
    assert "--version" in plugin.skip_auth_args()
    assert "--help" in plugin.skip_auth_args()
    assert "-h" in plugin.skip_auth_args()


@pytest.mark.parametrize(
    "args",
    [
        ["-s", "mine.xml", "install"],
        ["--settings", "mine.xml", "install"],
        ["--settings=mine.xml", "install"],
    ],
)
def test_maven_plugin_defers_to_user_settings_file(args):
    """A user-supplied settings file is a reason to skip provisioning."""
    reason = MavenPlugin().skip_provision_reason(args)
    assert reason is not None
    assert "settings" in reason


def test_maven_plugin_no_skip_reason_for_plain_args():
    """Ordinary goals give no reason to skip provisioning."""
    assert MavenPlugin().skip_provision_reason(["clean", "install"]) is None


def test_maven_plugin_provision_writes_settings_and_prepends_s():
    """provision() writes a 0600 settings.xml and returns ['-s', path]."""
    entry = config.PluginEntry(owner="acme", repo="prod")
    result = MavenPlugin().provision(entry, token="k_abc", args=["install"])

    assert result.prepend_args[0] == "-s"
    settings_path = Path(result.prepend_args[1])
    assert settings_path.exists()
    assert settings_path.read_text(encoding="utf-8") == build_settings_xml(
        owner=entry.owner,
        repo=entry.repo,
        token="k_abc",
        cdn_host=entry.cdn_host,
        server_id=entry.registry_id,
    )
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600
    assert result.temp_dirs == [str(settings_path.parent)]
    assert not result.env


# ---------------------------------------------------------------------------
# 3. shims — write_shim / remove_shim
# ---------------------------------------------------------------------------


def test_write_shim_execs_the_exec_command(tmp_path):
    """write_shim writes an executable that re-execs `credential-helper exec`."""
    dest = write_shim(tmp_path, "mvn")
    assert dest == tmp_path / "mvn"
    assert (
        dest.read_text(encoding="utf-8")
        == '#!/bin/sh\nexec cloudsmith exec -- mvn "$@"\n'
    )
    assert stat.S_IMODE(dest.stat().st_mode) == 0o755


def test_remove_shim(tmp_path):
    """remove_shim returns True when present, False when already gone."""
    write_shim(tmp_path, "mvn")
    assert remove_shim(tmp_path, "mvn") is True
    assert not (tmp_path / "mvn").exists()
    assert remove_shim(tmp_path, "mvn") is False


# ---------------------------------------------------------------------------
# 4. shellinit — generate_init / detect_shell
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_generate_init_posix_prepends_shims_dir(_home, shell):
    """bash/zsh init prepends the shims dir to PATH."""
    out = generate_init(shell)
    assert f'export PATH="{config.shims_dir()}:$PATH"' in out


def test_generate_init_fish_uses_fish_add_path(_home):
    """fish init uses fish_add_path, not export PATH."""
    out = generate_init("fish")
    assert f'fish_add_path "{config.shims_dir()}"' in out
    assert "export PATH" not in out


def test_generate_init_unknown_shell_raises():
    """An unsupported shell name is a clear error."""
    with pytest.raises(ValueError):
        generate_init("powershell")


@pytest.mark.parametrize(
    "shell_env,expected",
    [
        ("/bin/zsh", "zsh"),
        ("/usr/bin/fish", "fish"),
        ("/bin/bash", "bash"),
        ("", "bash"),
    ],
)
def test_detect_shell(monkeypatch, shell_env, expected):
    """detect_shell maps $SHELL to a supported shell, defaulting to bash."""
    monkeypatch.setenv("SHELL", shell_env)
    assert detect_shell() == expected


# ---------------------------------------------------------------------------
# 5. runner — resolve_real_binary + run
# ---------------------------------------------------------------------------


def _make_executable(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_resolve_real_binary_skips_excluded_dir(tmp_path, monkeypatch):
    """resolve_real_binary skips the shims dir and finds the real binary."""
    shims = tmp_path / "shims"
    real = tmp_path / "real"
    _make_executable(shims, "mvn")
    real_mvn = _make_executable(real, "mvn")
    monkeypatch.setenv("PATH", os.pathsep.join([str(shims), str(real)]))

    resolved = resolve_real_binary("mvn", exclude_dirs=[str(shims)])
    assert resolved == str(real_mvn)


def test_resolve_real_binary_none_when_only_excluded(tmp_path, monkeypatch):
    """resolve_real_binary returns None when the only match is excluded."""
    shims = tmp_path / "shims"
    _make_executable(shims, "mvn")
    monkeypatch.setenv("PATH", str(shims))

    assert resolve_real_binary("mvn", exclude_dirs=[str(shims)]) is None


def test_resolve_real_binary_excludes_symlinked_shims_dir(tmp_path, monkeypatch):
    """A PATH entry that is a symlink to the shims dir must not resolve the shim.

    Returning the shim here re-enters `cloudsmith exec` forever (fork bomb).
    """
    shims = tmp_path / "shims"
    real = tmp_path / "real"
    _make_executable(shims, "mvn")
    real_mvn = _make_executable(real, "mvn")
    linked = tmp_path / "linked-shims"
    linked.symlink_to(shims, target_is_directory=True)
    monkeypatch.setenv("PATH", os.pathsep.join([str(linked), str(real)]))

    assert resolve_real_binary("mvn", exclude_dirs=[str(shims)]) == str(real_mvn)


def test_resolve_real_binary_excludes_symlink_to_shim_binary(tmp_path, monkeypatch):
    """A symlink pointing at a shim binary from another dir is excluded too."""
    shims = tmp_path / "shims"
    shim = _make_executable(shims, "mvn")
    aliases = tmp_path / "aliases"
    aliases.mkdir()
    (aliases / "mvn").symlink_to(shim)
    monkeypatch.setenv("PATH", str(aliases))

    assert resolve_real_binary("mvn", exclude_dirs=[str(shims)]) is None


def test_run_skip_auth_passes_through_without_provisioning(_home, monkeypatch):
    """`mvn --version` execs the real binary directly, no settings.xml."""
    monkeypatch.setattr(runner, "resolve_real_binary", lambda *_a, **_k: "/usr/bin/mvn")
    captured = {}

    def _fake_run_process(path, args, env):
        captured["path"] = path
        captured["args"] = args
        return 0

    monkeypatch.setattr(runner, "_run_process", _fake_run_process)

    code = runner.run(
        ["mvn", "--version"],
        credential=CredentialResult(api_key="k_abc", source_name="test"),
        owner="acme",
        repo="prod",
    )

    assert code == 0
    assert captured["path"] == "/usr/bin/mvn"
    assert captured["args"] == ["--version"]
    # No temp settings dir left behind.
    assert not list(_home.glob("**/settings.xml"))


def test_run_provisions_prepends_s_and_cleans_up(_home, monkeypatch):
    """Auth path: provisions settings.xml, prepends -s, cleans up temp dir."""
    config.set_plugin(
        "maven",
        config.PluginEntry(owner="acme", repo="prod"),
    )
    monkeypatch.setattr(runner, "resolve_real_binary", lambda *_a, **_k: "/usr/bin/mvn")

    captured = {}

    def _fake_run_process(path, args, env):
        captured["path"] = path
        captured["args"] = args
        # Settings file must still exist while the child runs.
        captured["settings_exists"] = Path(args[1]).exists()
        return 7

    monkeypatch.setattr(runner, "_run_process", _fake_run_process)

    code = runner.run(
        ["mvn", "install"],
        credential=CredentialResult(api_key="k_abc", source_name="test"),
        owner="acme",
        repo="prod",
    )

    assert code == 7
    assert captured["args"][0] == "-s"
    assert captured["args"][-1] == "install"
    assert captured["settings_exists"] is True
    # Temp dir cleaned up after the child exits.
    assert not Path(captured["args"][1]).exists()


def test_run_empty_command_returns_nonzero(_home):
    """exec with no command is a usage error."""
    assert runner.run([], credential=None) != 0


def test_run_unmatched_command_runs_generically(_home, monkeypatch):
    """A command with no matching plugin runs as-is, with no provisioning."""
    monkeypatch.setattr(
        runner, "resolve_real_binary", lambda *_a, **_k: "/usr/bin/whoami"
    )
    captured = {}

    def _fake_run_process(path, args, env):
        captured["path"] = path
        captured["args"] = args
        return 0

    monkeypatch.setattr(runner, "_run_process", _fake_run_process)

    code = runner.run(["whoami"], credential=None)
    assert code == 0
    assert captured["path"] == "/usr/bin/whoami"
    assert captured["args"] == []
    assert not list(_home.glob("**/settings.xml"))


def test_run_provision_failure_is_clean_no_traceback(_home, monkeypatch):
    """A provisioning error returns a non-zero code, not a traceback."""
    config.set_plugin("maven", config.PluginEntry(owner="acme", repo="prod"))

    class _BoomPlugin:
        name = "maven"
        binary_name = "mvn"

        def skip_auth_args(self):
            return []

        def skip_provision_reason(self, _args):
            return None

        def provision(self, *_a, **_k):
            raise OSError("disk full")

    monkeypatch.setattr(plugin, "get_by_binary", lambda _b: _BoomPlugin())
    monkeypatch.setattr(runner, "resolve_real_binary", lambda *_a, **_k: "/usr/bin/mvn")

    code = runner.run(
        ["mvn", "install"],
        credential=CredentialResult(api_key="k", source_name="t"),
    )
    assert code != 0


def test_maven_provision_cleans_temp_dir_on_failure(monkeypatch, tmp_path):
    """If writing settings.xml fails, provision removes its temp dir and re-raises."""
    leak = tmp_path / "leak-dir"

    def _fake_mkdtemp(*_a, **_k):
        leak.mkdir()
        return str(leak)

    def _boom(**_k):
        raise OSError("boom")

    monkeypatch.setattr(maven.tempfile, "mkdtemp", _fake_mkdtemp)
    monkeypatch.setattr(maven, "build_settings_xml", _boom)

    with pytest.raises(OSError):
        maven.MavenPlugin().provision(
            config.PluginEntry(owner="acme", repo="prod"), "tok", []
        )
    assert not leak.exists()


def test_run_no_token_warns_but_proceeds(_home, monkeypatch):
    """No credential on an auth path still runs (public repos), with a warning."""
    config.set_plugin("maven", config.PluginEntry(owner="acme", repo="prod"))
    monkeypatch.setattr(runner, "resolve_real_binary", lambda *_a, **_k: "/usr/bin/mvn")
    captured = {}

    def _fake_run_process(path, args, env):
        captured["args"] = args
        return 0

    monkeypatch.setattr(runner, "_run_process", _fake_run_process)

    code = runner.run(["mvn", "install"], credential=None)
    assert code == 0
    assert captured["args"][0] == "-s"


def test_run_explicit_org_repo_override_stored_entry(_home, monkeypatch):
    """Explicit --org/--repo on exec take precedence over the stored binding."""
    config.set_plugin("maven", config.PluginEntry(owner="acme", repo="prod"))
    monkeypatch.setattr(runner, "resolve_real_binary", lambda *_a, **_k: "/usr/bin/mvn")
    captured = {}

    def _fake_run_process(path, args, env):
        captured["settings"] = Path(args[1]).read_text(encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "_run_process", _fake_run_process)

    code = runner.run(
        ["mvn", "install"],
        credential=CredentialResult(api_key="k", source_name="t"),
        owner="other",
        repo="dev",
    )
    assert code == 0
    assert "/basic/other/dev/maven/" in captured["settings"]
    assert "/basic/acme/prod/maven/" not in captured["settings"]


def test_run_binary_not_found_returns_nonzero(_home, monkeypatch):
    """When the real binary cannot be resolved, run returns non-zero."""
    monkeypatch.setattr(runner, "resolve_real_binary", lambda *_a, **_k: None)
    code = runner.run(
        ["mvn", "install"],
        credential=CredentialResult(api_key="k", source_name="t"),
        owner="acme",
        repo="prod",
    )
    assert code != 0


@pytest.mark.parametrize("owner,repo", [(None, None), ("acme", None), (None, "prod")])
def test_run_unconfigured_plugin_is_a_clear_error(
    _home, monkeypatch, capsys, owner, repo
):
    """No stored binding and no complete --org/--repo pair must not provision.

    Provisioning would inject a malformed URL like /basic///maven/ and shadow
    the user's own settings.xml; the customer gets baffling Maven errors.
    """
    monkeypatch.setattr(runner, "resolve_real_binary", lambda *_a, **_k: "/usr/bin/mvn")
    ran = {}
    monkeypatch.setattr(
        runner, "_run_process", lambda *_a, **_k: ran.setdefault("ran", True)
    )

    code = runner.run(
        ["mvn", "install"],
        credential=CredentialResult(api_key="k", source_name="t"),
        owner=owner,
        repo=repo,
    )

    assert code != 0
    assert "ran" not in ran
    stderr = capsys.readouterr().err
    assert "credential-helper install maven" in stderr
    assert not list(_home.glob("**/settings.xml"))


@pytest.mark.parametrize(
    "settings_args",
    [
        ["-s", "mine.xml"],
        ["--settings", "mine.xml"],
        ["--settings=mine.xml"],
    ],
)
def test_run_user_settings_file_wins_over_injection(
    _home, monkeypatch, capsys, settings_args
):
    """A user-supplied -s/--settings runs unwrapped, with a warning.

    Prepending our own -s as well would silently shadow the user's file
    (Maven takes the first occurrence).
    """
    config.set_plugin("maven", config.PluginEntry(owner="acme", repo="prod"))
    monkeypatch.setattr(runner, "resolve_real_binary", lambda *_a, **_k: "/usr/bin/mvn")
    captured = {}

    def _fake_run_process(path, args, env):
        captured["args"] = args
        return 0

    monkeypatch.setattr(runner, "_run_process", _fake_run_process)

    code = runner.run(
        ["mvn", *settings_args, "install"],
        credential=CredentialResult(api_key="k", source_name="t"),
    )

    assert code == 0
    assert captured["args"] == [*settings_args, "install"]
    assert "settings" in capsys.readouterr().err
    assert not list(_home.glob("**/settings.xml"))


def test_run_default_org_repo_fill_in_when_unconfigured(_home, monkeypatch):
    """Environment-sourced org/repo apply when no binding is stored."""
    monkeypatch.setattr(runner, "resolve_real_binary", lambda *_a, **_k: "/usr/bin/mvn")
    captured = {}

    def _fake_run_process(path, args, env):
        captured["settings"] = Path(args[1]).read_text(encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "_run_process", _fake_run_process)

    code = runner.run(
        ["mvn", "install"],
        credential=CredentialResult(api_key="k", source_name="t"),
        default_owner="acme",
        default_repo="prod",
    )
    assert code == 0
    assert "/basic/acme/prod/maven/" in captured["settings"]


def test_run_default_org_repo_do_not_override_stored_binding(_home, monkeypatch):
    """Environment-sourced org/repo must not silently override a stored binding.

    OIDC users keep CLOUDSMITH_ORG exported permanently; letting it override
    the binding points wrapped runs at a repository that does not exist.
    """
    config.set_plugin("maven", config.PluginEntry(owner="acme", repo="prod"))
    monkeypatch.setattr(runner, "resolve_real_binary", lambda *_a, **_k: "/usr/bin/mvn")
    captured = {}

    def _fake_run_process(path, args, env):
        captured["settings"] = Path(args[1]).read_text(encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "_run_process", _fake_run_process)

    code = runner.run(
        ["mvn", "install"],
        credential=CredentialResult(api_key="k", source_name="t"),
        default_owner="env-org",
        default_repo="env-repo",
    )
    assert code == 0
    assert "/basic/acme/prod/maven/" in captured["settings"]
    assert "env-org" not in captured["settings"]


# ---------------------------------------------------------------------------
# 6. MavenInstaller
# ---------------------------------------------------------------------------

_INSTALLER_GET_CUSTOM_DOMAINS = (
    "cloudsmith_cli.credential_helpers.maven.installer.get_custom_domains"
)


def _fake_discovery(monkeypatch, *, cdn_host=None, upload_host=None, raises=False):
    """Mock get_custom_domains: CDN domains carry backend_kind None; Maven == MAVEN."""
    domains = []
    if cdn_host:
        domains.append(
            CustomDomain(host=cdn_host, backend_kind=None, enabled=True, validated=True)
        )
    if upload_host:
        domains.append(
            CustomDomain(
                host=upload_host,
                backend_kind=int(BackendKind.MAVEN),
                enabled=True,
                validated=True,
            )
        )

    def _fake(org, **_kw):
        if raises:
            raise RuntimeError("network down")
        return domains

    monkeypatch.setattr(_INSTALLER_GET_CUSTOM_DOMAINS, _fake)


def test_maven_install_discovers_both_hosts_and_persists(_home, monkeypatch):
    """install writes the shim and persists discovered CDN + upload hosts."""
    monkeypatch.setenv("PATH", str(config.shims_dir()))
    _fake_discovery(monkeypatch, cdn_host="dl.acme.com", upload_host="maven.acme.com")

    MavenInstaller().install(org="acme", repo="prod", api_key="k", discover=True)

    assert (config.shims_dir() / "mvn").exists()
    entry = config.get_plugin("maven")
    assert entry.owner == "acme"
    assert entry.repo == "prod"
    assert entry.cdn_host == "dl.acme.com"
    assert entry.upload_host == "maven.acme.com"
    assert entry.registry_id == "cloudsmith"


def test_maven_install_defaults_when_no_discovery(_home, monkeypatch):
    """discover=False keeps the *.cloudsmith.io default hosts."""
    monkeypatch.setenv("PATH", str(config.shims_dir()))
    MavenInstaller().install(org="acme", repo="prod", discover=False)

    entry = config.get_plugin("maven")
    assert entry.cdn_host == "dl.cloudsmith.io"
    assert entry.upload_host == "maven.cloudsmith.io"


def test_maven_install_domain_override(_home, monkeypatch):
    """--domain overrides the discovered/default download CDN host."""
    monkeypatch.setenv("PATH", str(config.shims_dir()))
    MavenInstaller().install(
        org="acme", repo="prod", domains=("my.cdn.example.com",), discover=False
    )
    assert config.get_plugin("maven").cdn_host == "my.cdn.example.com"


def test_maven_install_custom_registry_id(_home, monkeypatch):
    """--registry-id is persisted for use in settings.xml + pom snippet."""
    monkeypatch.setenv("PATH", str(config.shims_dir()))
    MavenInstaller().install(
        org="acme", repo="prod", discover=False, registry_id="my-cs"
    )
    assert config.get_plugin("maven").registry_id == "my-cs"


def test_maven_install_prints_distribution_management_snippet(_home, monkeypatch):
    """install surfaces a distributionManagement snippet for opt-in deploy."""
    monkeypatch.setenv("PATH", str(config.shims_dir()))
    actions = MavenInstaller().install(org="acme", repo="prod", discover=False)

    joined = "\n".join(actions)
    assert "distributionManagement" in joined
    assert "https://maven.cloudsmith.io/acme/prod/" in joined
    assert "<id>cloudsmith</id>" in joined


def test_maven_install_notes_user_settings_not_consulted(_home, monkeypatch):
    """install tells the user wrapped runs do not read ~/.m2/settings.xml.

    Mirrors, proxies and other-repo credentials living there silently vanish
    from wrapped runs, so the surprise must be announced at install time.
    """
    monkeypatch.setenv("PATH", str(config.shims_dir()))
    actions = MavenInstaller().install(org="acme", repo="prod", discover=False)

    assert any("~/.m2/settings.xml" in action for action in actions)


def test_maven_install_snippet_custom_upload_domain_drops_org(_home, monkeypatch):
    """With a custom upload domain, the deploy snippet URL is org-scoped."""
    monkeypatch.setenv("PATH", str(config.shims_dir()))
    _fake_discovery(monkeypatch, upload_host="maven.acme.example.com")

    actions = MavenInstaller().install(
        org="acme", repo="prod", api_key="k", discover=True
    )
    joined = "\n".join(actions)
    assert "https://maven.acme.example.com/prod/" in joined
    assert "maven.acme.example.com/acme/prod/" not in joined


def test_maven_install_dry_run_writes_nothing(_home, monkeypatch):
    """dry_run: no shim, no package-managers.ini entry, returns 'would' actions."""
    actions = MavenInstaller().install(
        org="acme", repo="prod", discover=False, dry_run=True
    )
    assert not (config.shims_dir() / "mvn").exists()
    assert config.get_plugin("maven") is None
    assert any("would" in a.lower() for a in actions)


def test_maven_install_path_warning(_home, monkeypatch):
    """A WARNING is returned when the shims dir is not on PATH."""
    monkeypatch.setenv("PATH", "/usr/bin:/usr/local/bin")
    actions = MavenInstaller().install(org="acme", repo="prod", discover=False)
    warnings = [a for a in actions if a.startswith("WARNING")]
    assert warnings
    assert any("PATH" in a for a in warnings)


def test_maven_install_discovery_failure_is_graceful(_home, monkeypatch):
    """Discovery errors degrade to a WARNING; defaults still install."""
    monkeypatch.setenv("PATH", str(config.shims_dir()))
    _fake_discovery(monkeypatch, raises=True)

    actions = MavenInstaller().install(
        org="acme", repo="prod", api_key="k", discover=True
    )
    assert (config.shims_dir() / "mvn").exists()
    assert config.get_plugin("maven").cdn_host == "dl.cloudsmith.io"
    assert any(a.startswith("WARNING") for a in actions)


def test_maven_uninstall_removes_shim_and_entry(_home, monkeypatch):
    """uninstall removes the shim and drops the package-managers.ini entry."""
    monkeypatch.setenv("PATH", str(config.shims_dir()))
    installer = MavenInstaller()
    installer.install(org="acme", repo="prod", discover=False)
    assert (config.shims_dir() / "mvn").exists()

    installer.uninstall()
    assert not (config.shims_dir() / "mvn").exists()
    assert config.get_plugin("maven") is None


def test_maven_status_launcher_is_str_or_none(_home, monkeypatch):
    """status()['launcher'] is None before install and a str afterwards."""
    monkeypatch.setenv("PATH", str(config.shims_dir()))
    installer = MavenInstaller()

    assert installer.status()["launcher"] is None

    installer.install(org="acme", repo="prod", discover=False)
    launcher = installer.status()["launcher"]
    assert isinstance(launcher, str)
    assert launcher.endswith("mvn")


# ---------------------------------------------------------------------------
# 7. CLI wiring — exec + shell-init + manage
# ---------------------------------------------------------------------------


@pytest.fixture()
def cli_runner():
    return click.testing.CliRunner()


def test_exec_cmd_passes_command_through_and_propagates_exit_code(
    cli_runner, monkeypatch
):
    """`cloudsmith exec -- mvn install` calls runner.run([...]) and returns its code."""
    captured = {}

    def _fake_run(command, **kwargs):
        captured["command"] = command
        return 7

    monkeypatch.setattr(runner, "run", _fake_run)

    result = cli_runner.invoke(exec_, ["--", "mvn", "install", "-DskipTests"])
    assert result.exit_code == 7
    assert captured["command"] == ["mvn", "install", "-DskipTests"]


def test_exec_cmd_env_org_repo_are_defaults_not_overrides(cli_runner, monkeypatch):
    """CLOUDSMITH_ORG/CLOUDSMITH_REPO fill in when nothing is stored, but must
    not override a stored binding (OIDC users keep CLOUDSMITH_ORG exported)."""
    captured = {}

    def _fake_run(command, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(runner, "run", _fake_run)
    monkeypatch.setenv("CLOUDSMITH_ORG", "env-org")
    monkeypatch.setenv("CLOUDSMITH_REPO", "env-repo")

    result = cli_runner.invoke(exec_, ["-k", "fake-key", "--", "mvn", "install"])

    assert result.exit_code == 0
    assert captured["owner"] is None
    assert captured["repo"] is None
    assert captured["default_owner"] == "env-org"
    assert captured["default_repo"] == "env-repo"


def test_exec_cmd_flag_org_repo_are_overrides(cli_runner, monkeypatch):
    """--org/--repo passed on the command line override the stored binding."""
    captured = {}

    def _fake_run(command, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(runner, "run", _fake_run)
    monkeypatch.setenv("CLOUDSMITH_ORG", "env-org")

    result = cli_runner.invoke(
        exec_,
        ["-k", "fake-key", "--org", "flag-org", "--repo", "flag-repo", "--", "mvn"],
    )

    assert result.exit_code == 0
    assert captured["owner"] == "flag-org"
    assert captured["repo"] == "flag-repo"


def test_shell_init_cmd_explicit_shell(cli_runner, _home):
    """`shell-init --shell bash` prints the PATH prepend for the shims dir."""
    result = cli_runner.invoke(shell_init, ["--shell", "bash"])
    assert result.exit_code == 0
    assert f'export PATH="{config.shims_dir()}:$PATH"' in result.output


def test_shell_init_cmd_detects_fish(cli_runner, monkeypatch):
    """`shell-init` with $SHELL=fish emits fish syntax."""
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    result = cli_runner.invoke(shell_init, [])
    assert result.exit_code == 0
    assert "fish_add_path" in result.output


def test_manage_list_includes_maven(cli_runner):
    """`credential-helper list` shows the maven helper."""
    result = cli_runner.invoke(list_cmd, [])
    assert result.exit_code == 0, result.output
    assert "maven" in result.output


def test_manage_install_maven_dry_run(cli_runner, _home):
    """`install maven --org --repo --no-discover --dry-run` exits 0 with a plan."""
    result = cli_runner.invoke(
        install_cmd,
        ["maven", "--org", "acme", "--repo", "prod", "--no-discover", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "would" in result.output.lower() or "dry run" in result.output.lower()


def test_manage_install_maven_ignores_bin_dir(cli_runner, _home, tmp_path):
    """--bin-dir does not apply to shell plugins: the shim lands in the shims dir."""
    other = tmp_path / "other-bin"
    result = cli_runner.invoke(
        install_cmd,
        [
            "maven",
            "--org",
            "acme",
            "--repo",
            "prod",
            "--no-discover",
            "--bin-dir",
            str(other),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (config.shims_dir() / "mvn").exists()
    assert not (other / "mvn").exists()
    assert "--bin-dir is ignored" in result.stderr


def test_manage_install_maven_requires_repo(cli_runner, _home, monkeypatch):
    """Installing maven without --repo fails clearly."""
    monkeypatch.delenv("CLOUDSMITH_REPO", raising=False)
    result = cli_runner.invoke(install_cmd, ["maven", "--org", "acme", "--no-discover"])
    assert result.exit_code != 0


def test_manage_install_maven_requires_org(cli_runner, _home, monkeypatch):
    """Installing maven without --org fails clearly (no malformed empty-org URLs)."""
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    result = cli_runner.invoke(
        install_cmd, ["maven", "--repo", "prod", "--no-discover"]
    )
    assert result.exit_code != 0
