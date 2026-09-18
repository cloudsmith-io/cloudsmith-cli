"""Self-update for the standalone CLI bundle."""

import hashlib
import logging
import os
import shutil
import sys
import tarfile
import tempfile
import zipfile

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 120.0
_READ_CHUNK_BYTES = 1 << 20


class SelfUpdateError(Exception):
    """A self-update step failed."""


def _abspath(path):
    """Return an absolute path for logging, tolerating cwd errors."""
    try:
        return os.path.abspath(path)
    except OSError:
        return path


def _log_rename(src, dst):
    """``os.rename`` with a debug log of the full source and destination."""
    logger.debug("MOVE %s -> %s", _abspath(src), _abspath(dst))
    os.rename(src, dst)


def _log_rmtree(path, *, ignore_errors=False):
    """``shutil.rmtree`` with a debug log of the full path removed."""
    logger.debug("DELETE (recursive) %s", _abspath(path))
    shutil.rmtree(path, ignore_errors=ignore_errors)


def _log_unlink(path):
    """``os.unlink`` with a debug log of the full path removed."""
    logger.debug("DELETE %s", _abspath(path))
    os.unlink(path)


def _log_makedirs(path, **kwargs):
    """``os.makedirs`` with a debug log of the full path created."""
    logger.debug("MKDIR %s", _abspath(path))
    os.makedirs(path, **kwargs)


def _log_listdir(label, path):
    """Debug-log the full paths of a directory's immediate contents."""
    try:
        entries = sorted(os.listdir(path))
    except OSError as exc:
        logger.debug("LIST %s (%s): <error: %s>", label, _abspath(path), exc)
        return
    logger.debug(
        "LIST %s (%s): %s",
        label,
        _abspath(path),
        [_abspath(os.path.join(path, name)) for name in entries],
    )


def download_archive(url, dest_path, session=None, timeout=DOWNLOAD_TIMEOUT_SECONDS):
    """Stream a release archive to a local file.

    ``session`` is the shared requests session so proxy/CA/user-agent settings
    apply; when omitted a plain session is created.
    """
    if session is None:
        from .session import create_requests_session

        session = create_requests_session()

    logger.debug("DOWNLOAD %s -> WRITE %s", url, _abspath(dest_path))
    with session.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as dest:
            dest.writelines(response.iter_content(chunk_size=_READ_CHUNK_BYTES))
    logger.debug("WROTE %s (%d bytes)", _abspath(dest_path), os.path.getsize(dest_path))


def verify_sha256(path, expected):
    """Verify the SHA-256 digest of a file against the manifest value."""
    logger.debug("VERIFY sha256 of %s", _abspath(path))
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
    logger.debug("EXTRACT %s -> %s", _abspath(archive_path), _abspath(dest_dir))
    _log_makedirs(dest_dir, exist_ok=True)
    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as bundle:
            for name in bundle.namelist():
                logger.debug(
                    "EXTRACT member %s", _abspath(os.path.join(dest_dir, name))
                )
            bundle.extractall(dest_dir)
        return
    with tarfile.open(archive_path, "r:gz") as bundle:
        for name in bundle.getnames():
            logger.debug("EXTRACT member %s", _abspath(os.path.join(dest_dir, name)))
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
        logger.debug("BUNDLE ROOT (flat) %s", _abspath(extract_dir))
        return extract_dir
    entries = [os.path.join(extract_dir, name) for name in os.listdir(extract_dir)]
    logger.debug(
        "BUNDLE ROOT search under %s, entries: %s",
        _abspath(extract_dir),
        [_abspath(entry) for entry in entries],
    )
    subdirs = [path for path in entries if os.path.isdir(path)]
    for subdir in subdirs:
        if os.path.isfile(os.path.join(subdir, executable_name)):
            logger.debug("BUNDLE ROOT (wrapped) %s", _abspath(subdir))
            return subdir
    raise SelfUpdateError(f"the downloaded bundle has no {executable_name} executable")


#: Name of the sibling directory where bundle-owned entries are backed up during
#: an entry-scoped replacement so a failure can be rolled back. It only ever
#: holds files the CLI itself moved there (never user files), so removing it is
#: always safe.
_BACKUP_DIR_SUFFIX = ".cloudsmith-update-backup"
_EXTRACT_DIR_SUFFIX = ".extract"
_STAGING_DIR_SUFFIX = ".new"
_SCRATCH_SUFFIXES = (_EXTRACT_DIR_SUFFIX, _STAGING_DIR_SUFFIX, _BACKUP_DIR_SUFFIX)


def replace_bundle_entries(install_dir, staging_dir, executable_name=None):
    """Replace only the bundle-owned top-level entries inside ``install_dir``.

    The install directory itself is **never** renamed or removed, and only the
    top-level names present in the *new* bundle (``staging_dir``) are touched.
    Any other file or directory the user keeps alongside the CLI (they may have
    extracted the release into a shared directory) is left completely untouched.
    This is the core safety property: self-update can never delete user data.

    For each incoming entry the existing same-named entry (if any) is moved into
    a private backup directory, then the incoming entry is moved into place. On
    any failure every moved entry is rolled back from the backup so the original
    install is restored before raising. On success the backup — which only ever
    held bundle-owned entries the CLI moved there itself — is removed.

    Tradeoff (accepted): unlike a whole-directory rename this performs one rename
    per entry, so a hard process kill mid-loop can leave a partially-swapped
    bundle. Each individual rename is atomic and handled failures roll back; the
    residual hard-kill leftovers live only in the private backup dir and are
    reclaimed by :func:`_sweep_scratch` on the next run. Never destroying user
    data is worth this reduced atomicity.
    """
    backup_dir = install_dir + _BACKUP_DIR_SUFFIX
    entries = sorted(os.listdir(staging_dir))
    logger.debug(
        "REPLACE begin: install_dir=%s staging_dir=%s backup_dir=%s entries=%s",
        _abspath(install_dir),
        _abspath(staging_dir),
        _abspath(backup_dir),
        entries,
    )
    _log_listdir("install_dir before replace", install_dir)
    _log_listdir("staging_dir before replace", staging_dir)

    # Validate the staged bundle before touching anything in the live install.
    if executable_name is not None and executable_name not in entries:
        raise SelfUpdateError(
            f"the staged bundle is missing {executable_name} before replace"
        )
    # Start from a clean backup area so a stale one cannot shadow a rollback.
    if os.path.exists(backup_dir):
        _log_rmtree(backup_dir)
    _log_makedirs(backup_dir, mode=0o700, exist_ok=True)

    # (target_path, backup_path_or_None) for each entry we have moved, newest
    # last, so rollback can undo them in reverse order.
    moved = []
    try:
        for name in entries:
            target = os.path.join(install_dir, name)
            incoming = os.path.join(staging_dir, name)
            backup = os.path.join(backup_dir, name)
            if os.path.exists(target) or os.path.islink(target):
                _log_rename(target, backup)
                moved.append((target, backup))
            else:
                moved.append((target, None))
            _log_rename(incoming, target)
        # Defensive re-check: the staged bundle was validated above.
        if executable_name is not None and not os.path.isfile(
            os.path.join(install_dir, executable_name)
        ):
            raise SelfUpdateError(
                f"the installed bundle is missing {executable_name} after replace"
            )
    except (OSError, SelfUpdateError) as exc:
        _rollback_entries(moved, backup_dir, exc)
        raise

    _log_listdir("install_dir after replace", install_dir)
    logger.debug("REPLACE done: %s now holds the new bundle", _abspath(install_dir))
    return backup_dir


def _rollback_entries(moved, backup_dir, original_exc):
    """Undo a partial entry-scoped replacement, restoring the original install.

    ``moved`` is the list of ``(target, backup)`` pairs applied so far. Each is
    undone in reverse: the newly-installed entry is removed and, if the original
    had been backed up, it is moved back. A backup that cannot be restored is
    reported via :class:`SelfUpdateError` naming its location so the user can
    recover it by hand; anything not present is skipped.
    """
    logger.debug("ROLLBACK after failure: %s", original_exc)
    unrestored = []
    for target, backup in reversed(moved):
        # Remove the entry we moved into place (may be a file, dir, or symlink).
        if os.path.islink(target) or os.path.isfile(target):
            try:
                _log_unlink(target)
            except OSError:
                logger.debug("ROLLBACK could not remove %s", _abspath(target))
        elif os.path.isdir(target):
            _log_rmtree(target, ignore_errors=True)
        # Restore the original from backup, if there was one.
        if backup is not None and (os.path.exists(backup) or os.path.islink(backup)):
            try:
                _log_rename(backup, target)
            except OSError:
                logger.debug(
                    "ROLLBACK could not restore %s from %s",
                    _abspath(target),
                    _abspath(backup),
                )
                unrestored.append((target, backup))
    if unrestored:
        details = "; ".join(
            f"{_abspath(target)} (backup at {_abspath(backup)})"
            for target, backup in unrestored
        )
        raise SelfUpdateError(
            f"update failed ({original_exc}) and parts of the previous install "
            f"could not be restored: {details} - move each backup back to its "
            "target to recover"
        ) from original_exc


def _sweep_scratch(install_dir):
    """Remove leftover scratch dirs from a previous run.

    Run at the *start* of an update so a previous run's leftovers (extraction
    scratch, staging, and the private backup area) do not accumulate. All of
    these hold only files the CLI created or moved itself — never user files —
    so removing them is always safe. Best-effort: a directory that cannot be
    removed (e.g. still locked) is logged and skipped rather than aborting.
    """
    for suffix in _SCRATCH_SUFFIXES:
        scratch = install_dir + suffix
        if os.path.exists(scratch):
            _log_rmtree(scratch, ignore_errors=True)


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
    """Download, verify, and install the bundle from a manifest.

    Replacement is *entry-scoped*: only the top-level names shipped by the new
    bundle are replaced inside the install directory, which is itself never
    renamed or removed. Files the user keeps alongside the CLI are never
    touched, and a shell whose working directory is the install directory keeps
    working (its inode does not change). See :func:`replace_bundle_entries` for
    the atomicity tradeoff this implies.
    """
    missing = [key for key in ("url", "sha256") if not manifest.get(key)]
    if missing:
        raise SelfUpdateError(
            f"the release manifest is missing fields: {', '.join(missing)}"
        )
    executable_path = executable_path or sys.executable
    install_dir = os.path.dirname(os.path.realpath(executable_path))
    logger.debug(
        "SELF-UPDATE begin: executable_path=%s (realpath=%s) install_dir=%s cwd=%s",
        _abspath(executable_path),
        os.path.realpath(executable_path),
        _abspath(install_dir),
        _abspath(os.getcwd()),
    )
    _check_replaceable(install_dir)
    # Reclaim any scratch (extraction/staging/backup) left by a previous run
    # before staging the new bundle. These never contain user files.
    _sweep_scratch(install_dir)

    parent = os.path.dirname(install_dir)
    executable_name = os.path.basename(executable_path)
    # Extraction scratch dir and the final staging dir are kept separate so the
    # replacement source is never nested inside a directory we later clean up.
    extract_dir = install_dir + _EXTRACT_DIR_SUFFIX
    staging_dir = install_dir + _STAGING_DIR_SUFFIX
    logger.debug(
        "SELF-UPDATE paths: parent=%s executable_name=%s extract_dir=%s staging_dir=%s",
        _abspath(parent),
        executable_name,
        _abspath(extract_dir),
        _abspath(staging_dir),
    )
    suffix = ".zip" if manifest["url"].endswith(".zip") else ".tar.gz"
    archive_fd, archive_path = tempfile.mkstemp(dir=parent, suffix=suffix)
    os.close(archive_fd)
    logger.debug("TEMP archive created at %s", _abspath(archive_path))
    backup_dir = None
    try:
        download_archive(manifest["url"], archive_path, session=session)
        verify_sha256(archive_path, manifest["sha256"])
        extract_archive(archive_path, extract_dir)
        bundle_root = find_bundle_root(extract_dir, executable_name)
        # Promote the real bundle root out of the extraction scratch dir into a
        # standalone staging dir, so replacing from it cannot be undone by
        # cleaning up the extraction dir afterwards.
        _log_rename(bundle_root, staging_dir)
        if not os.path.isfile(os.path.join(staging_dir, executable_name)):
            raise SelfUpdateError(
                f"the downloaded bundle has no {executable_name} executable"
            )
        backup_dir = replace_bundle_entries(
            install_dir, staging_dir, executable_name=executable_name
        )
    finally:
        if os.path.exists(archive_path):
            _log_unlink(archive_path)
        if os.path.exists(extract_dir):
            _log_rmtree(extract_dir, ignore_errors=True)
        # staging_dir holds any bundle entries not consumed by the replacement
        # (e.g. after a failure); it only ever contains bundle files, so it is
        # safe to remove so a retry starts clean.
        if os.path.exists(staging_dir):
            _log_rmtree(staging_dir, ignore_errors=True)
    # The backup dir holds only the previous bundle's entries (never user
    # files), so it is safe to remove on success.
    if backup_dir is not None and os.path.exists(backup_dir):
        _log_rmtree(backup_dir, ignore_errors=True)
    logger.debug("SELF-UPDATE done: install_dir=%s", _abspath(install_dir))
    _log_listdir("install_dir final", install_dir)
    _log_listdir("install_dir final", install_dir)
