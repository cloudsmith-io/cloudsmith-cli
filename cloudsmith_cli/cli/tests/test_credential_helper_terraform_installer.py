# Copyright 2026 Cloudsmith Ltd
"""Tests for the Terraform credentials-helper installer and terraformrc block.

Covers the pure ``terraformrc`` block helpers (add/update/remove/conflict), the
``TerraformInstaller`` (launcher into the plugin dir + terraformrc block), and
the ``credential-helper install/uninstall terraform`` CLI wiring — including
that the resolved ``--org``/``-P`` land in the terraformrc ``args`` list.
"""

from __future__ import annotations

import json
from pathlib import Path

import click.testing
import pytest

from ...credential_helpers.terraform import installer as installer_mod, terraformrc
from ...credential_helpers.terraform.installer import (
    TerraformHelperExeNotFound,
    TerraformInstaller,
)

LAUNCHER = "terraform-credentials-cloudsmith"


def _launcher(home: Path) -> Path:
    """Return the default launcher path under a fake *home*."""
    return home / ".terraform.d" / "plugins" / LAUNCHER


@pytest.fixture()
def runner():
    """Return a CliRunner."""
    return click.testing.CliRunner()


# ---------------------------------------------------------------------------
# 1. terraformrc block helpers (pure text)
# ---------------------------------------------------------------------------


def test_render_block_formats_args():
    """render_block emits a valid HCL block with the args quoted."""
    block = terraformrc.render_block(["--org", "acme", "-P", "ci"])
    assert block == (
        'credentials_helper "cloudsmith" {\n  args = ["--org", "acme", "-P", "ci"]\n}'
    )


def test_render_block_empty_args():
    """No args renders an empty list, not a missing key."""
    assert "args = []" in terraformrc.render_block([])


def test_add_block_to_empty_file():
    """Adding to an empty file yields just the block plus a trailing newline."""
    new_text, changed = terraformrc.add_or_update_block("", ["--org", "acme"])
    assert changed is True
    assert new_text == terraformrc.render_block(["--org", "acme"]) + "\n"


def test_add_block_preserves_foreign_content():
    """Existing settings are kept and the block is appended after a blank line."""
    existing = 'plugin_cache_dir = "/tmp/x"\ndisable_checkpoint = true\n'
    new_text, changed = terraformrc.add_or_update_block(existing, [])
    assert changed is True
    assert new_text.startswith(existing)
    assert 'credentials_helper "cloudsmith"' in new_text


def test_update_replaces_existing_cloudsmith_block():
    """Re-adding with different args replaces the block in place."""
    first, _ = terraformrc.add_or_update_block("", ["--org", "acme"])
    second, changed = terraformrc.add_or_update_block(first, ["--org", "other"])
    assert changed is True
    assert second.count('credentials_helper "cloudsmith"') == 1
    assert '"other"' in second
    assert '"acme"' not in second


def test_add_is_idempotent():
    """Adding the identical block twice reports no change the second time."""
    first, _ = terraformrc.add_or_update_block("", ["--org", "acme"])
    second, changed = terraformrc.add_or_update_block(first, ["--org", "acme"])
    assert changed is False
    assert second == first


def test_add_raises_on_foreign_credentials_helper():
    """A credentials_helper for a different helper is a hard conflict."""
    existing = 'credentials_helper "vault" {\n  args = []\n}\n'
    with pytest.raises(terraformrc.TerraformrcConflictError) as exc:
        terraformrc.add_or_update_block(existing, [])
    assert exc.value.existing_name == "vault"


def test_remove_block_strips_only_cloudsmith():
    """remove_block drops the Cloudsmith block and collapses stray blank lines."""
    existing = (
        'plugin_cache_dir = "/tmp/x"\n\n'
        'credentials_helper "cloudsmith" {\n  args = []\n}\n'
    )
    new_text, changed = terraformrc.remove_block(existing)
    assert changed is True
    assert "credentials_helper" not in new_text
    assert new_text == 'plugin_cache_dir = "/tmp/x"\n'


def test_remove_block_leaves_foreign_helper_untouched():
    """A different helper's block is not removed."""
    existing = 'credentials_helper "vault" {\n  args = []\n}\n'
    new_text, changed = terraformrc.remove_block(existing)
    assert changed is False
    assert new_text == existing


def test_remove_block_no_block_is_noop():
    """Removing from a file without our block reports no change."""
    new_text, changed = terraformrc.remove_block("disable_checkpoint = true\n")
    assert changed is False


# ---------------------------------------------------------------------------
# 2. TerraformInstaller.install / uninstall / status
# ---------------------------------------------------------------------------


def test_installer_install_writes_launcher_and_block(tmp_path, monkeypatch):
    """install writes the launcher into the plugin dir and the terraformrc block."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)

    installer = TerraformInstaller()
    actions = installer.install(helper_args=("--org", "acme", "-P", "ci"))

    launcher = _launcher(tmp_path)
    assert launcher.exists()
    body = launcher.read_text(encoding="utf-8")
    assert "exec cloudsmith credential-helper terraform" in body

    rc = (tmp_path / ".terraformrc").read_text(encoding="utf-8")
    assert 'credentials_helper "cloudsmith"' in rc
    assert 'args = ["--org", "acme", "-P", "ci"]' in rc
    assert any("wrote launcher" in a for a in actions)


def test_installer_respects_bin_dir_override(tmp_path, monkeypatch):
    """--bin-dir overrides the default plugin directory for the launcher."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)
    custom = tmp_path / "custom_plugins"

    installer = TerraformInstaller()
    installer.install(bin_dir=str(custom))

    assert (custom / "terraform-credentials-cloudsmith").exists()
    # The default plugin dir must NOT have been used.
    assert not (tmp_path / ".terraform.d" / "plugins").exists()


def test_installer_dry_run_writes_nothing(tmp_path, monkeypatch):
    """dry_run reports planned actions without touching the filesystem."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)

    installer = TerraformInstaller()
    actions = installer.install(helper_args=("--org", "acme"), dry_run=True)

    assert not (tmp_path / ".terraformrc").exists()
    assert not (tmp_path / ".terraform.d" / "plugins").exists()
    assert any("would write launcher" in a for a in actions)
    assert any("would add" in a for a in actions)


def test_installer_idempotent(tmp_path, monkeypatch):
    """A second install reports the terraformrc is already up to date."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)

    installer = TerraformInstaller()
    installer.install(helper_args=("--org", "acme"))
    actions = installer.install(helper_args=("--org", "acme"))

    assert any("already up to date" in a for a in actions)


def test_installer_uninstall_removes_launcher_and_block(tmp_path, monkeypatch):
    """uninstall removes the launcher and the terraformrc block."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)

    installer = TerraformInstaller()
    installer.install(helper_args=("--org", "acme"))
    launcher = _launcher(tmp_path)
    assert launcher.exists()

    installer.uninstall()

    assert not launcher.exists()
    rc = (tmp_path / ".terraformrc").read_text(encoding="utf-8")
    assert "credentials_helper" not in rc


def test_installer_status_type_contract(tmp_path, monkeypatch):
    """status()['launcher'] is str when installed and None when not — never Path."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)

    installer = TerraformInstaller()

    before = installer.status()
    assert before["launcher"] is None
    assert before["hosts"] == []

    installer.install(helper_args=("--org", "acme"))
    after = installer.status()
    assert isinstance(after["launcher"], str)
    assert after["launcher"].endswith("terraform-credentials-cloudsmith")
    assert after["hosts"]  # non-empty marker


# ---------------------------------------------------------------------------
# 3. CLI wiring — install/uninstall terraform
# ---------------------------------------------------------------------------


def test_cli_install_bakes_org_and_profile_into_args(runner, tmp_path, monkeypatch):
    """`install terraform --org --P` writes those into the terraformrc args list."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)

    from ...cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        [
            "terraform",
            "--org=acme",
            "-P",
            "ci",
            "--no-discover",
            "-k",
            "k_flag",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    rc = (tmp_path / ".terraformrc").read_text(encoding="utf-8")
    assert 'args = ["--org", "acme", "-P", "ci"]' in rc


@pytest.mark.parametrize(
    "repo_flag",
    [
        ["-r", "my-repo"],
        ["--repo", "my-repo"],
        ["--repository", "my-repo"],
        ["--repo=my-repo"],
    ],
)
def test_cli_install_bakes_repo_into_args(runner, tmp_path, monkeypatch, repo_flag):
    """`install terraform --repo` writes `-r <repo>` into the terraformrc args."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)

    from ...cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        ["terraform", "--org=acme", *repo_flag, "--no-discover", "-k", "k_flag"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    rc = (tmp_path / ".terraformrc").read_text(encoding="utf-8")
    assert 'args = ["--org", "acme", "-r", "my-repo"]' in rc


def test_cli_install_with_repo_suppresses_next_steps(runner, tmp_path, monkeypatch):
    """A baked-in repository means the repository guidance is not printed."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)

    from ...cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        [
            "terraform",
            "--org=acme",
            "--repo",
            "my-repo",
            "--no-discover",
            "-k",
            "k_flag",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert "Next steps" not in result.output
    assert "CLOUDSMITH_REPO" not in result.output


def test_cli_install_conflict_is_clean_error(runner, tmp_path, monkeypatch):
    """A pre-existing foreign credentials_helper yields a ClickException, not a traceback."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)
    (tmp_path / ".terraformrc").write_text(
        'credentials_helper "vault" {\n  args = []\n}\n', encoding="utf-8"
    )

    from ...cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        ["terraform", "--no-discover", "-k", "k_flag"],
        catch_exceptions=False,
    )

    assert result.exit_code != 0
    assert "only one credentials_helper" in result.output
    # The launcher must not have been written when the terraformrc conflicts.
    launcher = _launcher(tmp_path)
    assert not launcher.exists()


def test_cli_install_prints_repo_next_steps(runner, tmp_path, monkeypatch):
    """install terraform prints guidance about the required repository."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)

    from ...cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        ["terraform", "--org=acme", "-P", "ci", "--no-discover", "-k", "k_flag"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    out = result.output
    assert "Next steps" in out
    assert "CLOUDSMITH_REPO" in out
    assert "--repo" in out


def test_cli_install_repo_next_steps_in_json(runner, tmp_path, monkeypatch):
    """The repository guidance is surfaced as a next_steps field in JSON mode."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)

    from ...cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        ["terraform", "--no-discover", "-k", "k_flag", "-F", "json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    next_steps = payload["data"]["next_steps"]
    assert next_steps
    assert any("CLOUDSMITH_REPO" in line for line in next_steps)


def test_cli_install_docker_has_no_next_steps(runner, tmp_path, monkeypatch):
    """Non-terraform helpers do not emit the terraform repository guidance."""
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / ".docker"))

    from ...cli.commands.credential_helper.manage import install_cmd

    result = runner.invoke(
        install_cmd,
        ["docker", "--no-discover", "-k", "k_flag", "-F", "json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["next_steps"] == []


def test_next_steps_uses_resolved_rc_path(tmp_path, monkeypatch):
    """The repository guidance names the resolved config file, not a hardcoded path.

    Driven via ``TF_CLI_CONFIG_FILE`` so the assertion holds on every platform
    (on Windows the default would be ``%APPDATA%\\terraform.rc``, not
    ``~/.terraformrc`` — the bug this guards against).
    """
    rc = tmp_path / "custom.tfrc"
    monkeypatch.setenv("TF_CLI_CONFIG_FILE", str(rc))

    from ...cli.commands.credential_helper.manage import _terraform_next_steps

    steps = _terraform_next_steps(())
    assert steps
    assert any(str(rc) in line for line in steps)
    assert not any("~/.terraformrc" in line for line in steps)


def test_conflict_error_uses_resolved_rc_path(tmp_path, monkeypatch):
    """A foreign-helper conflict names the resolved config file, not ~/.terraformrc."""
    rc = tmp_path / "custom.tfrc"
    rc.write_text('credentials_helper "vault" {\n  args = []\n}\n', encoding="utf-8")
    monkeypatch.setenv("TF_CLI_CONFIG_FILE", str(rc))

    installer = TerraformInstaller()
    with pytest.raises(terraformrc.TerraformrcConflictError) as exc:
        installer.install(helper_args=("--org", "acme"))

    assert str(rc) in str(exc.value)
    assert "~/.terraformrc" not in str(exc.value)


# ---------------------------------------------------------------------------
# 4. Windows launcher — a real .exe, not a .cmd (Terraform ignores .cmd)
# ---------------------------------------------------------------------------


def _force_windows(monkeypatch):
    """Make the installer take its Windows branch without patching os.name.

    Patching ``os.name`` would make ``pathlib`` build a ``WindowsPath`` and
    raise on a POSIX host (even inside pytest's own reporting), so the installer
    exposes ``_is_windows()`` as the single seam to override instead.
    """
    monkeypatch.setattr(TerraformInstaller, "_is_windows", staticmethod(lambda: True))


def test_plugin_path_is_exe_on_windows(monkeypatch, tmp_path):
    """On Windows the launcher is a real .exe (Terraform ignores .cmd shims)."""
    _force_windows(monkeypatch)
    installer = TerraformInstaller()
    path = installer._plugin_path(tmp_path)
    assert path.name == f"{LAUNCHER}.exe"


def test_resolve_helper_exe_prefers_frozen_sibling(monkeypatch, tmp_path):
    """When frozen, the sibling exe next to sys.executable is used."""
    sibling = tmp_path / "terraform-credentials-cloudsmith"
    sibling.write_text("x", encoding="utf-8")
    monkeypatch.setattr(installer_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        installer_mod.sys, "executable", str(tmp_path / "cloudsmith"), raising=False
    )
    # PATH lookup must not be consulted when the frozen sibling exists.
    monkeypatch.setattr(installer_mod.shutil, "which", lambda _n: None)

    assert TerraformInstaller._resolve_helper_exe() == sibling.resolve()


def test_resolve_helper_exe_falls_back_to_path(monkeypatch, tmp_path):
    """A pip install resolves the [project.scripts]-generated exe via PATH."""
    on_path = tmp_path / "terraform-credentials-cloudsmith"
    on_path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(installer_mod.sys, "frozen", False, raising=False)
    monkeypatch.setattr(installer_mod.shutil, "which", lambda _n: str(on_path))

    assert TerraformInstaller._resolve_helper_exe() == on_path.resolve()


def test_windows_install_copies_real_exe(monkeypatch, tmp_path):
    """On Windows, install copies a genuine exe into the plugin dir."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)
    _force_windows(monkeypatch)

    source = tmp_path / "src" / "terraform-credentials-cloudsmith.exe"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"MZfake-pe")
    monkeypatch.setattr(
        TerraformInstaller, "_resolve_helper_exe", classmethod(lambda cls: source)
    )

    installer = TerraformInstaller()
    custom = tmp_path / "plugins"
    installer.install(bin_dir=str(custom), helper_args=("--org", "acme"))

    dest = custom / f"{LAUNCHER}.exe"
    assert dest.exists()
    assert dest.read_bytes() == b"MZfake-pe"


def test_windows_install_errors_when_no_exe(monkeypatch, tmp_path):
    """A clean error (not a traceback) when no real exe can be located."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)
    _force_windows(monkeypatch)
    monkeypatch.setattr(
        TerraformInstaller, "_resolve_helper_exe", classmethod(lambda cls: None)
    )

    installer = TerraformInstaller()
    with pytest.raises(TerraformHelperExeNotFound):
        installer.install(bin_dir=str(tmp_path / "plugins"))

    # The terraformrc must not have been written when the launcher can't be.
    assert not (tmp_path / ".terraformrc").exists()


def test_windows_uninstall_removes_exe(monkeypatch, tmp_path):
    """Uninstall removes the .exe launcher on Windows."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("TF_CLI_CONFIG_FILE", raising=False)
    _force_windows(monkeypatch)

    source = tmp_path / "terraform-credentials-cloudsmith.exe"
    source.write_bytes(b"MZfake-pe")
    monkeypatch.setattr(
        TerraformInstaller, "_resolve_helper_exe", classmethod(lambda cls: source)
    )

    installer = TerraformInstaller()
    custom = tmp_path / "plugins"
    installer.install(bin_dir=str(custom))
    dest = custom / f"{LAUNCHER}.exe"
    assert dest.exists()

    installer.uninstall(bin_dir=str(custom))
    assert not dest.exists()
