"""Tests for Debian ``.dsc`` parsing and member resolution."""

import os

import click
import pytest

from ..dsc_parser import ResolvedDscFiles, resolve_dsc_files


def _file_field(name, filenames):
    checksum = "a" * (64 if name == "Checksums-Sha256" else 32)
    entries = "\n".join(f" {checksum} 100 {filename}" for filename in filenames)
    return f"{name}:\n{entries}\n"


def _write_dsc(
    tmp_path,
    filenames,
    *,
    source="pkg",
    version="1.0",
    source_format="3.0 (native)",
    fields=("Files",),
    clearsigned=False,
    name=None,
):
    control = (
        f"Format: {source_format}\nSource: {source}\nVersion: {version}\n"
        + "".join(_file_field(field, filenames) for field in fields)
    )
    if clearsigned:
        control = (
            "-----BEGIN PGP SIGNED MESSAGE-----\n"
            "Hash: SHA256\n\n"
            f"{control}"
            "-----BEGIN PGP SIGNATURE-----\n"
            "test-signature-data\n"
            "-----END PGP SIGNATURE-----\n"
        )
    dsc_path = tmp_path / (name or f"{source}_{version}.dsc")
    dsc_path.write_text(control)
    return dsc_path


def _touch(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"dummy content")
    return path


def test_resolves_native_source_archive(tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.tar.xz")
    dsc_path = _write_dsc(tmp_path, [source_archive.name])

    assert resolve_dsc_files(str(dsc_path)) == ResolvedDscFiles(str(source_archive))


def test_resolves_quilt_source_and_debian_archives(tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    debian_archive = _touch(tmp_path, "pkg_1.0-1.debian.tar.xz")
    dsc_path = _write_dsc(
        tmp_path,
        [source_archive.name, debian_archive.name],
        version="1.0-1",
        source_format="3.0 (quilt)",
    )

    assert resolve_dsc_files(str(dsc_path)) == ResolvedDscFiles(
        str(source_archive), str(debian_archive)
    )


def test_resolves_legacy_non_native_source_and_diff_archives(tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    diff_archive = _touch(tmp_path, "pkg_1.0-1.diff.gz")
    dsc_path = _write_dsc(
        tmp_path,
        [source_archive.name, diff_archive.name],
        version="1.0-1",
        source_format="1.0",
    )

    assert resolve_dsc_files(str(dsc_path)) == ResolvedDscFiles(
        str(source_archive), str(diff_archive)
    )


def test_rejects_legacy_non_native_source_without_diff(tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    dsc_path = _write_dsc(
        tmp_path,
        [source_archive.name],
        version="1.0-1",
        source_format="1.0",
    )

    with pytest.raises(click.UsageError, match="exactly one Debian packaging diff"):
        resolve_dsc_files(str(dsc_path))


def test_resolves_clearsigned_dsc_using_matching_sha256_and_files(tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    debian_archive = _touch(tmp_path, "pkg_1.0-1.debian.tar.xz")
    dsc_path = _write_dsc(
        tmp_path,
        [source_archive.name, debian_archive.name],
        version="1.0-1",
        source_format="3.0 (quilt)",
        fields=("Files", "Checksums-Sha256"),
        clearsigned=True,
    )

    assert resolve_dsc_files(str(dsc_path)) == ResolvedDscFiles(
        str(source_archive), str(debian_archive)
    )


def test_uses_checksums_sha256_when_files_is_absent(tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.tar.gz")
    dsc_path = _write_dsc(tmp_path, [source_archive.name], fields=("Checksums-Sha256",))

    assert resolve_dsc_files(str(dsc_path)) == ResolvedDscFiles(str(source_archive))


def test_rejects_conflicting_checksum_file_lists(tmp_path):
    dsc_path = tmp_path / "pkg_1.0.dsc"
    dsc_path.write_text(
        "Format: 3.0 (native)\nSource: pkg\nVersion: 1.0\n"
        + _file_field("Files", ["pkg_1.0.tar.gz"])
        + _file_field("Checksums-Sha256", ["other_1.0.tar.gz"])
    )

    with pytest.raises(click.UsageError, match="conflicting filenames"):
        resolve_dsc_files(str(dsc_path))


def test_rejects_malformed_file_list_row(tmp_path):
    dsc_path = tmp_path / "pkg_1.0.dsc"
    dsc_path.write_text(
        "Format: 3.0 (native)\nSource: pkg\nVersion: 1.0\n"
        "Files:\n deadbeef pkg_1.0.tar.gz\n"
    )

    with pytest.raises(click.UsageError, match="malformed 'Files' entry"):
        resolve_dsc_files(str(dsc_path))


def test_rejects_missing_referenced_file(tmp_path):
    dsc_path = _write_dsc(tmp_path, ["pkg_1.0.tar.gz"])

    with pytest.raises(click.UsageError, match="not a regular file next to"):
        resolve_dsc_files(str(dsc_path))


def test_rejects_multi_component_source_package(tmp_path):
    _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    _touch(tmp_path, "pkg_1.0.orig-libbar.tar.gz")
    _touch(tmp_path, "pkg_1.0-1.debian.tar.xz")
    dsc_path = _write_dsc(
        tmp_path,
        [
            "pkg_1.0.orig.tar.gz",
            "pkg_1.0.orig-libbar.tar.gz",
            "pkg_1.0-1.debian.tar.xz",
        ],
        version="1.0-1",
        source_format="3.0 (quilt)",
    )

    with pytest.raises(click.UsageError, match="multi-component"):
        resolve_dsc_files(str(dsc_path))


def test_skips_detached_signature_without_failing(tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    _touch(tmp_path, "pkg_1.0.orig.tar.gz.asc")
    debian_archive = _touch(tmp_path, "pkg_1.0-1.debian.tar.xz")
    dsc_path = _write_dsc(
        tmp_path,
        [
            "pkg_1.0.orig.tar.gz",
            "pkg_1.0.orig.tar.gz.asc",
            "pkg_1.0-1.debian.tar.xz",
        ],
        version="1.0-1",
        source_format="3.0 (quilt)",
    )

    assert resolve_dsc_files(str(dsc_path)) == ResolvedDscFiles(
        str(source_archive),
        str(debian_archive),
        ignored_files=("pkg_1.0.orig.tar.gz.asc",),
    )


@pytest.mark.parametrize("source_format", ["3.0 (git)", "3.0 (bzr)", "3.0 (custom)"])
def test_rejects_source_formats_without_an_indexable_archive(source_format, tmp_path):
    _touch(tmp_path, "pkg_1.0.git")
    dsc_path = _write_dsc(tmp_path, ["pkg_1.0.git"], source_format=source_format)

    with pytest.raises(click.UsageError, match="unsupported Debian source format"):
        resolve_dsc_files(str(dsc_path))


@pytest.mark.parametrize("filename", ["/etc/passwd", "../pkg_1.0.tar.gz"])
def test_rejects_member_paths(filename, tmp_path):
    dsc_path = _write_dsc(tmp_path, [filename])

    with pytest.raises(click.UsageError, match="must be filenames next to the .dsc"):
        resolve_dsc_files(str(dsc_path))


def test_resolves_symlinked_member_to_its_canonical_target(tmp_path):
    # `mk-origtargz --symlink` (the uscan default) links the .orig tarball in
    # from a download cache, so a member pointing outside the .dsc directory
    # is a normal build tree, not an attempt to escape it.
    dsc_dir = tmp_path / "source-package"
    dsc_dir.mkdir()
    outside_archive = _touch(tmp_path, "outside.tar.gz")
    (dsc_dir / "pkg_1.0.tar.gz").symlink_to(outside_archive)
    dsc_path = _write_dsc(dsc_dir, ["pkg_1.0.tar.gz"])

    assert resolve_dsc_files(str(dsc_path)) == ResolvedDscFiles(str(outside_archive))


def test_rejects_member_symlinked_to_a_directory(tmp_path):
    dsc_dir = tmp_path / "source-package"
    dsc_dir.mkdir()
    (dsc_dir / "pkg_1.0.tar.gz").symlink_to(tmp_path, target_is_directory=True)
    dsc_path = _write_dsc(dsc_dir, ["pkg_1.0.tar.gz"])

    with pytest.raises(click.UsageError, match="not a regular file next to"):
        resolve_dsc_files(str(dsc_path))


@pytest.mark.parametrize(
    ("source", "version", "filename"),
    [
        ("foo.orig-bar", "1.0", "foo.orig-bar_1.0.tar.gz"),
        ("foo", "1.0.orig-bar", "foo_1.0.orig-bar.tar.gz"),
    ],
)
def test_native_name_or_version_containing_orig_marker_is_not_a_component(
    source, version, filename, tmp_path
):
    source_archive = _touch(tmp_path, filename)
    dsc_path = _write_dsc(
        tmp_path, [filename], source=source, version=version, name="package.dsc"
    )

    assert resolve_dsc_files(str(dsc_path)) == ResolvedDscFiles(str(source_archive))


def test_rejects_missing_file_listing(tmp_path):
    dsc_path = tmp_path / "empty.dsc"
    dsc_path.write_text("Format: 3.0 (native)\nSource: pkg\nVersion: 1.0\n")

    with pytest.raises(click.UsageError, match="Checksums-Sha256"):
        resolve_dsc_files(str(dsc_path))


def test_resolved_paths_are_canonical(tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.tar.gz")
    internal_link = tmp_path / "linked"
    internal_link.symlink_to(tmp_path, target_is_directory=True)
    dsc_path = _write_dsc(tmp_path, [source_archive.name])

    resolved = resolve_dsc_files(os.path.join(str(internal_link), dsc_path.name))

    assert resolved.sources_file == str(source_archive)
