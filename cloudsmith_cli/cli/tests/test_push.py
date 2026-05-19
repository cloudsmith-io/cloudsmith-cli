# pylint: disable=too-many-lines
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import click
import pytest

from ...core.api.exceptions import ApiException
from ..commands.push import (
    _print_metadata_retry_hint,
    attach_metadata_to_package,
    resolve_push_metadata_options,
    upload_files_and_create_package,
    validate_metadata_payload,
)
from ..metadata_common import ResolvedMetadata


# pylint: disable=too-many-instance-attributes,too-many-public-methods
class TestPush(unittest.TestCase):
    def setUp(self):
        self.mock_ctx = MagicMock()
        self.mock_opts = MagicMock()
        self.package_type = "test_format"
        self.owner = "test_owner"
        self.repo = "test_repo"
        self.name = "test_package"
        self.version = "1.0.0"
        self.dry_run = False
        self.no_wait_for_sync = False
        self.wait_interval = 5.0
        self.skip_errors = False
        self.sync_attempts = 3

    def test_upload_files_and_create_package(self):
        # Values passed in from the command line
        input_kwargs = {
            "package_file": "package/file/path",
            "name": "test_package",
            "version": "1.0.0",
        }

        # Predefine file attributes in for testing
        files = {
            "package_file": {
                "path": "package/file/path",
                "checksum": "package_file_checksum",
                "id": "package_file_identifier",
            },
        }

        # Kwargs for package creation in final step, contain ids returned from the AWS S3 upload
        create_package_kwargs = {
            "package_file": files["package_file"]["id"],
            "name": self.name,
            "version": self.version,
        }

        with (
            patch(
                "cloudsmith_cli.cli.commands.push.validate_create_package"
            ) as mock_validate_create_package,
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file"
            ) as mock_validate_upload_file,
            patch("cloudsmith_cli.cli.commands.push.upload_file") as mock_upload_file,
            patch(
                "cloudsmith_cli.cli.commands.push.create_package"
            ) as mock_create_package,
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
        ):
            # Validate upload returns checksums which we use to upload the files
            mock_validate_upload_file.side_effect = [
                file["checksum"] for file in files.values()
            ]
            # Upload files returns files ids which we use to create the package
            mock_upload_file.side_effect = [file["id"] for file in files.values()]
            mock_create_package.return_value = ("", "test_package_slug")

            # 1. Call upload_files_and_create_package function
            upload_files_and_create_package(
                self.mock_ctx,
                self.mock_opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                **input_kwargs,
            )

            # 2. Confirm that validate_create_package was called with the correct arguments
            mock_validate_create_package.assert_called_once_with(
                ctx=self.mock_ctx,
                opts=self.mock_opts,
                owner=self.owner,
                repo=self.repo,
                package_type=self.package_type,
                skip_errors=self.skip_errors,
                **input_kwargs,
            )

            # 3. For each file, confirm that validate_upload_file and upload_file were called with the correct arguments
            for file_data in files.values():
                mock_validate_upload_file.assert_any_call(
                    ctx=self.mock_ctx,
                    opts=self.mock_opts,
                    owner=self.owner,
                    repo=self.repo,
                    filepath=file_data["path"],
                    skip_errors=self.skip_errors,
                )
                mock_upload_file.assert_any_call(
                    ctx=self.mock_ctx,
                    opts=self.mock_opts,
                    owner=self.owner,
                    repo=self.repo,
                    filepath=file_data["path"],
                    skip_errors=self.skip_errors,
                    md5_checksum=file_data["checksum"],
                )

            # 4. Validate that create_package was called once with the correct arguments
            mock_create_package.assert_called_once_with(
                ctx=self.mock_ctx,
                opts=self.mock_opts,
                owner=self.owner,
                repo=self.repo,
                package_type=self.package_type,
                skip_errors=self.skip_errors,
                **create_package_kwargs,
            )

    def test_upload_files_and_create_package_with_metadata(self):
        """Successful push with metadata creates package + metadata entry."""
        input_kwargs = {
            "package_file": "package/file/path",
            "name": "test_package",
            "version": "1.0.0",
        }
        metadata_kwargs = {
            "metadata_content": '{"git_sha": "abc123"}',
            "metadata_content_type": "application/vnd.jfrog.buildinfo+json",
            "metadata_source_identity": "github-actions@example",
        }

        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file"
            ) as mock_validate_upload_file,
            patch("cloudsmith_cli.cli.commands.push.upload_file") as mock_upload_file,
            patch(
                "cloudsmith_cli.cli.commands.push.create_package"
            ) as mock_create_package,
            patch("cloudsmith_cli.cli.commands.push.api_validate_metadata"),
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata"
            ) as mock_create_metadata,
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
        ):
            mock_validate_upload_file.return_value = "checksum"
            mock_upload_file.return_value = "package_file_identifier"
            mock_create_package.return_value = ("slug-perm-abc", "test_package_slug")
            mock_create_metadata.return_value = {"slug_perm": "meta-slug-xyz"}

            upload_files_and_create_package(
                self.mock_ctx,
                self.mock_opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                **input_kwargs,
                **metadata_kwargs,
            )

            mock_create_metadata.assert_called_once_with(
                "slug-perm-abc",
                content={"git_sha": "abc123"},
                content_type="application/vnd.jfrog.buildinfo+json",
                source_identity="github-actions@example",
            )

    def test_upload_files_and_create_package_with_json_null_metadata(self):
        """Explicit JSON null is rejected before upload by default."""
        with (
            patch(
                "cloudsmith_cli.cli.commands.push.validate_create_package"
            ) as mock_validate_create_package,
            patch("cloudsmith_cli.cli.commands.push.api_validate_metadata"),
            patch("cloudsmith_cli.cli.commands.push.api_create_metadata"),
        ):
            with pytest.raises(click.ClickException, match="JSON object"):
                upload_files_and_create_package(
                    self.mock_ctx,
                    MagicMock(spec=[]),
                    self.package_type,
                    [self.owner, self.repo],
                    self.dry_run,
                    self.no_wait_for_sync,
                    self.wait_interval,
                    self.skip_errors,
                    self.sync_attempts,
                    package_file="path",
                    name="x",
                    version="1",
                    metadata_content="null",
                    metadata_content_type="application/json",
                )

        mock_validate_create_package.assert_not_called()

    def test_upload_attach_publishes_metadata_info_to_opts(self):
        """Attach result is published on opts.push_metadata_info for JSON output."""
        api_entry = {
            "slug_perm": "meta-slug-xyz",
            "content_type": "application/json",
            "classification": "GENERIC",
            "source_kind": "CUSTOMER",
            "source_identity": "github-actions@demo",
            "content": {"git_sha": "abc123"},
        }

        opts = MagicMock(spec=[])

        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file",
                return_value="checksum",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.upload_file",
                return_value="package_file_identifier",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.create_package",
                return_value=("slug-perm-abc", "test_package_slug"),
            ),
            patch("cloudsmith_cli.cli.commands.push.api_validate_metadata"),
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata",
                return_value=api_entry,
            ),
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
        ):
            result = upload_files_and_create_package(
                self.mock_ctx,
                opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                package_file="path",
                name="x",
                version="1",
                metadata_content='{"git_sha": "abc123"}',
                metadata_content_type="application/json",
            )

        assert result == ("slug-perm-abc", "test_package_slug")
        assert opts.push_metadata_info == {
            "status": "attached",
            "slug_perm": "meta-slug-xyz",
            "entry": api_entry,
        }

    def test_upload_files_and_create_package_metadata_failure_warn_does_not_fail_push(
        self,
    ):
        """With CLOUDSMITH_METADATA_FAILURE_MODE=warn the push survives a bad attach."""
        input_kwargs = {
            "package_file": "package/file/path",
            "name": "test_package",
            "version": "1.0.0",
        }
        metadata_kwargs = {
            "metadata_content": '{"git_sha": "abc123"}',
            "metadata_content_type": "application/json",
        }

        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file"
            ) as mock_validate_upload_file,
            patch("cloudsmith_cli.cli.commands.push.upload_file") as mock_upload_file,
            patch(
                "cloudsmith_cli.cli.commands.push.create_package"
            ) as mock_create_package,
            patch("cloudsmith_cli.cli.commands.push.api_validate_metadata"),
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata"
            ) as mock_create_metadata,
            patch(
                "cloudsmith_cli.cli.commands.push.wait_for_package_sync"
            ) as mock_wait_for_sync,
            patch.dict(
                "cloudsmith_cli.cli.commands.push.os.environ",
                {"CLOUDSMITH_METADATA_FAILURE_MODE": "warn"},
            ),
        ):
            mock_validate_upload_file.return_value = "checksum"
            mock_upload_file.return_value = "package_file_identifier"
            mock_create_package.return_value = ("slug-perm-abc", "test_package_slug")
            mock_create_metadata.side_effect = ApiException(
                status=422, detail="Schema validation failed"
            )

            opts = MagicMock(spec=[])

            # Push must complete without raising, returning the slug pair.
            result = upload_files_and_create_package(
                self.mock_ctx,
                opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                **input_kwargs,
                **metadata_kwargs,
            )

            assert result == ("slug-perm-abc", "test_package_slug")
            assert opts.push_metadata_info == {
                "status": "attach_failed",
                "http_status": 422,
                "error": "Schema validation failed",
            }
            mock_create_metadata.assert_called_once()
            # Sync wait still happens — push behaviour unchanged otherwise.
            mock_wait_for_sync.assert_called_once()

    def test_upload_files_and_create_package_metadata_failure_default_aborts_push(self):
        """Default failure mode (no env override) aborts the push on a bad attach."""
        input_kwargs = {
            "package_file": "package/file/path",
            "name": "test_package",
            "version": "1.0.0",
        }

        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file",
                return_value="checksum",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.upload_file",
                return_value="package_file_identifier",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.create_package",
                return_value=("slug-perm-abc", "test_package_slug"),
            ),
            patch("cloudsmith_cli.cli.commands.push.api_validate_metadata"),
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata",
                side_effect=ApiException(status=422, detail="bad payload"),
            ),
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
            patch.dict(
                "cloudsmith_cli.cli.commands.push.os.environ",
                {},
                clear=False,
            ) as patched_env,
        ):
            patched_env.pop("CLOUDSMITH_METADATA_FAILURE_MODE", None)
            opts = SimpleNamespace(
                output=None,
                push_metadata_info=None,
                verbose=False,
                debug=False,
                api_key=None,
                api_host=None,
            )
            ctx = click.Context(click.Command("test"))

            with pytest.raises(click.exceptions.Exit) as exc_info:
                upload_files_and_create_package(
                    ctx,
                    opts,
                    self.package_type,
                    [self.owner, self.repo],
                    self.dry_run,
                    self.no_wait_for_sync,
                    self.wait_interval,
                    self.skip_errors,
                    self.sync_attempts,
                    metadata_content='{"x": 1}',
                    metadata_content_type="application/json",
                    **input_kwargs,
                )

            assert exc_info.value.exit_code == 422
            assert opts.push_metadata_info == {
                "status": "attach_failed",
                "http_status": 422,
                "error": "bad payload",
            }

    def test_prevalidate_metadata_404_aborts_before_upload_by_default(self):
        """A validation endpoint API error aborts before upload by default."""
        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file",
                return_value="checksum",
            ) as mock_validate_upload_file,
            patch(
                "cloudsmith_cli.cli.commands.push.upload_file",
                return_value="package_file_identifier",
            ) as mock_upload_file,
            patch(
                "cloudsmith_cli.cli.commands.push.create_package",
                return_value=("slug-perm-abc", "test_package_slug"),
            ) as mock_create_package,
            patch(
                "cloudsmith_cli.cli.commands.push.api_validate_metadata",
                side_effect=ApiException(status=404, detail="Not Found"),
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata",
                return_value={"slug_perm": "meta-slug-xyz"},
            ),
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
        ):
            opts = SimpleNamespace(
                output=None,
                push_metadata_info=None,
                verbose=False,
                debug=False,
                api_key=None,
                api_host=None,
            )
            ctx = click.Context(click.Command("test"))
            with pytest.raises(click.exceptions.Exit) as exc_info:
                upload_files_and_create_package(
                    ctx,
                    opts,
                    self.package_type,
                    [self.owner, self.repo],
                    self.dry_run,
                    self.no_wait_for_sync,
                    self.wait_interval,
                    self.skip_errors,
                    self.sync_attempts,
                    package_file="path",
                    name="x",
                    version="1",
                    metadata_content='{"x": 1}',
                    metadata_content_type="application/json",
                )

        assert exc_info.value.exit_code == 404
        mock_validate_upload_file.assert_not_called()
        mock_upload_file.assert_not_called()
        mock_create_package.assert_not_called()

    def test_prevalidate_metadata_warn_skips_attach_but_uploads_package(self):
        """Validation failure in warn mode drops attach but lets the package upload."""
        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file",
                return_value="checksum",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.upload_file",
                return_value="package_file_identifier",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.create_package",
                return_value=("slug-perm-abc", "test_package_slug"),
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.api_validate_metadata",
                side_effect=ApiException(status=422, detail="schema mismatch"),
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata"
            ) as mock_create_metadata,
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
            patch.dict(
                "cloudsmith_cli.cli.commands.push.os.environ",
                {"CLOUDSMITH_METADATA_FAILURE_MODE": "warn"},
            ),
        ):
            opts = MagicMock(spec=[])
            result = upload_files_and_create_package(
                self.mock_ctx,
                opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                package_file="path",
                name="x",
                version="1",
                metadata_content='{"x": 1}',
                metadata_content_type="application/json",
            )

        # Package created successfully, metadata attach call never reached.
        assert result == ("slug-perm-abc", "test_package_slug")
        assert opts.push_metadata_info == {
            "status": "validation_failed",
            "http_status": 422,
            "error": "schema mismatch",
        }
        mock_create_metadata.assert_not_called()

    def test_local_metadata_content_warn_skips_attach_but_uploads_package(self):
        """Local JSON object validation failure respects warn mode."""
        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file",
                return_value="checksum",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.upload_file",
                return_value="package_file_identifier",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.create_package",
                return_value=("slug-perm-abc", "test_package_slug"),
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.api_validate_metadata"
            ) as mock_validate_metadata,
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata"
            ) as mock_create_metadata,
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
            patch.dict(
                "cloudsmith_cli.cli.commands.push.os.environ",
                {"CLOUDSMITH_METADATA_FAILURE_MODE": "warn"},
            ),
        ):
            opts = MagicMock(spec=[])
            result = upload_files_and_create_package(
                self.mock_ctx,
                opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                package_file="path",
                name="x",
                version="1",
                metadata_content="[]",
                metadata_content_type="application/json",
            )

        assert result == ("slug-perm-abc", "test_package_slug")
        assert opts.push_metadata_info["status"] == "content_invalid"
        mock_validate_metadata.assert_not_called()
        mock_create_metadata.assert_not_called()

    def test_prevalidate_metadata_default_aborts_before_upload(self):
        """Validation failure aborts before any file upload by default."""
        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file"
            ) as mock_validate_upload_file,
            patch("cloudsmith_cli.cli.commands.push.upload_file") as mock_upload_file,
            patch(
                "cloudsmith_cli.cli.commands.push.create_package"
            ) as mock_create_package,
            patch(
                "cloudsmith_cli.cli.commands.push.api_validate_metadata",
                side_effect=ApiException(status=422, detail="schema mismatch"),
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata"
            ) as mock_create_metadata,
            patch.dict(
                "cloudsmith_cli.cli.commands.push.os.environ",
                {},
                clear=False,
            ) as patched_env,
        ):
            patched_env.pop("CLOUDSMITH_METADATA_FAILURE_MODE", None)
            opts = SimpleNamespace(
                output=None,
                push_metadata_info=None,
                verbose=False,
                debug=False,
                api_key=None,
                api_host=None,
            )
            ctx = click.Context(click.Command("test"))

            with pytest.raises(click.exceptions.Exit) as exc_info:
                upload_files_and_create_package(
                    ctx,
                    opts,
                    self.package_type,
                    [self.owner, self.repo],
                    self.dry_run,
                    self.no_wait_for_sync,
                    self.wait_interval,
                    self.skip_errors,
                    self.sync_attempts,
                    package_file="path",
                    name="x",
                    version="1",
                    metadata_content='{"x": 1}',
                    metadata_content_type="application/json",
                )

            assert exc_info.value.exit_code == 422
            assert opts.push_metadata_info == {
                "status": "validation_failed",
                "http_status": 422,
                "error": "schema mismatch",
            }

        # No upload, no package, no attach.
        mock_validate_upload_file.assert_not_called()
        mock_upload_file.assert_not_called()
        mock_create_package.assert_not_called()
        mock_create_metadata.assert_not_called()

    def test_metadata_content_type_without_payload_errors(self):
        """Setting only --metadata-content-type (no payload) is a usage error."""
        with pytest.raises(click.UsageError, match="Add --metadata-content"):
            upload_files_and_create_package(
                self.mock_ctx,
                self.mock_opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                metadata_content_type="application/json",
                package_file="path",
                name="x",
                version="1",
            )

    def test_metadata_source_identity_without_payload_errors(self):
        """Setting only --metadata-source-identity is a usage error."""
        with pytest.raises(click.UsageError, match="Add --metadata-content"):
            upload_files_and_create_package(
                self.mock_ctx,
                self.mock_opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                metadata_source_identity="ci@example",
                package_file="path",
                name="x",
                version="1",
            )

    def test_metadata_content_without_content_type_errors(self):
        """Metadata content requires --metadata-content-type."""
        with pytest.raises(click.UsageError, match="--metadata-content-type"):
            upload_files_and_create_package(
                self.mock_ctx,
                self.mock_opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                metadata_content="{}",
                package_file="path",
                name="x",
                version="1",
            )

    def test_resolve_push_metadata_options_inline_json(self):
        metadata, failure = resolve_push_metadata_options(
            metadata_content='{"k": "v"}',
            metadata_content_type="application/json",
        )

        assert failure is None
        assert metadata.content == {"k": "v"}
        assert metadata.content_type == "application/json"
        assert metadata.source_label == "inline"

    def test_resolve_push_metadata_options_json_null_rejected(self):
        with pytest.raises(click.ClickException, match="JSON object"):
            resolve_push_metadata_options(
                metadata_content="null",
                metadata_content_type="application/json",
            )

    def test_resolve_push_metadata_options_invalid_json_rejected(self):
        with pytest.raises(click.ClickException, match="Invalid JSON"):
            resolve_push_metadata_options(
                metadata_content="not-json",
                metadata_content_type="application/json",
            )

    def test_resolve_push_metadata_options_invalid_json_warn_returns_failure(self):
        with patch.dict(
            "cloudsmith_cli.cli.commands.push.os.environ",
            {"CLOUDSMITH_METADATA_FAILURE_MODE": "warn"},
        ):
            metadata, failure = resolve_push_metadata_options(
                metadata_content="not-json",
                metadata_content_type="application/json",
            )

        assert metadata.provided is True
        assert metadata.content is None
        assert failure["status"] == "content_invalid"
        assert "Invalid JSON" in failure["error"]

    def test_resolve_push_metadata_options_neither_returns_not_provided(self):
        metadata, failure = resolve_push_metadata_options()

        assert metadata.provided is False
        assert metadata.content is None
        assert failure is None

    def test_resolve_push_metadata_options_mutex(self):
        with pytest.raises(click.UsageError, match="mutually exclusive"):
            resolve_push_metadata_options(
                metadata_content_file="/tmp/foo.json",
                metadata_content='{"k": "v"}',
                metadata_content_type="application/json",
            )

    def test_resolve_push_metadata_options_warn_via_cli_flag(self):
        """``--on-metadata-failure warn`` (on opts) downgrades content errors."""
        opts = SimpleNamespace(cli_metadata_failure_mode="warn")
        with patch.dict(
            "cloudsmith_cli.cli.commands.push.os.environ", {}, clear=False
        ) as patched_env:
            patched_env.pop("CLOUDSMITH_METADATA_FAILURE_MODE", None)
            metadata, failure = resolve_push_metadata_options(
                metadata_content="not-json",
                metadata_content_type="application/json",
                opts=opts,
            )

        assert metadata.provided is True
        assert metadata.content is None
        assert failure["status"] == "content_invalid"

    def test_resolve_push_metadata_options_warn_via_config_key(self):
        """``metadata_failure_mode`` config key downgrades when no flag/env set."""
        opts = SimpleNamespace(metadata_failure_mode="warn")
        with patch.dict(
            "cloudsmith_cli.cli.commands.push.os.environ", {}, clear=False
        ) as patched_env:
            patched_env.pop("CLOUDSMITH_METADATA_FAILURE_MODE", None)
            metadata, failure = resolve_push_metadata_options(
                metadata_content="not-json",
                metadata_content_type="application/json",
                opts=opts,
            )

        assert metadata.provided is True
        assert failure["status"] == "content_invalid"

    def test_resolve_push_metadata_options_flag_beats_env_error(self):
        """``--on-metadata-failure error`` overrides ``...=warn`` in the env."""
        opts = SimpleNamespace(cli_metadata_failure_mode="error")
        with patch.dict(
            "cloudsmith_cli.cli.commands.push.os.environ",
            {"CLOUDSMITH_METADATA_FAILURE_MODE": "warn"},
        ):
            with pytest.raises(click.ClickException, match="Invalid JSON"):
                resolve_push_metadata_options(
                    metadata_content="not-json",
                    metadata_content_type="application/json",
                    opts=opts,
                )

    def test_resolve_push_metadata_options_env_beats_config_error(self):
        """``...=warn`` env var overrides ``metadata_failure_mode = error`` config."""
        opts = SimpleNamespace(metadata_failure_mode="error")
        with patch.dict(
            "cloudsmith_cli.cli.commands.push.os.environ",
            {"CLOUDSMITH_METADATA_FAILURE_MODE": "warn"},
        ):
            metadata, failure = resolve_push_metadata_options(
                metadata_content="not-json",
                metadata_content_type="application/json",
                opts=opts,
            )

        assert metadata.provided is True
        assert failure["status"] == "content_invalid"

    def test_resolve_push_metadata_options_reads_stdin_via_dash(self):
        """``--metadata-content-file -`` reads JSON from stdin once."""
        import io

        stdin = io.StringIO('{"git_sha": "abc123"}')
        with patch(
            "cloudsmith_cli.cli.metadata_common.click.get_text_stream",
            return_value=stdin,
        ):
            metadata, failure = resolve_push_metadata_options(
                metadata_content_file="-",
                metadata_content_type="application/json",
            )

        assert failure is None
        assert metadata.content == {"git_sha": "abc123"}
        assert metadata.source_label == "stdin"

    def test_cached_stdin_metadata_payload_reused_across_uploads(self):
        """The push command resolves ``-`` metadata before per-file uploads."""
        import io

        open_calls = []

        def fake_get_text_stream(name):
            assert name == "stdin"
            open_calls.append(name)
            return io.StringIO('{"git_sha": "abc123"}')

        metadata_kwargs = {
            "metadata_content_file": "-",
            "metadata_content": None,
            "metadata_content_type": "application/json",
            "metadata_source_identity": None,
        }

        with patch(
            "cloudsmith_cli.cli.metadata_common.click.get_text_stream",
            side_effect=fake_get_text_stream,
        ):
            metadata, metadata_failure_info = resolve_push_metadata_options(
                **metadata_kwargs
            )

        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file",
                return_value="checksum",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.upload_file",
                return_value="package_file_identifier",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.create_package",
                side_effect=[
                    ("slug-perm-abc", "test_package_slug"),
                    ("slug-perm-def", "test_package_slug_2"),
                ],
            ),
            patch("cloudsmith_cli.cli.commands.push.api_validate_metadata"),
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata",
                return_value={"slug_perm": "meta-slug-xyz"},
            ) as mock_create_metadata,
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
        ):
            for package_file in ("path-1", "path-2"):
                upload_files_and_create_package(
                    self.mock_ctx,
                    MagicMock(spec=[]),
                    self.package_type,
                    [self.owner, self.repo],
                    self.dry_run,
                    self.no_wait_for_sync,
                    self.wait_interval,
                    self.skip_errors,
                    self.sync_attempts,
                    package_file=package_file,
                    name="x",
                    version="1",
                    metadata=metadata,
                    metadata_failure_info=metadata_failure_info,
                )

        assert open_calls == ["stdin"]
        assert mock_create_metadata.call_count == 2
        for call in mock_create_metadata.call_args_list:
            assert call.kwargs["content"] == {"git_sha": "abc123"}
            assert call.kwargs["content_type"] == "application/json"

    def test_metadata_content_file_round_trip(self):
        """A JSON file given via --metadata-content-file reaches the API call."""
        payload = {"git_sha": "abc123", "build": 42}
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            with (
                patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
                patch(
                    "cloudsmith_cli.cli.commands.push.validate_upload_file",
                    return_value="checksum",
                ),
                patch(
                    "cloudsmith_cli.cli.commands.push.upload_file",
                    return_value="package_file_identifier",
                ),
                patch(
                    "cloudsmith_cli.cli.commands.push.create_package",
                    return_value=("slug-perm-abc", "test_package_slug"),
                ),
                patch("cloudsmith_cli.cli.commands.push.api_validate_metadata"),
                patch(
                    "cloudsmith_cli.cli.commands.push.api_create_metadata",
                    return_value={"slug_perm": "meta-slug-xyz"},
                ) as mock_create_metadata,
                patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
            ):
                upload_files_and_create_package(
                    self.mock_ctx,
                    MagicMock(spec=[]),
                    self.package_type,
                    [self.owner, self.repo],
                    self.dry_run,
                    self.no_wait_for_sync,
                    self.wait_interval,
                    self.skip_errors,
                    self.sync_attempts,
                    package_file="path",
                    name="x",
                    version="1",
                    metadata_content_file=path,
                    metadata_content_type="application/json",
                )

            kwargs = mock_create_metadata.call_args.kwargs
            assert kwargs["content"] == payload
        finally:
            os.unlink(path)

    def test_metadata_default_source_identity(self):
        """Without --metadata-source-identity the default is cloudsmith-cli@<version>."""
        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file",
                return_value="checksum",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.upload_file",
                return_value="package_file_identifier",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.create_package",
                return_value=("slug-perm-abc", "test_package_slug"),
            ),
            patch("cloudsmith_cli.cli.commands.push.api_validate_metadata"),
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata",
                return_value={"slug_perm": "meta-slug-xyz"},
            ) as mock_create_metadata,
            patch(
                "cloudsmith_cli.cli.metadata_common.get_cli_version",
                return_value="9.9.9",
            ),
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
        ):
            upload_files_and_create_package(
                self.mock_ctx,
                MagicMock(spec=[]),
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                package_file="path",
                name="x",
                version="1",
                metadata_content='{"x": 1}',
                metadata_content_type="application/json",
            )

        assert (
            mock_create_metadata.call_args.kwargs["source_identity"]
            == "cloudsmith-cli@9.9.9"
        )

    def test_metadata_retry_hint_emitted_on_attach_warn_failure(self):
        """Attach failure (warn mode, file payload) routes to the hint helper."""
        opts = SimpleNamespace(output=None, push_metadata_info=None)
        metadata = ResolvedMetadata(
            provided=True,
            content={"x": 1},
            content_type="application/vnd.cyclonedx+json",
            source_identity="ci@gha",
            content_file="/tmp/sbom.json",
            source_label="sbom.json",
        )

        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file",
                return_value="checksum",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.upload_file",
                return_value="package_file_identifier",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.create_package",
                return_value=("slug-perm-abc", "test_package_slug"),
            ),
            patch("cloudsmith_cli.cli.commands.push.api_validate_metadata"),
            patch(
                "cloudsmith_cli.cli.commands.push.api_create_metadata",
                side_effect=ApiException(status=422, detail="bad payload"),
            ),
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
            patch("cloudsmith_cli.cli.commands.push._print_metadata_retry_hint") as spy,
            patch.dict(
                "cloudsmith_cli.cli.commands.push.os.environ",
                {"CLOUDSMITH_METADATA_FAILURE_MODE": "warn"},
            ),
        ):
            upload_files_and_create_package(
                self.mock_ctx,
                opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                package_file="path",
                name="x",
                version="1",
                metadata_content_type="application/vnd.cyclonedx+json",
                metadata_source_identity="ci@gha",
                metadata=metadata,
            )

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        assert kwargs["owner"] == self.owner
        assert kwargs["repo"] == self.repo
        assert kwargs["slug"] == "test_package_slug"
        assert kwargs["metadata_content_file"] == "/tmp/sbom.json"
        assert kwargs["cli_content_type"] == "application/vnd.cyclonedx+json"
        assert kwargs["cli_source_identity"] == "ci@gha"

    def test_metadata_retry_hint_emitted_on_validation_warn_failure(self):
        """Pre-validation warn failure routes to the hint helper after create."""
        opts = SimpleNamespace(output=None, push_metadata_info=None)
        metadata = ResolvedMetadata(
            provided=True,
            content={"x": 1},
            content_type="application/json",
            source_identity="cloudsmith-cli@9.9.9",
            content_file="/tmp/buildinfo.json",
            source_label="buildinfo.json",
        )

        with (
            patch("cloudsmith_cli.cli.commands.push.validate_create_package"),
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file",
                return_value="checksum",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.upload_file",
                return_value="package_file_identifier",
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.create_package",
                return_value=("slug-perm-abc", "test_package_slug"),
            ),
            patch(
                "cloudsmith_cli.cli.commands.push.api_validate_metadata",
                side_effect=ApiException(status=422, detail="schema mismatch"),
            ),
            patch("cloudsmith_cli.cli.commands.push.api_create_metadata"),
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
            patch("cloudsmith_cli.cli.commands.push._print_metadata_retry_hint") as spy,
            patch.dict(
                "cloudsmith_cli.cli.commands.push.os.environ",
                {"CLOUDSMITH_METADATA_FAILURE_MODE": "warn"},
            ),
        ):
            upload_files_and_create_package(
                self.mock_ctx,
                opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                package_file="path",
                name="x",
                version="1",
                metadata_content_type="application/json",
                metadata=metadata,
            )

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        assert kwargs["slug"] == "test_package_slug"
        assert kwargs["metadata_content_file"] == "/tmp/buildinfo.json"

    def test_upload_files_and_create_package_extra_files(self):
        # Values passed in from the command line
        input_kwargs = {
            "package_file": "package/file/path",
            "test_file": "test/file/path",
            "extra_files": ["test/extra/file/path1", "test/extra/file/path2"],
            "name": "test_package",
            "version": "1.0.0",
        }

        # Predefine file attributes in for testing
        files = {
            "package_file": {
                "path": "package/file/path",
                "checksum": "package_file_checksum",
                "id": "package_file_identifier",
            },
            "test_file": {
                "path": "test/file/path",
                "checksum": "test_file_checksum",
                "id": "test_file_identifier",
            },
            "extra_file1": {
                "path": "test/extra/file/path1",
                "checksum": "extra_file_checksum1",
                "id": "extra_file_identifier1",
            },
            "extra_file2": {
                "path": "test/extra/file/path2",
                "checksum": "extra_file_checksum2",
                "id": "extra_file_identifier2",
            },
        }

        # Kwargs for package creation in final step, contain ids returned from the AWS S3 upload
        create_package_kwargs = {
            "package_file": files["package_file"]["id"],
            "test_file": files["test_file"]["id"],
            "extra_files": [
                files["extra_file1"]["id"],
                files["extra_file2"]["id"],
            ],
            "name": self.name,
            "version": self.version,
        }

        with (
            patch(
                "cloudsmith_cli.cli.commands.push.validate_create_package"
            ) as mock_validate_create_package,
            patch(
                "cloudsmith_cli.cli.commands.push.validate_upload_file"
            ) as mock_validate_upload_file,
            patch("cloudsmith_cli.cli.commands.push.upload_file") as mock_upload_file,
            patch(
                "cloudsmith_cli.cli.commands.push.create_package"
            ) as mock_create_package,
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
        ):
            # Validate upload returns checksums which we use to upload the files
            mock_validate_upload_file.side_effect = [
                file["checksum"] for file in files.values()
            ]
            # Upload files returns files ids which we use to create the package
            mock_upload_file.side_effect = [file["id"] for file in files.values()]
            mock_create_package.return_value = ("", "test_package_slug")

            # 1. Call upload_files_and_create_package function
            upload_files_and_create_package(
                self.mock_ctx,
                self.mock_opts,
                self.package_type,
                [self.owner, self.repo],
                self.dry_run,
                self.no_wait_for_sync,
                self.wait_interval,
                self.skip_errors,
                self.sync_attempts,
                **input_kwargs,
            )

            # 2. Confirm that validate_create_package was called with the correct arguments
            mock_validate_create_package.assert_called_once_with(
                ctx=self.mock_ctx,
                opts=self.mock_opts,
                owner=self.owner,
                repo=self.repo,
                package_type=self.package_type,
                skip_errors=self.skip_errors,
                **input_kwargs,
            )

            # 3. For each file, confirm that validate_upload_file and upload_file were called with the correct arguments
            for file_data in files.values():
                mock_validate_upload_file.assert_any_call(
                    ctx=self.mock_ctx,
                    opts=self.mock_opts,
                    owner=self.owner,
                    repo=self.repo,
                    filepath=file_data["path"],
                    skip_errors=self.skip_errors,
                )
                mock_upload_file.assert_any_call(
                    ctx=self.mock_ctx,
                    opts=self.mock_opts,
                    owner=self.owner,
                    repo=self.repo,
                    filepath=file_data["path"],
                    skip_errors=self.skip_errors,
                    md5_checksum=file_data["checksum"],
                )

            # 4. Validate that create_package was called once with the correct arguments
            mock_create_package.assert_called_once_with(
                ctx=self.mock_ctx,
                opts=self.mock_opts,
                owner=self.owner,
                repo=self.repo,
                package_type=self.package_type,
                skip_errors=self.skip_errors,
                **create_package_kwargs,
            )


# Plain pytest functions for hint output — capsys is not auto-injected into
# unittest.TestCase methods, so these live outside the class.


def _hint_opts(output=None):
    return SimpleNamespace(output=output, push_metadata_info=None)


def _api_opts(output="json"):
    return SimpleNamespace(
        output=output,
        push_metadata_info=None,
        verbose=False,
        debug=False,
        api_key=None,
        api_host=None,
    )


def test_validate_metadata_payload_json_failure_uses_api_error_envelope(capsys):
    ctx = click.Context(click.Command("push"))
    opts = _api_opts(output="json")

    with (
        patch(
            "cloudsmith_cli.cli.commands.push.api_validate_metadata",
            side_effect=ApiException(status=422, detail="bad payload"),
        ),
        patch.dict(
            "cloudsmith_cli.cli.commands.push.os.environ",
            {},
            clear=False,
        ) as patched_env,
    ):
        patched_env.pop("CLOUDSMITH_METADATA_FAILURE_MODE", None)
        with pytest.raises(click.exceptions.Exit) as exc_info:
            validate_metadata_payload(
                ctx=ctx,
                opts=opts,
                content={"x": 1},
                content_type="application/json",
                source="inline",
            )

    assert exc_info.value.exit_code == 422
    data = json.loads(capsys.readouterr().out)
    assert data["detail"] == "bad payload"
    assert data["help"]["context"].startswith("Metadata content failed validation")
    assert data["metadata_attachment"] == {
        "status": "validation_failed",
        "http_status": 422,
        "error": "bad payload",
    }


def test_attach_metadata_json_failure_uses_api_error_envelope(capsys):
    ctx = click.Context(click.Command("push"))
    opts = _api_opts(output="pretty_json")

    with (
        patch(
            "cloudsmith_cli.cli.commands.push.api_create_metadata",
            side_effect=ApiException(status=422, detail="bad payload"),
        ),
        patch.dict(
            "cloudsmith_cli.cli.commands.push.os.environ",
            {},
            clear=False,
        ) as patched_env,
    ):
        patched_env.pop("CLOUDSMITH_METADATA_FAILURE_MODE", None)
        with pytest.raises(click.exceptions.Exit) as exc_info:
            attach_metadata_to_package(
                ctx=ctx,
                opts=opts,
                owner="acme",
                repo="repo",
                slug="hello-txt",
                slug_perm="hello-txt-abc",
                content={"x": 1},
                content_type="application/json",
                source_identity="ci@example",
            )

    assert exc_info.value.exit_code == 422
    data = json.loads(capsys.readouterr().out)
    assert data["detail"] == "bad payload"
    assert data["help"]["context"].startswith("Could not attach metadata")
    assert data["metadata_attachment"] == {
        "status": "attach_failed",
        "http_status": 422,
        "error": "bad payload",
    }


def test_print_metadata_retry_hint_emits_copy_paste_command(capsys):
    _print_metadata_retry_hint(
        opts=_hint_opts(),
        owner="acme",
        repo="repo",
        slug="hello-txt-abc",
        metadata_content_file="/tmp/sbom.json",
        cli_content_type="application/vnd.cyclonedx+json",
        cli_source_identity="ci@gha",
    )
    err = capsys.readouterr().err
    assert "Run this command to attach metadata:" in err
    assert "cloudsmith metadata add acme/repo/hello-txt-abc" in err
    assert "--file /tmp/sbom.json" in err
    assert "--source-identity ci@gha" in err
    assert "--content-type application/vnd.cyclonedx+json" in err


def test_print_metadata_retry_hint_omits_default_flags(capsys):
    _print_metadata_retry_hint(
        opts=_hint_opts(),
        owner="acme",
        repo="repo",
        slug="hello-txt-abc",
        metadata_content_file="/tmp/sbom.json",
        cli_content_type=None,
        cli_source_identity=None,
    )
    err = capsys.readouterr().err
    assert "cloudsmith metadata add acme/repo/hello-txt-abc" in err
    assert "--file /tmp/sbom.json" in err
    assert "--source-identity" not in err
    assert "--content-type" not in err


def test_print_metadata_retry_hint_silent_for_inline_content(capsys):
    _print_metadata_retry_hint(
        opts=_hint_opts(),
        owner="acme",
        repo="repo",
        slug="hello-txt-abc",
        metadata_content_file=None,
        cli_content_type=None,
        cli_source_identity=None,
    )
    assert capsys.readouterr().err == ""


def test_print_metadata_retry_hint_silent_for_stdin(capsys):
    """Stdin payload (``-``) is not safely reproducible — suppress the hint."""
    _print_metadata_retry_hint(
        opts=_hint_opts(),
        owner="acme",
        repo="repo",
        slug="hello-txt-abc",
        metadata_content_file="-",
        cli_content_type=None,
        cli_source_identity=None,
    )
    assert capsys.readouterr().err == ""


def test_print_metadata_retry_hint_silent_in_json_mode(capsys):
    _print_metadata_retry_hint(
        opts=_hint_opts(output="json"),
        owner="acme",
        repo="repo",
        slug="hello-txt-abc",
        metadata_content_file="/tmp/sbom.json",
        cli_content_type=None,
        cli_source_identity=None,
    )
    assert capsys.readouterr().err == ""


def test_options_metadata_failure_mode_accepts_valid_values():
    """Options setter normalises supported values and stores them."""
    from cloudsmith_cli.cli.config import Options

    for raw, expected in (
        ("error", "error"),
        ("warn", "warn"),
        ("0", "0"),
        ("WARN", "warn"),
        (" warn ", "warn"),
    ):
        opts = Options()
        opts.metadata_failure_mode = raw
        assert opts.metadata_failure_mode == expected


def test_options_metadata_failure_mode_rejects_invalid_value():
    """Options setter rejects anything outside the supported set."""
    from cloudsmith_cli.cli.config import Options

    opts = Options()
    with pytest.raises(click.UsageError, match="Invalid metadata_failure_mode"):
        opts.metadata_failure_mode = "nope"


def test_options_metadata_failure_mode_none_is_noop():
    """Passing ``None`` leaves the option unset (config absent)."""
    from cloudsmith_cli.cli.config import Options

    opts = Options()
    opts.metadata_failure_mode = None
    assert opts.metadata_failure_mode is None
