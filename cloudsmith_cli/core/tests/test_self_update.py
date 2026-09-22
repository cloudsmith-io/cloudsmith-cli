# Copyright 2026 Cloudsmith Ltd
"""Tests for cloudsmith_cli.core.self_update.

The self-update primitives are exercised against real files in a temp tree
(checksum, extraction, entry-scoped replacement). The network download is
stubbed so no test touches a remote.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import zipfile

import pytest

from cloudsmith_cli.core import self_update


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()


class TestVerifySha256:
    def test_match(self, tmp_path):
        f = tmp_path / "blob"
        f.write_bytes(b"hello")
        self_update.verify_sha256(str(f), _sha256(str(f)))

    def test_match_uppercase_and_whitespace(self, tmp_path):
        f = tmp_path / "blob"
        f.write_bytes(b"hello")
        self_update.verify_sha256(str(f), f"  {_sha256(str(f)).upper()}  ")

    def test_mismatch(self, tmp_path):
        f = tmp_path / "blob"
        f.write_bytes(b"hello")
        with pytest.raises(self_update.SelfUpdateError, match="checksum mismatch"):
            self_update.verify_sha256(str(f), "0" * 64)


class TestExtractArchive:
    def test_targz(self, tmp_path):
        member = tmp_path / "cloudsmith"
        member.write_text("binary")
        archive = tmp_path / "bundle.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(member, arcname="cloudsmith")
        dest = tmp_path / "out"
        self_update.extract_archive(str(archive), str(dest))
        assert (dest / "cloudsmith").read_text() == "binary"

    def test_zip(self, tmp_path):
        archive = tmp_path / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("cloudsmith", "binary")
        dest = tmp_path / "out"
        self_update.extract_archive(str(archive), str(dest))
        assert (dest / "cloudsmith").read_text() == "binary"

    def test_targz_nested_dir(self, tmp_path):
        """A wrapped onedir bundle extracts on every supported Python.

        This exercises the pre-3.12 safe-extraction path (no ``filter=`` kwarg
        on 3.10/3.11) as well as ``filter="data"`` on 3.12+.
        """
        member = tmp_path / "cloudsmith"
        member.write_text("binary")
        archive = tmp_path / "bundle.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(member, arcname="cloudsmith/cloudsmith")
        dest = tmp_path / "out"
        self_update.extract_archive(str(archive), str(dest))
        assert (dest / "cloudsmith" / "cloudsmith").read_text() == "binary"

    def test_corrupt_targz_raises_self_update_error(self, tmp_path):
        archive = tmp_path / "bundle.tar.gz"
        archive.write_bytes(b"not a gzip stream")
        dest = tmp_path / "out"
        with pytest.raises(self_update.SelfUpdateError, match="could not be read"):
            self_update.extract_archive(str(archive), str(dest))

    def test_corrupt_zip_raises_self_update_error(self, tmp_path):
        archive = tmp_path / "bundle.zip"
        archive.write_bytes(b"PK\x03\x04 not really a zip")
        dest = tmp_path / "out"
        with pytest.raises(self_update.SelfUpdateError, match="could not be read"):
            self_update.extract_archive(str(archive), str(dest))

    def test_tar_traversal_member_rejected(self, tmp_path):
        """A member escaping the extraction root is rejected on all Pythons."""
        evil = tmp_path / "evil"
        evil.write_text("owned")
        archive = tmp_path / "bundle.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(evil, arcname="../escape")
        dest = tmp_path / "out"
        with pytest.raises(self_update.SelfUpdateError):
            self_update.extract_archive(str(archive), str(dest))
        assert not (tmp_path / "escape").exists()

    def test_zip_traversal_member_rejected(self, tmp_path):
        archive = tmp_path / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("../escape", "owned")
        dest = tmp_path / "out"
        with pytest.raises(
            self_update.SelfUpdateError, match="escapes the extraction directory"
        ):
            self_update.extract_archive(str(archive), str(dest))
        assert not (tmp_path / "escape").exists()


class TestReplaceBundleEntries:
    def _install(self, tmp_path):
        """A pristine install dir with a bundle exe + _internal dir."""
        install = tmp_path / "install"
        install.mkdir()
        (install / "cloudsmith").write_text("old-exe")
        (install / "_internal").mkdir()
        (install / "_internal" / "d").write_text("old-dep")
        return install

    def _staging(self, tmp_path, *, exe="cloudsmith"):
        """A staged new bundle with a new exe + _internal dir."""
        staging = tmp_path / "install.new"
        staging.mkdir()
        (staging / exe).write_text("new-exe")
        (staging / "_internal").mkdir()
        (staging / "_internal" / "d").write_text("new-dep")
        return staging

    def test_success_replaces_bundle_entries(self, tmp_path):
        install = self._install(tmp_path)
        staging = self._staging(tmp_path)

        backup = self_update.replace_bundle_entries(
            str(install), str(staging), executable_name="cloudsmith"
        )

        assert (install / "cloudsmith").read_text() == "new-exe"
        assert (install / "_internal" / "d").read_text() == "new-dep"
        # The backup dir (a SIBLING of install_dir) is returned for the caller
        # to remove; it holds the old bundle entries only.
        assert os.path.exists(backup)
        assert backup == str(install) + self_update._BACKUP_DIR_SUFFIX
        assert os.path.exists(os.path.join(backup, "cloudsmith"))

    def test_user_files_are_never_touched(self, tmp_path):
        # The core safety property: files the user keeps alongside the CLI must
        # survive an update untouched, because they are not bundle entries.
        install = self._install(tmp_path)
        (install / "my-notes.txt").write_text("keep me")
        user_dir = install / "user-dir"
        user_dir.mkdir()
        (user_dir / "x").write_text("keep dir")
        staging = self._staging(tmp_path)

        inode_before = os.stat(install).st_ino
        self_update.replace_bundle_entries(
            str(install), str(staging), executable_name="cloudsmith"
        )

        assert (install / "my-notes.txt").read_text() == "keep me"
        assert (user_dir / "x").read_text() == "keep dir"
        # The install directory itself is never renamed, so its inode is stable
        # (a shell whose cwd is here keeps working).
        assert os.stat(install).st_ino == inode_before

    def test_missing_executable_rejected_before_any_move(self, tmp_path, monkeypatch):
        # A staged bundle without the executable is rejected before anything in
        # the live install is moved, so the original is never even at risk.
        install = self._install(tmp_path)
        staging = self._staging(tmp_path, exe="not-cloudsmith")

        def guard_rename(src, dst):
            raise AssertionError(f"nothing must be moved: rename({src}, {dst})")

        monkeypatch.setattr(self_update.os, "rename", guard_rename)
        with pytest.raises(
            self_update.SelfUpdateError, match="missing cloudsmith before replace"
        ):
            self_update.replace_bundle_entries(
                str(install), str(staging), executable_name="cloudsmith"
            )

        assert (install / "cloudsmith").read_text() == "old-exe"
        assert not os.path.exists(str(install) + self_update._BACKUP_DIR_SUFFIX)

    def test_rollback_restores_original_and_keeps_user_files(
        self, tmp_path, monkeypatch
    ):
        # A failure partway through the per-entry loop must restore every moved
        # bundle entry AND leave user files untouched.
        install = self._install(tmp_path)
        (install / "my-notes.txt").write_text("keep me")
        staging = self._staging(tmp_path)
        # Add a second bundle entry so the loop moves more than one thing.
        (staging / "terraform-credentials-cloudsmith").write_text("new-tf")
        (install / "terraform-credentials-cloudsmith").write_text("old-tf")

        real_rename = os.rename
        calls = {"n": 0}

        def flaky_rename(src, dst):
            calls["n"] += 1
            # Fail on the 3rd rename (partway through the entry loop) to force a
            # rollback of what has been applied so far.
            if calls["n"] == 3:
                raise OSError("boom")
            return real_rename(src, dst)

        monkeypatch.setattr(self_update.os, "rename", flaky_rename)
        with pytest.raises(OSError, match="boom"):
            self_update.replace_bundle_entries(
                str(install), str(staging), executable_name="cloudsmith"
            )

        # Original bundle entries restored, user file intact.
        assert (install / "cloudsmith").read_text() == "old-exe"
        assert (install / "_internal" / "d").read_text() == "old-dep"
        assert (install / "terraform-credentials-cloudsmith").read_text() == "old-tf"
        assert (install / "my-notes.txt").read_text() == "keep me"

    def test_failed_rollback_reports_backup_paths(self, tmp_path, monkeypatch):
        # If the replacement fails AND a restore also fails, the error must name
        # the surviving backup so the user can recover by hand.
        install = self._install(tmp_path)
        staging = self._staging(tmp_path)

        # Entries are processed sorted, so `_internal` is handled before
        # `cloudsmith`: rename 1 moves install/_internal -> backup (ok); rename
        # 2 (staging/_internal -> install) fails and triggers rollback; rename 3
        # (backup/_internal restore) also fails.
        real_rename = os.rename
        calls = {"n": 0}

        def flaky_rename(src, dst):
            calls["n"] += 1
            if calls["n"] in (2, 3):
                raise OSError(f"boom{calls['n']}")
            return real_rename(src, dst)

        monkeypatch.setattr(self_update.os, "rename", flaky_rename)
        with pytest.raises(self_update.SelfUpdateError, match="could not be restored"):
            self_update.replace_bundle_entries(
                str(install), str(staging), executable_name="cloudsmith"
            )

        # The un-restored original entry is preserved in the backup dir so the
        # user can recover it by hand.
        backup = install.parent / (install.name + self_update._BACKUP_DIR_SUFFIX)
        assert (backup / "_internal" / "d").read_text() == "old-dep"


class TestFindBundleRoot:
    def test_flat_layout(self, tmp_path):
        (tmp_path / "cloudsmith").write_text("exe")
        assert self_update.find_bundle_root(str(tmp_path), "cloudsmith") == str(
            tmp_path
        )

    def test_wrapped_layout(self, tmp_path):
        # The real release archives wrap the bundle in a top-level directory.
        wrapper = tmp_path / "cloudsmith"
        wrapper.mkdir()
        (wrapper / "cloudsmith").write_text("exe")
        (wrapper / "_internal").mkdir()
        assert self_update.find_bundle_root(str(tmp_path), "cloudsmith") == str(wrapper)

    def test_missing_executable_raises(self, tmp_path):
        (tmp_path / "somedir").mkdir()
        with pytest.raises(self_update.SelfUpdateError, match="no cloudsmith"):
            self_update.find_bundle_root(str(tmp_path), "cloudsmith")


class TestPerformSelfUpdate:
    def _make_bundle(self, tmp_path, exe_name="cloudsmith", wrap=False):
        """Build a release tar.gz.

        ``wrap=True`` nests members under a top-level ``cloudsmith/`` directory,
        matching what the release workflow publishes; ``wrap=False`` puts them
        at the archive root (flat).
        """
        staging = tmp_path / "staging"
        base = staging / "cloudsmith" if wrap else staging
        base.mkdir(parents=True)
        (base / exe_name).write_text("new-binary")
        (base / "_internal").mkdir()
        (base / "_internal" / "data").write_text("dep")
        archive = tmp_path / "bundle.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for child in sorted(staging.iterdir()):
                tar.add(child, arcname=child.name)
        shutil.rmtree(staging)
        return archive

    def test_missing_fields(self):
        with pytest.raises(self_update.SelfUpdateError, match="missing fields"):
            self_update.perform_self_update({"url": "http://x/a.tar.gz"})

    def test_windows_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(self_update.os, "name", "nt")
        exe = tmp_path / "install" / "cloudsmith"
        exe.parent.mkdir()
        exe.write_text("x")
        with pytest.raises(self_update.SelfUpdateError, match="Windows"):
            self_update.perform_self_update(
                {"url": "http://x/a.tar.gz", "sha256": "0" * 64},
                executable_path=str(exe),
            )

    @pytest.mark.parametrize("wrap", [False, True], ids=["flat", "wrapped"])
    def test_happy_path(self, tmp_path, monkeypatch, wrap):
        install = tmp_path / "install"
        install.mkdir()
        exe = install / "cloudsmith"
        exe.write_text("old-binary")

        archive = self._make_bundle(tmp_path, wrap=wrap)
        expected_sha = _sha256(str(archive))

        def fake_download(url, dest_path, session=None, timeout=None):
            shutil.copyfile(str(archive), dest_path)

        monkeypatch.setattr(self_update, "download_archive", fake_download)

        inode_before = os.stat(install).st_ino
        self_update.perform_self_update(
            {"url": "http://x/bundle.tar.gz", "sha256": expected_sha},
            executable_path=str(exe),
        )
        # The executable is a file directly in install_dir (no double-nesting),
        # and its sibling data came along.
        assert exe.is_file()
        assert exe.read_text() == "new-binary"
        assert (install / "_internal" / "data").read_text() == "dep"
        assert not (install / "cloudsmith").is_dir()
        # The install directory is replaced entry-scoped, never renamed: its
        # inode is stable so a shell whose cwd is here keeps working.
        assert os.stat(install).st_ino == inode_before
        # No scratch directories are left behind next to the install.
        assert not (tmp_path / "install.new").exists()
        assert not (tmp_path / "install.extract").exists()
        assert not (install.parent / (install.name + "-BACKUP")).exists()
        assert not (install / self_update._BACKUP_DIR_SUFFIX).exists()

    @pytest.mark.parametrize("wrap", [False, True], ids=["flat", "wrapped"])
    def test_user_files_survive_full_update(self, tmp_path, monkeypatch, wrap):
        # End-to-end: a user file kept alongside the CLI survives a real update.
        install = tmp_path / "install"
        install.mkdir()
        exe = install / "cloudsmith"
        exe.write_text("old-binary")
        (install / "my-notes.txt").write_text("keep me")
        user_dir = install / "user-dir"
        user_dir.mkdir()
        (user_dir / "x").write_text("keep dir")

        archive = self._make_bundle(tmp_path, wrap=wrap)
        expected_sha = _sha256(str(archive))

        def fake_download(url, dest_path, session=None, timeout=None):
            shutil.copyfile(str(archive), dest_path)

        monkeypatch.setattr(self_update, "download_archive", fake_download)

        self_update.perform_self_update(
            {"url": "http://x/bundle.tar.gz", "sha256": expected_sha},
            executable_path=str(exe),
        )
        assert exe.read_text() == "new-binary"
        assert (install / "my-notes.txt").read_text() == "keep me"
        assert (user_dir / "x").read_text() == "keep dir"

    def test_missing_executable_in_bundle(self, tmp_path, monkeypatch):
        install = tmp_path / "install"
        install.mkdir()
        exe = install / "cloudsmith"
        exe.write_text("old-binary")

        # Bundle contains a differently-named executable.
        archive = self._make_bundle(tmp_path, exe_name="not-cloudsmith")
        expected_sha = _sha256(str(archive))

        def fake_download(url, dest_path, session=None, timeout=None):
            shutil.copyfile(str(archive), dest_path)

        monkeypatch.setattr(self_update, "download_archive", fake_download)

        with pytest.raises(self_update.SelfUpdateError, match="no cloudsmith"):
            self_update.perform_self_update(
                {"url": "http://x/bundle.tar.gz", "sha256": expected_sha},
                executable_path=str(exe),
            )
        # The original install must remain intact after a failed update.
        assert exe.read_text() == "old-binary"
