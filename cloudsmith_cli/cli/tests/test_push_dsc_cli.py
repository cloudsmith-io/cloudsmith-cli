"""Registered-command tests for ``cloudsmith push deb --dsc-file``."""

from pathlib import Path
from unittest.mock import patch

import pytest

from .. import config as cli_config
from ..commands.main import main

HERMETIC_ARGS = ["--api-key", "fake-api-key"]

_MOCK_TARGETS = (
    "cloudsmith_cli.cli.commands.push.validate_create_package",
    "cloudsmith_cli.cli.commands.push.validate_upload_file",
    "cloudsmith_cli.cli.commands.push.upload_file",
    "cloudsmith_cli.cli.commands.push.create_package",
    "cloudsmith_cli.cli.commands.push.wait_for_package_sync",
)


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch):
    """Keep developer environment and config values out of command tests."""
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delenv("CLOUDSMITH_CONFIG_FILE", raising=False)
    monkeypatch.delattr(cli_config.OPTIONS, "value", raising=False)
    monkeypatch.setattr(cli_config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(cli_config.ConfigReader, "config_searchpath", ["."])


def _touch(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"dummy content")
    return path


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
    clearsigned=False,
):
    control = (
        f"Format: {source_format}\nSource: {source}\nVersion: {version}\n"
        + _file_field("Files", filenames)
        + _file_field("Checksums-Sha256", filenames)
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
    dsc_path = tmp_path / f"{source}_{version}.dsc"
    dsc_path.write_text(control)
    return dsc_path


def _upload_identifier(*, filepath, **_kwargs):
    return f"uploaded:{Path(filepath).name}"


def _invoke(runner, tmp_path, extra_args, mocks, package_file=None):
    if package_file is None:
        package_file = _touch(tmp_path, "pkg_1.0-1_amd64.deb")
    with (
        patch(_MOCK_TARGETS[0]) as mock_validate_create_package,
        patch(_MOCK_TARGETS[1], return_value="checksum") as mock_validate_upload,
        patch(_MOCK_TARGETS[2], side_effect=_upload_identifier) as mock_upload,
        patch(
            _MOCK_TARGETS[3], return_value=("slug-perm", "slug")
        ) as mock_create_package,
        patch(_MOCK_TARGETS[4]),
    ):
        mocks.update(
            validate_create_package=mock_validate_create_package,
            validate_upload_file=mock_validate_upload,
            upload_file=mock_upload,
            create_package=mock_create_package,
        )
        result = runner.invoke(
            main,
            [
                "push",
                "deb",
                "example/repo/ubuntu/xenial",
                str(package_file),
                *extra_args,
                *HERMETIC_ARGS,
            ],
            catch_exceptions=False,
        )
    return result


@pytest.mark.parametrize(
    ("source_format", "version", "source_name", "changes_name"),
    [
        ("3.0 (native)", "1.0", "pkg_1.0.tar.xz", None),
        (
            "3.0 (quilt)",
            "1.0-1",
            "pkg_1.0.orig.tar.gz",
            "pkg_1.0-1.debian.tar.xz",
        ),
        ("1.0", "1.0-1", "pkg_1.0.orig.tar.gz", "pkg_1.0-1.diff.gz"),
    ],
)
def test_dsc_maps_real_source_package_members_to_uploaded_sdk_fields(
    runner, tmp_path, source_format, version, source_name, changes_name
):
    source_archive = _touch(tmp_path, source_name)
    filenames = [source_archive.name]
    if changes_name:
        filenames.append(_touch(tmp_path, changes_name).name)
    dsc_path = _write_dsc(
        tmp_path, filenames, version=version, source_format=source_format
    )

    mocks = {}
    result = _invoke(runner, tmp_path, ["--dsc-file", str(dsc_path)], mocks)

    assert result.exit_code == 0, result.output
    validation_kwargs = mocks["validate_create_package"].call_args.kwargs
    assert validation_kwargs["sources_file"] == str(source_archive)
    assert validation_kwargs["changes_file"] == (
        str(tmp_path / changes_name) if changes_name else None
    )
    create_kwargs = mocks["create_package"].call_args.kwargs
    assert create_kwargs["sources_file"] == f"uploaded:{source_name}"
    assert create_kwargs["changes_file"] == (
        f"uploaded:{changes_name}" if changes_name else None
    )


def test_dsc_as_package_file_is_parsed_without_the_option(runner, tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    debian_archive = _touch(tmp_path, "pkg_1.0-1.debian.tar.xz")
    dsc_path = _write_dsc(
        tmp_path,
        [source_archive.name, debian_archive.name],
        version="1.0-1",
        source_format="3.0 (quilt)",
    )

    mocks = {}
    result = _invoke(runner, tmp_path, [], mocks, package_file=dsc_path)

    assert result.exit_code == 0, result.output
    kwargs = mocks["validate_create_package"].call_args.kwargs
    assert kwargs["sources_file"] == str(source_archive)
    assert kwargs["changes_file"] == str(debian_archive)


def test_explicit_sources_file_stops_the_package_file_being_parsed(runner, tmp_path):
    # The .dsc references a member that is absent, so parsing it at all would
    # abort the push; --sources-file means the caller drives the members.
    explicit_source = _touch(tmp_path, "explicit.tar.gz")
    dsc_path = _write_dsc(tmp_path, ["absent_1.0.tar.gz"])

    mocks = {}
    result = _invoke(
        runner,
        tmp_path,
        ["--sources-file", str(explicit_source)],
        mocks,
        package_file=dsc_path,
    )

    assert result.exit_code == 0, result.output
    kwargs = mocks["validate_create_package"].call_args.kwargs
    assert kwargs["sources_file"] == str(explicit_source)
    assert kwargs["changes_file"] is None


def test_binary_package_file_is_never_parsed_as_a_dsc(runner, tmp_path):
    mocks = {}
    result = _invoke(runner, tmp_path, [], mocks)

    assert result.exit_code == 0, result.output
    kwargs = mocks["validate_create_package"].call_args.kwargs
    assert kwargs["sources_file"] is None
    assert kwargs["changes_file"] is None


def test_clearsigned_dsc_is_parsed_through_registered_command(runner, tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    debian_archive = _touch(tmp_path, "pkg_1.0-1.debian.tar.xz")
    dsc_path = _write_dsc(
        tmp_path,
        [source_archive.name, debian_archive.name],
        version="1.0-1",
        source_format="3.0 (quilt)",
        clearsigned=True,
    )

    mocks = {}
    result = _invoke(runner, tmp_path, ["--dsc-file", str(dsc_path)], mocks)

    assert result.exit_code == 0, result.output
    kwargs = mocks["validate_create_package"].call_args.kwargs
    assert kwargs["sources_file"] == str(source_archive)
    assert kwargs["changes_file"] == str(debian_archive)


def test_explicit_sources_file_wins_per_field(runner, tmp_path):
    dsc_source = _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    debian_archive = _touch(tmp_path, "pkg_1.0-1.debian.tar.xz")
    explicit_source = _touch(tmp_path, "explicit.tar.gz")
    dsc_path = _write_dsc(
        tmp_path,
        [dsc_source.name, debian_archive.name],
        version="1.0-1",
        source_format="3.0 (quilt)",
    )

    mocks = {}
    result = _invoke(
        runner,
        tmp_path,
        [
            "--dsc-file",
            str(dsc_path),
            "--sources-file",
            str(explicit_source),
        ],
        mocks,
    )

    assert result.exit_code == 0, result.output
    kwargs = mocks["validate_create_package"].call_args.kwargs
    assert kwargs["sources_file"] == str(explicit_source)
    assert kwargs["changes_file"] == str(debian_archive)


def test_explicit_changes_file_wins_per_field(runner, tmp_path):
    source_archive = _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    dsc_changes = _touch(tmp_path, "pkg_1.0-1.debian.tar.xz")
    explicit_changes = _touch(tmp_path, "explicit.diff.gz")
    dsc_path = _write_dsc(
        tmp_path,
        [source_archive.name, dsc_changes.name],
        version="1.0-1",
        source_format="3.0 (quilt)",
    )

    mocks = {}
    result = _invoke(
        runner,
        tmp_path,
        [
            "--dsc-file",
            str(dsc_path),
            "--changes-file",
            str(explicit_changes),
        ],
        mocks,
    )

    assert result.exit_code == 0, result.output
    kwargs = mocks["validate_create_package"].call_args.kwargs
    assert kwargs["sources_file"] == str(source_archive)
    assert kwargs["changes_file"] == str(explicit_changes)


@pytest.mark.parametrize("member", ["/etc/passwd", "../pkg_1.0.tar.gz"])
def test_member_path_is_rejected_before_network_calls(runner, tmp_path, member):
    dsc_path = _write_dsc(tmp_path, [member])

    mocks = {}
    result = _invoke(runner, tmp_path, ["--dsc-file", str(dsc_path)], mocks)

    assert result.exit_code != 0
    assert "must be filenames next to the .dsc" in result.output
    mocks["validate_create_package"].assert_not_called()
    mocks["validate_upload_file"].assert_not_called()


def test_symlinked_member_uploads_its_canonical_target(runner, tmp_path):
    dsc_dir = tmp_path / "dsc"
    dsc_dir.mkdir()
    outside_archive = _touch(tmp_path, "outside.tar.gz")
    (dsc_dir / "pkg_1.0.tar.gz").symlink_to(outside_archive)
    dsc_path = _write_dsc(dsc_dir, ["pkg_1.0.tar.gz"])

    mocks = {}
    result = _invoke(runner, tmp_path, ["--dsc-file", str(dsc_path)], mocks)

    assert result.exit_code == 0, result.output
    _, kwargs = mocks["create_package"].call_args
    assert kwargs["sources_file"] == "uploaded:outside.tar.gz"


def test_member_symlinked_to_a_directory_is_rejected_before_network_calls(
    runner, tmp_path
):
    dsc_dir = tmp_path / "dsc"
    dsc_dir.mkdir()
    (dsc_dir / "pkg_1.0.tar.gz").symlink_to(tmp_path, target_is_directory=True)
    dsc_path = _write_dsc(dsc_dir, ["pkg_1.0.tar.gz"])

    mocks = {}
    result = _invoke(runner, tmp_path, ["--dsc-file", str(dsc_path)], mocks)

    assert result.exit_code != 0
    assert "not a regular file next to the .dsc" in result.output
    mocks["validate_create_package"].assert_not_called()
    mocks["validate_upload_file"].assert_not_called()


def test_multi_component_is_rejected_before_network_calls(runner, tmp_path):
    filenames = [
        _touch(tmp_path, "pkg_1.0.orig.tar.gz").name,
        _touch(tmp_path, "pkg_1.0.orig-libbar.tar.gz").name,
        _touch(tmp_path, "pkg_1.0-1.debian.tar.xz").name,
    ]
    dsc_path = _write_dsc(
        tmp_path, filenames, version="1.0-1", source_format="3.0 (quilt)"
    )

    mocks = {}
    result = _invoke(runner, tmp_path, ["--dsc-file", str(dsc_path)], mocks)

    assert result.exit_code != 0
    assert "multi-component" in result.output
    mocks["validate_create_package"].assert_not_called()


def test_detached_signature_is_skipped_with_a_warning(runner, tmp_path):
    filenames = [
        _touch(tmp_path, "pkg_1.0.orig.tar.gz").name,
        _touch(tmp_path, "pkg_1.0.orig.tar.gz.asc").name,
        _touch(tmp_path, "pkg_1.0-1.debian.tar.xz").name,
    ]
    dsc_path = _write_dsc(
        tmp_path, filenames, version="1.0-1", source_format="3.0 (quilt)"
    )

    mocks = {}
    result = _invoke(runner, tmp_path, ["--dsc-file", str(dsc_path)], mocks)

    assert result.exit_code == 0, result.output
    assert "Not uploading pkg_1.0.orig.tar.gz.asc" in result.output
    _, kwargs = mocks["create_package"].call_args
    assert kwargs["sources_file"] == "uploaded:pkg_1.0.orig.tar.gz"
    assert kwargs["changes_file"] == "uploaded:pkg_1.0-1.debian.tar.xz"


def test_push_deb_help_documents_dsc_file_option(runner):
    result = runner.invoke(main, ["push", "deb", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "--dsc-file" in result.output
    assert ".debian.tar.*" in result.output


def test_push_non_deb_format_has_no_dsc_file_option(runner):
    result = runner.invoke(main, ["push", "raw", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "--dsc-file" not in result.output
