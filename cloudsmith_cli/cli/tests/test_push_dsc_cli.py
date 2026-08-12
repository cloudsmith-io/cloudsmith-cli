"""CLI-level tests for `cloudsmith push deb --dsc-file` (GitHub issue #56).

Complements ``test_dsc_parser.py`` (pure ``.dsc`` parsing/resolution) with
integration coverage of the ``deb`` push handler: the flag itself, the
--sources-file/--changes-file precedence rule, and that a rejected .dsc
aborts before any network call.
"""

from unittest.mock import patch

import pytest

from .. import config as cli_config
from ..commands.push import push

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
    """Keep a developer's real env/config out of these tests (see test_domains.py)."""
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delenv("CLOUDSMITH_CONFIG_FILE", raising=False)
    monkeypatch.delattr(cli_config.OPTIONS, "value", raising=False)
    monkeypatch.setattr(cli_config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(cli_config.ConfigReader, "config_searchpath", ["."])


def _touch(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"dummy content")
    return path


def _write_dsc(tmp_path, file_lines, field="Files", name="pkg_1.0-1.dsc"):
    body = "\n".join(f" deadbeef 100 {line}" for line in file_lines)
    dsc_path = tmp_path / name
    dsc_path.write_text(
        f"Format: 3.0 (native)\nSource: pkg\nVersion: 1.0-1\n{field}:\n{body}\n"
    )
    return dsc_path


def _invoke(runner, tmp_path, extra_args, mocks):
    package_file = _touch(tmp_path, "pkg_1.0-1_amd64.deb")
    with (
        patch(_MOCK_TARGETS[0]) as mock_validate_create_package,
        patch(_MOCK_TARGETS[1], return_value="checksum"),
        patch(_MOCK_TARGETS[2], return_value="file-id"),
        patch(_MOCK_TARGETS[3], return_value=("slug-perm", "slug")),
        patch(_MOCK_TARGETS[4]),
    ):
        mocks["validate_create_package"] = mock_validate_create_package
        result = runner.invoke(
            push,
            [
                "deb",
                "acme/repo/ubuntu/xenial",
                str(package_file),
                *extra_args,
                *HERMETIC_ARGS,
            ],
            catch_exceptions=False,
        )
    return result


def test_dsc_file_derives_sources_and_changes_files(runner, tmp_path):
    sources_tarball = _touch(tmp_path, "pkg_1.0.tar.gz")
    changes_file = _touch(tmp_path, "pkg_1.0-1_amd64.changes")
    dsc_path = _write_dsc(tmp_path, [sources_tarball.name, changes_file.name])

    mocks = {}
    result = _invoke(runner, tmp_path, ["--dsc-file", str(dsc_path)], mocks)

    assert result.exit_code == 0, result.output
    kwargs = mocks["validate_create_package"].call_args.kwargs
    assert kwargs["sources_file"] == str(sources_tarball)
    assert kwargs["changes_file"] == str(changes_file)


def test_explicit_sources_file_wins_over_dsc_file(runner, tmp_path):
    """Explicit --sources-file always takes precedence over --dsc-file."""
    dsc_sources_tarball = _touch(tmp_path, "pkg_1.0.tar.gz")
    changes_file = _touch(tmp_path, "pkg_1.0-1_amd64.changes")
    explicit_sources_file = _touch(tmp_path, "explicit_sources.tar.gz")
    dsc_path = _write_dsc(tmp_path, [dsc_sources_tarball.name, changes_file.name])

    mocks = {}
    result = _invoke(
        runner,
        tmp_path,
        [
            "--dsc-file",
            str(dsc_path),
            "--sources-file",
            str(explicit_sources_file),
        ],
        mocks,
    )

    assert result.exit_code == 0, result.output
    kwargs = mocks["validate_create_package"].call_args.kwargs
    # Explicit flag wins...
    assert kwargs["sources_file"] == str(explicit_sources_file)
    # ...but changes_file, which was not passed explicitly, is still derived.
    assert kwargs["changes_file"] == str(changes_file)


def test_explicit_changes_file_wins_over_dsc_file(runner, tmp_path):
    """Explicit --changes-file always takes precedence over --dsc-file."""
    sources_tarball = _touch(tmp_path, "pkg_1.0.tar.gz")
    dsc_changes_file = _touch(tmp_path, "pkg_1.0-1_amd64.changes")
    explicit_changes_file = _touch(tmp_path, "explicit.changes")
    dsc_path = _write_dsc(tmp_path, [sources_tarball.name, dsc_changes_file.name])

    mocks = {}
    result = _invoke(
        runner,
        tmp_path,
        [
            "--dsc-file",
            str(dsc_path),
            "--changes-file",
            str(explicit_changes_file),
        ],
        mocks,
    )

    assert result.exit_code == 0, result.output
    kwargs = mocks["validate_create_package"].call_args.kwargs
    assert kwargs["sources_file"] == str(sources_tarball)
    assert kwargs["changes_file"] == str(explicit_changes_file)


def test_dsc_file_rejects_multi_component_before_any_network_call(runner, tmp_path):
    orig_tarball = _touch(tmp_path, "pkg_1.0.orig.tar.gz")
    component_tarball = _touch(tmp_path, "pkg_1.0.orig-libbar.tar.gz")
    dsc_path = _write_dsc(tmp_path, [orig_tarball.name, component_tarball.name])

    mocks = {}
    result = _invoke(runner, tmp_path, ["--dsc-file", str(dsc_path)], mocks)

    assert result.exit_code != 0
    assert "multi-component" in result.output
    mocks["validate_create_package"].assert_not_called()


def test_dsc_file_rejects_detached_signature_before_any_network_call(runner, tmp_path):
    sources_tarball = _touch(tmp_path, "pkg_1.0.tar.gz")
    signature_file = _touch(tmp_path, "pkg_1.0.tar.gz.asc")
    dsc_path = _write_dsc(tmp_path, [sources_tarball.name, signature_file.name])

    mocks = {}
    result = _invoke(runner, tmp_path, ["--dsc-file", str(dsc_path)], mocks)

    assert result.exit_code != 0
    assert "detached signature" in result.output
    mocks["validate_create_package"].assert_not_called()


def test_push_deb_help_documents_dsc_file_option(runner):
    result = runner.invoke(push, ["deb", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "--dsc-file" in result.output


def test_push_non_deb_format_has_no_dsc_file_option(runner):
    result = runner.invoke(push, ["raw", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "--dsc-file" not in result.output
