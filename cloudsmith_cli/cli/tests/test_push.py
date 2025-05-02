import unittest
from unittest.mock import MagicMock, patch

from ..commands.push import upload_files_and_create_package


# pylint: disable=too-many-instance-attributes
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
