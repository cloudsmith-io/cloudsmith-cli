"""Registered-command tests for ``cloudsmith push skills``."""

import os
import zipfile
from unittest.mock import patch

import pytest

from .. import config as cli_config
from ..commands.main import main

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


def test_changelog_is_sent_to_the_api(runner, tmp_path):
    package_file = tmp_path / "my-skill.zip"
    package_file.write_bytes(b"dummy content")

    with (
        patch(_MOCK_TARGETS[0]) as mock_validate_create_package,
        patch(_MOCK_TARGETS[1], return_value="checksum"),
        patch(_MOCK_TARGETS[2], return_value="uploaded:my-skill.zip"),
        patch(
            _MOCK_TARGETS[3], return_value=("slug-perm", "slug")
        ) as mock_create_package,
        patch(_MOCK_TARGETS[4]),
    ):
        result = runner.invoke(
            main,
            [
                "push",
                "skills",
                "example/repo",
                str(package_file),
                "--name",
                "my-skill",
                "--version",
                "1.0.0",
                "--changelog",
                "Fixed a bug",
                "--api-key",
                "fake-api-key",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output

    # Validation runs before file upload -> check kwargs passed through
    validation_kwargs = mock_validate_create_package.call_args.kwargs
    assert validation_kwargs["changelog"] == "Fixed a bug"

    # The create call persists the package -> check kwargs gets sent to package creation
    create_kwargs = mock_create_package.call_args.kwargs
    assert create_kwargs["changelog"] == "Fixed a bug"


def test_push_skills_help_documents_changelog_option(runner):
    result = runner.invoke(main, ["push", "skills", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "--changelog" in result.output


def test_push_non_skills_format_has_no_changelog_option(runner):
    result = runner.invoke(main, ["push", "raw", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "--changelog" not in result.output


def test_directory_is_compressed_and_uploaded_with_compress(runner, tmp_path):
    skill_dir = tmp_path / "my-skill"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\n")
    (skill_dir / "scripts" / "run.sh").write_text("echo hi\n")

    uploaded = {}

    # The archive lives in a temp dir that is removed after the push, so
    # inspect it while the upload is in flight.
    def capture_upload(*args, filepath, **kwargs):
        with zipfile.ZipFile(filepath) as archive:
            uploaded["filename"] = os.path.basename(filepath)
            uploaded["members"] = sorted(archive.namelist())
        return "uploaded:my-skill.zip"

    with (
        patch(_MOCK_TARGETS[0]) as mock_validate_create_package,
        patch(_MOCK_TARGETS[1], return_value="checksum"),
        patch(_MOCK_TARGETS[2], side_effect=capture_upload),
        patch(
            _MOCK_TARGETS[3], return_value=("slug-perm", "slug")
        ) as mock_create_package,
        patch(_MOCK_TARGETS[4]),
    ):
        result = runner.invoke(
            main,
            [
                "push",
                "skills",
                "example/repo",
                str(skill_dir),
                "--name",
                "my-skill",
                "--version",
                "1.0.0",
                "--compress",
                "--api-key",
                "fake-api-key",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    assert uploaded["filename"] == "my-skill.zip"
    # Members are relative to the skill directory, not the absolute path
    assert "SKILL.md" in uploaded["members"]
    assert "scripts/run.sh" in uploaded["members"]

    # The flag is client-side only and must not leak into the API payload
    assert "compress" not in mock_validate_create_package.call_args.kwargs
    assert "compress" not in mock_create_package.call_args.kwargs


def test_directory_compression_excludes_os_and_vcs_clutter(runner, tmp_path):
    skill_dir = tmp_path / "my-skill"
    for path, content in {
        "SKILL.md": "---\nname: my-skill\n---\n",
        ".claude-plugin/plugin.json": "{}",
        "scripts/pkg/__init__.py": "",
        "references/.DS_Store": "",
        "._SKILL.md": "",
        "__MACOSX/._SKILL.md": "",
        ".git/HEAD": "ref: refs/heads/main\n",
        ".env": "SECRET=1\n",
    }.items():
        (skill_dir / path).parent.mkdir(parents=True, exist_ok=True)
        (skill_dir / path).write_text(content)

    uploaded = {}

    def capture_upload(*args, filepath, **kwargs):
        with zipfile.ZipFile(filepath) as archive:
            uploaded["members"] = sorted(
                name for name in archive.namelist() if not name.endswith("/")
            )
        return "uploaded:my-skill.zip"

    with (
        patch(_MOCK_TARGETS[0]),
        patch(_MOCK_TARGETS[1], return_value="checksum"),
        patch(_MOCK_TARGETS[2], side_effect=capture_upload),
        patch(_MOCK_TARGETS[3], return_value=("slug-perm", "slug")),
        patch(_MOCK_TARGETS[4]),
    ):
        result = runner.invoke(
            main,
            [
                "push",
                "skills",
                "example/repo",
                str(skill_dir),
                "--name",
                "my-skill",
                "--version",
                "1.0.0",
                "--compress",
                "--api-key",
                "fake-api-key",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    assert uploaded["members"] == [
        ".claude-plugin/plugin.json",
        "SKILL.md",
        "scripts/pkg/__init__.py",
    ]


def test_directory_without_compress_is_rejected(runner, tmp_path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\n")

    with (
        patch(_MOCK_TARGETS[0]),
        patch(_MOCK_TARGETS[1]),
        patch(_MOCK_TARGETS[2]) as mock_upload_file,
        patch(_MOCK_TARGETS[3]) as mock_create_package,
        patch(_MOCK_TARGETS[4]),
    ):
        result = runner.invoke(
            main,
            [
                "push",
                "skills",
                "example/repo",
                str(skill_dir),
                "--name",
                "my-skill",
                "--version",
                "1.0.0",
                "--api-key",
                "fake-api-key",
            ],
        )

    assert result.exit_code == 2, result.output
    assert "Directories require --compress" in result.output
    assert not mock_upload_file.called
    assert not mock_create_package.called


def test_file_with_compress_is_uploaded_unchanged(runner, tmp_path):
    package_file = tmp_path / "my-skill.zip"
    package_file.write_bytes(b"dummy content")

    with (
        patch(_MOCK_TARGETS[0]),
        patch(_MOCK_TARGETS[1], return_value="checksum"),
        patch(
            _MOCK_TARGETS[2], return_value="uploaded:my-skill.zip"
        ) as mock_upload_file,
        patch(_MOCK_TARGETS[3], return_value=("slug-perm", "slug")),
        patch(_MOCK_TARGETS[4]),
    ):
        result = runner.invoke(
            main,
            [
                "push",
                "skills",
                "example/repo",
                str(package_file),
                "--name",
                "my-skill",
                "--version",
                "1.0.0",
                "--compress",
                "--api-key",
                "fake-api-key",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    assert mock_upload_file.call_args.kwargs["filepath"] == str(package_file)


def test_push_skills_help_documents_compress_option(runner):
    result = runner.invoke(main, ["push", "skills", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "--compress" in result.output


def test_push_non_skills_format_rejects_directory(runner, tmp_path):
    package_dir = tmp_path / "not-a-file"
    package_dir.mkdir()

    result = runner.invoke(
        main,
        [
            "push",
            "raw",
            "example/repo",
            str(package_dir),
            "--api-key",
            "fake-api-key",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "is a directory" in result.output
    assert "--compress" not in result.output
