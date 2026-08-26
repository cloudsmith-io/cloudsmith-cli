# Copyright 2026 Cloudsmith Ltd
"""Tests for the Terraform credentials-helper installer and terraformrc block.

Covers the pure ``terraformrc`` block helpers (add/update/remove/conflict), the
``TerraformInstaller`` (launcher into the plugin dir + terraformrc block), and
the ``credential-helper install/uninstall terraform`` CLI wiring — including
that the resolved ``--org``/``-P`` land in the terraformrc ``args`` list.
"""

from __future__ import annotations

from pathlib import Path

import click.testing
import pytest

from ...credential_helpers.terraform import terraformrc
from ...credential_helpers.terraform.installer import TerraformInstaller

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
