# Copyright 2026 Cloudsmith Ltd
"""Tests for cloudsmith_cli.core.self_update.

The self-update primitives are exercised against real files in a temp tree
(checksum, extraction, atomic swap). The network download is stubbed so no
test touches a remote.
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


class TestSwapInstallDir:
    def test_success(self, tmp_path):
        install = tmp_path / "install"
        install.mkdir()
        (install / "old").write_text("old")
        staging = tmp_path / "install.new"
        staging.mkdir()
        (staging / "new").write_text("new")

        old_dir = self_update.swap_install_dir(str(install), str(staging))

        assert (install / "new").exists()
        assert not (install / "old").exists()
        assert os.path.exists(old_dir)

    def test_rollback_on_failure(self, tmp_path, monkeypatch):
        install = tmp_path / "install"
        install.mkdir()
        (install / "keep").write_text("keep")
        staging = tmp_path / "install.new"
        staging.mkdir()

        real_rename = os.rename
        calls = {"n": 0}

        def flaky_rename(src, dst):
            calls["n"] += 1
            # First rename (install -> .old) succeeds; second (.new -> install)
            # fails; the rollback rename must restore the original.
            if calls["n"] == 2:
                raise OSError("boom")
            return real_rename(src, dst)

        monkeypatch.setattr(self_update.os, "rename", flaky_rename)
        with pytest.raises(OSError, match="boom"):
            self_update.swap_install_dir(str(install), str(staging))

        assert (install / "keep").read_text() == "keep"

    def test_rollback_when_executable_missing_after_swap(self, tmp_path):
        # A staging dir without the executable must not become the install; the
        # original must be restored so a botched bundle never empties the dir.
        install = tmp_path / "install"
        install.mkdir()
        (install / "cloudsmith").write_text("old-exe")
        (install / "_internal").mkdir()
        staging = tmp_path / "install.new"
        staging.mkdir()
        (staging / "unexpected").write_text("no exe here")

        with pytest.raises(self_update.SelfUpdateError, match="missing cloudsmith"):
            self_update.swap_install_dir(
                str(install), str(staging), executable_name="cloudsmith"
            )

        # Original install fully intact.
        assert (install / "cloudsmith").read_text() == "old-exe"
        assert (install / "_internal").is_dir()

    def test_failed_restore_preserves_old_and_reports_path(self, tmp_path, monkeypatch):
        # If the swap fails AND the restore also fails, the old install must be
        # preserved at <install>.old and the error must point the user to it.
        install = tmp_path / "install"
        install.mkdir()
        (install / "keep").write_text("keep")
        staging = tmp_path / "install.new"
        staging.mkdir()

        real_rename = os.rename
        calls = {"n": 0}

        def flaky_rename(src, dst):
            calls["n"] += 1
            # 1: install -> .old (ok); 2: .new -> install (fail);
            # 3: .old -> install restore (fail).
            if calls["n"] in (2, 3):
                raise OSError(f"boom{calls['n']}")
            return real_rename(src, dst)

        monkeypatch.setattr(self_update.os, "rename", flaky_rename)
        with pytest.raises(self_update.SelfUpdateError, match="preserved at"):
            self_update.swap_install_dir(str(install), str(staging))

        old_dir = tmp_path / "install.old"
        assert (old_dir / "keep").read_text() == "keep"


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
        # No scratch directories are left behind next to the install.
        assert not (tmp_path / "install.new").exists()
        assert not (tmp_path / "install.extract").exists()
        assert not (tmp_path / "install.old").exists()

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
