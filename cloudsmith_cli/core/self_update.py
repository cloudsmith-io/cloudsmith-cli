"""Self-update for the standalone CLI bundle."""

import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
import zipfile

DOWNLOAD_TIMEOUT_SECONDS = 120.0
_READ_CHUNK_BYTES = 1 << 20


class SelfUpdateError(Exception):
    """A self-update step failed."""


def download_archive(url, dest_path, timeout=DOWNLOAD_TIMEOUT_SECONDS):
    """Stream a release archive to a local file."""
    from .session import create_requests_session

    with create_requests_session().get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as dest:
            dest.writelines(response.iter_content(chunk_size=_READ_CHUNK_BYTES))


def verify_sha256(path, expected):
    """Verify the SHA-256 digest of a file against the manifest value."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected.strip().lower():
        raise SelfUpdateError(
            f"checksum mismatch for {os.path.basename(path)}: "
            f"expected {expected}, got {digest.hexdigest()}"
        )


def extract_archive(archive_path, dest_dir):
    """Extract a release archive (tar.gz or zip) into a directory."""
    os.makedirs(dest_dir, exist_ok=True)
    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as bundle:
            bundle.extractall(dest_dir)
        return
    with tarfile.open(archive_path, "r:gz") as bundle:
        bundle.extractall(dest_dir, filter="data")


def swap_install_dir(install_dir, staging_dir):
    """Replace the install directory with the staged one; return the old one."""
    old_dir = install_dir + ".old"
    if os.path.exists(old_dir):
        shutil.rmtree(old_dir)
    os.rename(install_dir, old_dir)
    try:
        os.rename(staging_dir, install_dir)
    except OSError:
        os.rename(old_dir, install_dir)
        raise
    return old_dir


def _check_replaceable(install_dir):
    if os.name == "nt":
        raise SelfUpdateError(
            "self-update cannot replace a running executable on Windows; "
            "download the new archive and replace the install directory"
        )
    parent = os.path.dirname(install_dir)
    if not (os.access(parent, os.W_OK) and os.access(install_dir, os.W_OK)):
        raise SelfUpdateError(
            f"the install directory {install_dir} is not writable; "
            "run the upgrade with sufficient privileges"
        )


def perform_self_update(manifest, executable_path=None):
    """Download, verify, and atomically install the bundle from a manifest."""
    missing = [key for key in ("url", "sha256") if not manifest.get(key)]
    if missing:
        raise SelfUpdateError(
            f"the release manifest is missing fields: {', '.join(missing)}"
        )
    executable_path = executable_path or sys.executable
    install_dir = os.path.dirname(os.path.realpath(executable_path))
    _check_replaceable(install_dir)

    parent = os.path.dirname(install_dir)
    staging_dir = install_dir + ".new"
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    suffix = ".zip" if manifest["url"].endswith(".zip") else ".tar.gz"
    archive_fd, archive_path = tempfile.mkstemp(dir=parent, suffix=suffix)
    os.close(archive_fd)
    try:
        download_archive(manifest["url"], archive_path)
        verify_sha256(archive_path, manifest["sha256"])
        extract_archive(archive_path, staging_dir)
        executable_name = os.path.basename(executable_path)
        if not os.path.isfile(os.path.join(staging_dir, executable_name)):
            raise SelfUpdateError(
                f"the downloaded bundle has no {executable_name} executable"
            )
        old_dir = swap_install_dir(install_dir, staging_dir)
    finally:
        if os.path.exists(archive_path):
            os.unlink(archive_path)
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
    shutil.rmtree(old_dir, ignore_errors=True)
