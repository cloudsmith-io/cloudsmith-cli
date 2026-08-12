"""Tests for ``cloudsmith_cli.cli.dsc_parser`` (GitHub issue #56)."""

import click
import pytest

from ..dsc_parser import resolve_dsc_files


def _write_dsc(tmp_path, file_lines, field="Files", name="pkg_1.0-1.dsc"):
    """Write a minimal .dsc control file listing ``file_lines`` under ``field``."""
    body_lines = "\n".join(f" deadbeef 100 {line}" for line in file_lines)
    dsc_path = tmp_path / name
    dsc_path.write_text(
        f"Format: 3.0 (native)\nSource: pkg\nVersion: 1.0-1\n{field}:\n{body_lines}\n"
    )
    return dsc_path


def _touch(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"dummy content")
    return path


def test_resolve_dsc_files_happy_path_with_changes(tmp_path):
    _touch(tmp_path, "pkg_1.0.tar.gz")
    _touch(tmp_path, "pkg_1.0-1_amd64.changes")
    dsc_path = _write_dsc(tmp_path, ["pkg_1.0.tar.gz", "pkg_1.0-1_amd64.changes"])

    sources_file, changes_file = resolve_dsc_files(str(dsc_path))

    assert sources_file == str(tmp_path / "pkg_1.0.tar.gz")
    assert changes_file == str(tmp_path / "pkg_1.0-1_amd64.changes")


def test_resolve_dsc_files_happy_path_without_changes(tmp_path):
    _touch(tmp_path, "pkg_1.0.tar.gz")
    dsc_path = _write_dsc(tmp_path, ["pkg_1.0.tar.gz"])

    sources_file, changes_file = resolve_dsc_files(str(dsc_path))

    assert sources_file == str(tmp_path / "pkg_1.0.tar.gz")
    assert changes_file is None


def test_resolve_dsc_files_uses_checksums_sha256_fallback(tmp_path):
    _touch(tmp_path, "pkg_1.0.tar.gz")
    dsc_path = _write_dsc(tmp_path, ["pkg_1.0.tar.gz"], field="Checksums-Sha256")

    sources_file, _ = resolve_dsc_files(str(dsc_path))

    assert sources_file == str(tmp_path / "pkg_1.0.tar.gz")


def test_resolve_dsc_files_missing_referenced_file_errors(tmp_path):
    # pkg_1.0.tar.gz is referenced but never actually written to disk.
    dsc_path = _write_dsc(tmp_path, ["pkg_1.0.tar.gz"])

    with pytest.raises(click.UsageError, match="not found next to the .dsc"):
        resolve_dsc_files(str(dsc_path))


def test_resolve_dsc_files_rejects_multi_component(tmp_path):
    _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    _touch(tmp_path, "pkg_1.0.orig-libbar.tar.gz")
    dsc_path = _write_dsc(
        tmp_path, ["pkg_1.0.orig.tar.gz", "pkg_1.0.orig-libbar.tar.gz"]
    )

    with pytest.raises(click.UsageError, match="multi-component"):
        resolve_dsc_files(str(dsc_path))


def test_resolve_dsc_files_rejects_detached_signature(tmp_path):
    _touch(tmp_path, "pkg_1.0.tar.gz")
    _touch(tmp_path, "pkg_1.0.tar.gz.asc")
    dsc_path = _write_dsc(tmp_path, ["pkg_1.0.tar.gz", "pkg_1.0.tar.gz.asc"])

    with pytest.raises(click.UsageError, match="detached signature"):
        resolve_dsc_files(str(dsc_path))


def test_resolve_dsc_files_rejects_ambiguous_multiple_source_tarballs(tmp_path):
    _touch(tmp_path, "pkg_1.0.tar.gz")
    _touch(tmp_path, "pkg_1.0-1.debian.tar.xz")
    dsc_path = _write_dsc(tmp_path, ["pkg_1.0.tar.gz", "pkg_1.0-1.debian.tar.xz"])

    with pytest.raises(click.UsageError, match="more than one source tarball"):
        resolve_dsc_files(str(dsc_path))


def test_resolve_dsc_files_rejects_multiple_changes_files(tmp_path):
    _touch(tmp_path, "pkg_1.0.tar.gz")
    _touch(tmp_path, "pkg_1.0-1_amd64.changes")
    _touch(tmp_path, "pkg_1.0-1_source.changes")
    dsc_path = _write_dsc(
        tmp_path,
        [
            "pkg_1.0.tar.gz",
            "pkg_1.0-1_amd64.changes",
            "pkg_1.0-1_source.changes",
        ],
    )

    with pytest.raises(click.UsageError, match="more than one .changes file"):
        resolve_dsc_files(str(dsc_path))


def test_resolve_dsc_files_no_files_stanza_errors(tmp_path):
    dsc_path = tmp_path / "empty.dsc"
    dsc_path.write_text("Format: 3.0 (native)\nSource: pkg\nVersion: 1.0-1\n")

    with pytest.raises(click.UsageError, match="Files"):
        resolve_dsc_files(str(dsc_path))


def test_resolve_dsc_files_no_source_tarball_errors(tmp_path):
    _touch(tmp_path, "pkg_1.0-1_amd64.changes")
    dsc_path = _write_dsc(tmp_path, ["pkg_1.0-1_amd64.changes"])

    with pytest.raises(click.UsageError, match="does not reference a source tarball"):
        resolve_dsc_files(str(dsc_path))
