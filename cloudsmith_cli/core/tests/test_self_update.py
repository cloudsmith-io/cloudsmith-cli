"""Standalone self-update - Tests."""

import hashlib
import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from unittest import mock

from .. import self_update


def build_bundle_tar(path, executable_name="cloudsmith", content=b"new-binary"):
    """Build a small onedir-style tar.gz bundle archive."""
    with tarfile.open(path, "w:gz") as tar:
        exe_info = tarfile.TarInfo(executable_name)
        exe_info.size = len(content)
        exe_info.mode = 0o755
        tar.addfile(exe_info, io.BytesIO(content))
        lib_info = tarfile.TarInfo("_internal/lib.so")
        lib_data = b"lib"
        lib_info.size = len(lib_data)
        tar.addfile(lib_info, io.BytesIO(lib_data))


def sha256_of(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class TestVerifySha256(unittest.TestCase):
    def test_accepts_matching_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "file")
            with open(path, "wb") as handle:
                handle.write(b"data")
            self_update.verify_sha256(path, hashlib.sha256(b"data").hexdigest())

    def test_rejects_mismatched_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "file")
            with open(path, "wb") as handle:
                handle.write(b"data")
            with self.assertRaises(self_update.SelfUpdateError):
                self_update.verify_sha256(path, "0" * 64)


class TestExtractArchive(unittest.TestCase):
    def test_extracts_tar_gz(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "bundle.tar.gz")
            build_bundle_tar(archive)
            staging = os.path.join(tmp, "staging")
            self_update.extract_archive(archive, staging)
            exe_path = os.path.join(staging, "cloudsmith")
            self.assertTrue(os.path.isfile(exe_path))
            self.assertTrue(os.access(exe_path, os.X_OK))
            self.assertTrue(os.path.isfile(os.path.join(staging, "_internal/lib.so")))

    def test_extracts_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "bundle.zip")
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("cloudsmith.exe", b"new-binary")
            staging = os.path.join(tmp, "staging")
            self_update.extract_archive(archive, staging)
            self.assertTrue(os.path.isfile(os.path.join(staging, "cloudsmith.exe")))


class TestSwapInstallDir(unittest.TestCase):
    def test_swaps_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = os.path.join(tmp, "cloudsmith")
            staging_dir = os.path.join(tmp, "cloudsmith.new")
            os.makedirs(install_dir)
            os.makedirs(staging_dir)
            with open(os.path.join(install_dir, "cloudsmith"), "w") as handle:
                handle.write("old")
            with open(os.path.join(staging_dir, "cloudsmith"), "w") as handle:
                handle.write("new")

            old_dir = self_update.swap_install_dir(install_dir, staging_dir)

            with open(os.path.join(install_dir, "cloudsmith")) as handle:
                self.assertEqual("new", handle.read())
            with open(os.path.join(old_dir, "cloudsmith")) as handle:
                self.assertEqual("old", handle.read())


class TestPerformSelfUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.install_dir = os.path.join(self.tmp.name, "cloudsmith")
        os.makedirs(os.path.join(self.install_dir, "_internal"))
        self.executable = os.path.join(self.install_dir, "cloudsmith")
        with open(self.executable, "w") as handle:
            handle.write("old-binary")
        self.archive = os.path.join(self.tmp.name, "fixture.tar.gz")
        build_bundle_tar(self.archive)

    def _manifest(self, sha256=None):
        return {
            "version": "1.26.0",
            "url": "https://dl.cloudsmith.io/example.tar.gz",
            "archive": "cloudsmith-1.26.0-macos-arm64.tar.gz",
            "sha256": sha256 or sha256_of(self.archive),
        }

    def _fake_download(self, url, dest_path, timeout=None):
        with open(self.archive, "rb") as src, open(dest_path, "wb") as dest:
            dest.write(src.read())

    def test_replaces_install_dir(self):
        with mock.patch.object(
            self_update, "download_archive", side_effect=self._fake_download
        ):
            self_update.perform_self_update(
                self._manifest(), executable_path=self.executable
            )
        with open(self.executable, "rb") as handle:
            self.assertEqual(b"new-binary", handle.read())
        self.assertFalse(os.path.exists(self.install_dir + ".old"))
        self.assertFalse(os.path.exists(self.install_dir + ".new"))

    def test_sha_mismatch_leaves_install_untouched(self):
        with mock.patch.object(
            self_update, "download_archive", side_effect=self._fake_download
        ):
            with self.assertRaises(self_update.SelfUpdateError):
                self_update.perform_self_update(
                    self._manifest(sha256="0" * 64),
                    executable_path=self.executable,
                )
        with open(self.executable) as handle:
            self.assertEqual("old-binary", handle.read())

    def test_rejects_manifest_without_url_or_sha256(self):
        for missing_key in ("url", "sha256"):
            manifest = self._manifest()
            del manifest[missing_key]
            with self.assertRaises(self_update.SelfUpdateError):
                self_update.perform_self_update(
                    manifest, executable_path=self.executable
                )

    def test_refuses_windows(self):
        with mock.patch.object(self_update.os, "name", "nt"):
            with self.assertRaises(self_update.SelfUpdateError):
                self_update.perform_self_update(
                    self._manifest(), executable_path=self.executable
                )

    def test_refuses_unwritable_parent(self):
        if os.name == "nt" or os.geteuid() == 0:
            self.skipTest("chmod-based write denial needs a non-root POSIX user")
        os.chmod(self.tmp.name, 0o500)
        self.addCleanup(os.chmod, self.tmp.name, 0o700)
        with self.assertRaises(self_update.SelfUpdateError):
            self_update.perform_self_update(
                self._manifest(), executable_path=self.executable
            )
