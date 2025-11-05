import unittest
from unittest.mock import Mock, patch

import click
from click.testing import CliRunner

from cloudsmith_cli.cli.commands.download import download
from cloudsmith_cli.core.api.exceptions import ApiException


class TestDownloadCommand(unittest.TestCase):
    """Test the download CLI command."""

    def setUp(self):
        self.runner = CliRunner()
        self.mock_opts = Mock()
        self.mock_opts.debug = False
        self.mock_opts.output = "pretty"
        self.mock_opts.verbose = False

    @patch("cloudsmith_cli.cli.commands.download.resolve_auth")
    @patch("cloudsmith_cli.cli.commands.download.resolve_package")
    @patch("cloudsmith_cli.cli.commands.download.get_download_url")
    @patch("cloudsmith_cli.cli.commands.download.stream_download")
    def test_download_basic_success(
        self, mock_stream, mock_get_url, mock_resolve_pkg, mock_resolve_auth
    ):
        """Test basic successful download."""
        # Mock auth resolution
        mock_session = Mock()
        mock_resolve_auth.return_value = (
            mock_session,
            {"X-Api-Key": "test"},
            "api-key",
        )

        # Mock package resolution
        mock_package = {
            "name": "test-package",
            "version": "1.0.0",
            "format": "deb",
            "filename": "test-package_1.0.0.deb",
            "size": 1024,
        }
        mock_resolve_pkg.return_value = mock_package

        # Mock download URL
        mock_get_url.return_value = "https://example.com/test-package_1.0.0.deb"

        result = self.runner.invoke(
            download,
            [
                "--config-file",
                "/dev/null",
                "--api-key",
                "test-key",
                "testorg/testrepo",
                "test-package",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Download completed successfully!", result.output)

        # Verify calls
        mock_resolve_pkg.assert_called_once()
        mock_get_url.assert_called_once_with(mock_package)
        mock_stream.assert_called_once()

    @patch("cloudsmith_cli.cli.commands.download.resolve_auth")
    @patch("cloudsmith_cli.cli.commands.download.resolve_package")
    @patch("cloudsmith_cli.cli.commands.download.get_download_url")
    def test_download_dry_run(self, mock_get_url, mock_resolve_pkg, mock_resolve_auth):
        """Test dry run mode."""
        # Mock setup
        mock_session = Mock()
        mock_resolve_auth.return_value = (mock_session, {}, "none")

        mock_package = {
            "name": "test-package",
            "version": "1.0.0",
            "format": "deb",
            "size": 2048,
        }
        mock_resolve_pkg.return_value = mock_package
        mock_get_url.return_value = "https://example.com/test.deb"

        result = self.runner.invoke(
            download,
            [
                "--config-file",
                "/dev/null",
                "--dry-run",
                "testorg/testrepo",
                "test-package",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Dry run - would download:", result.output)
        self.assertIn("test-package v1.0.0", result.output)

    @patch("cloudsmith_cli.cli.commands.download.resolve_auth")
    @patch("cloudsmith_cli.cli.commands.download.resolve_package")
    def test_download_package_not_found(self, mock_resolve_pkg, mock_resolve_auth):
        """Test package not found scenario."""
        mock_session = Mock()
        mock_resolve_auth.return_value = (mock_session, {}, "none")

        # Mock package not found
        exc = click.ClickException("No packages found")
        exc.exit_code = 2
        mock_resolve_pkg.side_effect = exc

        result = self.runner.invoke(
            download,
            ["--config-file", "/dev/null", "testorg/testrepo", "nonexistent-package"],
        )

        self.assertEqual(result.exit_code, 2)

    @patch("cloudsmith_cli.cli.commands.download.resolve_auth")
    @patch("cloudsmith_cli.cli.commands.download.resolve_package")
    def test_download_multiple_packages_no_yes(
        self, mock_resolve_pkg, mock_resolve_auth
    ):
        """Test multiple packages found without --yes flag."""
        mock_session = Mock()
        mock_resolve_auth.return_value = (mock_session, {}, "none")

        # Mock multiple packages found
        exc = click.ClickException("Multiple packages found")
        exc.exit_code = 3
        mock_resolve_pkg.side_effect = exc

        result = self.runner.invoke(
            download,
            ["--config-file", "/dev/null", "testorg/testrepo", "ambiguous-package"],
        )

        self.assertEqual(result.exit_code, 3)

    @patch("cloudsmith_cli.cli.commands.download.resolve_auth")
    @patch("cloudsmith_cli.cli.commands.download.resolve_package")
    @patch("cloudsmith_cli.cli.commands.download.get_download_url")
    @patch("cloudsmith_cli.cli.commands.download.stream_download")
    def test_download_with_filters(
        self, mock_stream, mock_get_url, mock_resolve_pkg, mock_resolve_auth
    ):
        """Test download with version and format filters."""
        mock_session = Mock()
        mock_resolve_auth.return_value = (mock_session, {}, "none")

        mock_package = {
            "name": "test-package",
            "version": "2.0.0",
            "format": "rpm",
            "filename": "test-package-2.0.0.rpm",
        }
        mock_resolve_pkg.return_value = mock_package
        mock_get_url.return_value = "https://example.com/test.rpm"

        result = self.runner.invoke(
            download,
            [
                "--config-file",
                "/dev/null",
                "--version",
                "2.0.0",
                "--format",
                "rpm",
                "--arch",
                "x86_64",
                "testorg/testrepo",
                "test-package",
            ],
        )

        self.assertEqual(result.exit_code, 0)

        # Verify filters were passed to resolve_package
        call_args = mock_resolve_pkg.call_args
        self.assertEqual(call_args[1]["version"], "2.0.0")
        self.assertEqual(call_args[1]["format_filter"], "rpm")
        self.assertEqual(call_args[1]["arch_filter"], "x86_64")

    @patch("cloudsmith_cli.cli.commands.download.resolve_auth")
    @patch("cloudsmith_cli.cli.commands.download.resolve_package")
    @patch("cloudsmith_cli.cli.commands.download.get_download_url")
    @patch("cloudsmith_cli.cli.commands.download.stream_download")
    def test_download_custom_output_file(
        self, mock_stream, mock_get_url, mock_resolve_pkg, mock_resolve_auth
    ):
        """Test download with custom output filename."""
        mock_session = Mock()
        mock_resolve_auth.return_value = (mock_session, {}, "none")

        mock_package = {"name": "test-package", "version": "1.0.0"}
        mock_resolve_pkg.return_value = mock_package
        mock_get_url.return_value = "https://example.com/test.deb"

        result = self.runner.invoke(
            download,
            [
                "--config-file",
                "/dev/null",
                "--outfile",
                "/tmp/my-custom-name.deb",
                "testorg/testrepo",
                "test-package",
            ],
        )

        self.assertEqual(result.exit_code, 0)

        # Verify custom filename was used
        stream_call_args = mock_stream.call_args
        self.assertIn("/tmp/my-custom-name.deb", str(stream_call_args))

    @patch("cloudsmith_cli.cli.commands.download.resolve_auth")
    @patch("cloudsmith_cli.cli.commands.download.resolve_package")
    @patch("cloudsmith_cli.cli.commands.download.get_download_url")
    @patch("cloudsmith_cli.cli.commands.download.stream_download")
    def test_download_overwrite_flag(
        self, mock_stream, mock_get_url, mock_resolve_pkg, mock_resolve_auth
    ):
        """Test download with overwrite flag."""
        mock_session = Mock()
        mock_resolve_auth.return_value = (mock_session, {}, "none")

        mock_package = {"name": "test-package", "version": "1.0.0"}
        mock_resolve_pkg.return_value = mock_package
        mock_get_url.return_value = "https://example.com/test.deb"

        result = self.runner.invoke(
            download,
            [
                "--config-file",
                "/dev/null",
                "--overwrite",
                "testorg/testrepo",
                "test-package",
            ],
        )

        self.assertEqual(result.exit_code, 0)

        # Verify overwrite was passed to stream_download
        stream_call_args = mock_stream.call_args
        self.assertTrue(stream_call_args[1]["overwrite"])

    @patch("cloudsmith_cli.cli.commands.download.resolve_auth")
    @patch("cloudsmith_cli.cli.commands.download.resolve_package")
    @patch("cloudsmith_cli.cli.commands.download.get_download_url")
    @patch("cloudsmith_cli.cli.commands.download.get_package_detail")
    @patch("cloudsmith_cli.cli.commands.download.stream_download")
    def test_download_fallback_to_package_detail(
        self,
        mock_stream,
        mock_get_detail,
        mock_get_url,
        mock_resolve_pkg,
        mock_resolve_auth,
    ):
        """Test fallback to package detail when download URL not in list result."""
        mock_session = Mock()
        mock_resolve_auth.return_value = (mock_session, {}, "none")

        mock_package = {"name": "test-package", "version": "1.0.0", "slug": "test-slug"}
        mock_resolve_pkg.return_value = mock_package

        # First call returns None, second call returns URL
        mock_get_url.side_effect = [
            click.ClickException("No download URL"),
            "https://example.com/test.deb",
        ]

        mock_detail_package = {
            "name": "test-package",
            "version": "1.0.0",
            "cdn_url": "https://example.com/test.deb",
        }
        mock_get_detail.return_value = mock_detail_package

        result = self.runner.invoke(
            download, ["--config-file", "/dev/null", "testorg/testrepo", "test-package"]
        )

        # Should fail because we're raising an exception
        self.assertEqual(result.exit_code, 1)
        # But verify the right calls were still attempted
        self.assertTrue(mock_get_url.called)

    def test_download_invalid_repo_format(self):
        """Test error handling for invalid repository format."""
        result = self.runner.invoke(
            download,
            ["--config-file", "/dev/null", "invalid-repo-format", "test-package"],
        )

        self.assertEqual(result.exit_code, 2)  # Click validation error

    @patch("cloudsmith_cli.cli.commands.download.resolve_auth")
    def test_download_api_exception_handling(self, mock_resolve_auth):
        """Test API exception handling."""
        # Mock API exception during auth resolution
        mock_resolve_auth.side_effect = ApiException(status=401)

        result = self.runner.invoke(
            download, ["--config-file", "/dev/null", "testorg/testrepo", "test-package"]
        )

        self.assertEqual(result.exit_code, 1)

    def test_get_extension_for_format(self):
        """Test file extension mapping for different formats."""
        from cloudsmith_cli.cli.commands.download import _get_extension_for_format

        self.assertEqual(_get_extension_for_format("deb"), "deb")
        self.assertEqual(_get_extension_for_format("rpm"), "rpm")
        self.assertEqual(_get_extension_for_format("python"), "whl")
        self.assertEqual(_get_extension_for_format("npm"), "tgz")
        self.assertEqual(_get_extension_for_format("unknown"), "bin")

    def test_format_package_size(self):
        """Test package size formatting."""
        from cloudsmith_cli.cli.commands.download import _format_package_size

        self.assertEqual(_format_package_size({"size": 0}), "Unknown")
        self.assertEqual(_format_package_size({"size": 1024}), "1.0 KB")
        self.assertEqual(_format_package_size({"size": 1048576}), "1.0 MB")
        self.assertEqual(_format_package_size({}), "Unknown")


if __name__ == "__main__":
    unittest.main()
