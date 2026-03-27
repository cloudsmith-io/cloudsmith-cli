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
        input_kwargs = {
            "package_file": "package/file/path",
            "name": "test_package",
            "version": "1.0.0",
        }

        files = {
            "package_file": {
                "path": "package/file/path",
                "id": "package_file_identifier",
            },
        }

        create_package_kwargs = {
            "package_file": files["package_file"]["id"],
            "name": self.name,
            "version": self.version,
        }

        with (
            patch(
                "cloudsmith_cli.cli.commands.push.validate_create_package"
            ) as mock_validate_create_package,
            patch("cloudsmith_cli.cli.commands.push._upload_file") as mock_upload_file,
            patch(
                "cloudsmith_cli.cli.commands.push.create_package"
            ) as mock_create_package,
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
        ):
            mock_upload_file.side_effect = [file["id"] for file in files.values()]
            mock_create_package.return_value = ("", "test_package_slug")

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

            mock_validate_create_package.assert_called_once_with(
                ctx=self.mock_ctx,
                opts=self.mock_opts,
                owner=self.owner,
                repo=self.repo,
                package_type=self.package_type,
                skip_errors=self.skip_errors,
                **input_kwargs,
            )

            for file_data in files.values():
                mock_upload_file.assert_any_call(
                    ctx=self.mock_ctx,
                    opts=self.mock_opts,
                    owner=self.owner,
                    repo=self.repo,
                    filepath=file_data["path"],
                    skip_errors=self.skip_errors,
                )

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
        input_kwargs = {
            "package_file": "package/file/path",
            "test_file": "test/file/path",
            "extra_files": ["test/extra/file/path1", "test/extra/file/path2"],
            "name": "test_package",
            "version": "1.0.0",
        }

        files = {
            "package_file": {
                "path": "package/file/path",
                "id": "package_file_identifier",
            },
            "test_file": {
                "path": "test/file/path",
                "id": "test_file_identifier",
            },
            "extra_file1": {
                "path": "test/extra/file/path1",
                "id": "extra_file_identifier1",
            },
            "extra_file2": {
                "path": "test/extra/file/path2",
                "id": "extra_file_identifier2",
            },
        }

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
            patch("cloudsmith_cli.cli.commands.push._upload_file") as mock_upload_file,
            patch(
                "cloudsmith_cli.cli.commands.push.create_package"
            ) as mock_create_package,
            patch("cloudsmith_cli.cli.commands.push.wait_for_package_sync"),
        ):
            mock_upload_file.side_effect = [file["id"] for file in files.values()]
            mock_create_package.return_value = ("", "test_package_slug")

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

            mock_validate_create_package.assert_called_once_with(
                ctx=self.mock_ctx,
                opts=self.mock_opts,
                owner=self.owner,
                repo=self.repo,
                package_type=self.package_type,
                skip_errors=self.skip_errors,
                **input_kwargs,
            )

            for file_data in files.values():
                mock_upload_file.assert_any_call(
                    ctx=self.mock_ctx,
                    opts=self.mock_opts,
                    owner=self.owner,
                    repo=self.repo,
                    filepath=file_data["path"],
                    skip_errors=self.skip_errors,
                )

            mock_create_package.assert_called_once_with(
                ctx=self.mock_ctx,
                opts=self.mock_opts,
                owner=self.owner,
                repo=self.repo,
                package_type=self.package_type,
                skip_errors=self.skip_errors,
                **create_package_kwargs,
            )
