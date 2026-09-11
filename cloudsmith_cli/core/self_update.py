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


def download_archive(url, dest_path, session=None, timeout=DOWNLOAD_TIMEOUT_SECONDS):
    """Stream a release archive to a local file.

    ``session`` is the shared requests session so proxy/CA/user-agent settings
    apply; when omitted a plain session is created.
    """
    if session is None:
        from .session import create_requests_session

        session = create_requests_session()

    with session.get(url, stream=True, timeout=timeout) as response:
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


def find_bundle_root(extract_dir, executable_name):
    """Return the directory holding ``executable_name`` inside an extraction.

    The release archives wrap the onedir bundle in a top-level directory
    (``cloudsmith/cloudsmith`` etc.), so the executable is one level below the
    extraction root. Older/flat archives put it at the root. This handles both:
    it returns ``extract_dir`` when the executable sits there, otherwise the
    lone wrapper subdirectory that contains it. Raises ``SelfUpdateError`` when
    no such executable is found.
    """
    if os.path.isfile(os.path.join(extract_dir, executable_name)):
        return extract_dir
    entries = [os.path.join(extract_dir, name) for name in os.listdir(extract_dir)]
    subdirs = [path for path in entries if os.path.isdir(path)]
    for subdir in subdirs:
        if os.path.isfile(os.path.join(subdir, executable_name)):
            return subdir
    raise SelfUpdateError(f"the downloaded bundle has no {executable_name} executable")


def swap_install_dir(install_dir, staging_dir, executable_name=None):
    """Replace the install directory with the staged one; return the old one.

    Same-filesystem, atomic-``rename`` swap so both the move-aside and the
    install are all-or-nothing (``.old``/``.new`` are siblings of the install,
    never on ``/tmp``, which may be a different filesystem and force a
    non-atomic copy).

    Flow: move ``install_dir`` aside to ``<install_dir>.old``, move
    ``staging_dir`` into its place, then verify the executable is present. On
    any failure the original is restored from ``.old`` before raising, so a
    failed swap always leaves a working install. If the restore itself fails,
    a :class:`SelfUpdateError` names where the previous install is preserved so
    the user can recover it by hand.
    """
    old_dir = install_dir + ".old"
    if os.path.exists(old_dir):
        shutil.rmtree(old_dir)
    os.rename(install_dir, old_dir)
    try:
        os.rename(staging_dir, install_dir)
        if executable_name is not None and not os.path.isfile(
            os.path.join(install_dir, executable_name)
        ):
            raise SelfUpdateError(
                f"the installed bundle is missing {executable_name} after swap"
            )
    except (OSError, SelfUpdateError) as exc:
        _restore_from_old(install_dir, old_dir, exc)
        raise
    return old_dir


def _restore_from_old(install_dir, old_dir, original_exc):
    """Restore ``install_dir`` from ``old_dir`` after a failed swap.

    Removes a half-swapped install, then moves the preserved copy back. If the
    restore cannot complete, raises a :class:`SelfUpdateError` that names the
    surviving ``old_dir`` so the previous install is never silently lost.
    """
    if os.path.exists(install_dir):
        shutil.rmtree(install_dir, ignore_errors=True)
    try:
        os.rename(old_dir, install_dir)
    except OSError as restore_exc:
        raise SelfUpdateError(
            f"update failed ({original_exc}) and the previous install could not "
            f"be restored ({restore_exc}); your working install is preserved at "
            f"{old_dir} - move it back to {install_dir} to recover"
        ) from restore_exc


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


def perform_self_update(manifest, executable_path=None, session=None):
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
    executable_name = os.path.basename(executable_path)
    # Extraction scratch dir and the final swap-in dir are kept separate so the
    # swap source is never nested inside a directory we later clean up.
    extract_dir = install_dir + ".extract"
    staging_dir = install_dir + ".new"
    for scratch in (extract_dir, staging_dir):
        if os.path.exists(scratch):
            shutil.rmtree(scratch)
    suffix = ".zip" if manifest["url"].endswith(".zip") else ".tar.gz"
    archive_fd, archive_path = tempfile.mkstemp(dir=parent, suffix=suffix)
    os.close(archive_fd)
    old_dir = None
    try:
        download_archive(manifest["url"], archive_path, session=session)
        verify_sha256(archive_path, manifest["sha256"])
        extract_archive(archive_path, extract_dir)
        bundle_root = find_bundle_root(extract_dir, executable_name)
        # Promote the real bundle root out of the extraction scratch dir into a
        # standalone staging dir, so swapping it in cannot be undone by cleaning
        # up the extraction dir afterwards.
        os.rename(bundle_root, staging_dir)
        if not os.path.isfile(os.path.join(staging_dir, executable_name)):
            raise SelfUpdateError(
                f"the downloaded bundle has no {executable_name} executable"
            )
        old_dir = swap_install_dir(
            install_dir, staging_dir, executable_name=executable_name
        )
    finally:
        if os.path.exists(archive_path):
            os.unlink(archive_path)
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        # staging_dir only survives here if the swap did not consume it (i.e. a
        # failure before/at swap); remove it so a retry starts clean.
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
    if old_dir is not None:
        shutil.rmtree(old_dir, ignore_errors=True)
