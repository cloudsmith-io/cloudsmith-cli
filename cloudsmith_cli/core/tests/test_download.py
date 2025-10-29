"""Tests for core download functionality."""

# pylint: disable=protected-access  # Testing private functions is acceptable in tests

import tempfile
import unittest
from unittest.mock import Mock, patch

import click
import requests

from cloudsmith_cli.core import download


class TestResolveAuth(unittest.TestCase):
    """Test auth resolution logic."""

    def setUp(self):
        self.mock_opts = Mock()
        self.mock_opts.debug = False
        self.mock_opts.rate_limit = True
        self.mock_opts.error_retry_cb = None
        self.mock_opts.api_key = None

    @patch("cloudsmith_cli.core.download.create_requests_session")
    def test_resolve_auth_api_key_from_opts(self, mock_create_session):
        """Test auth resolution with API key from opts."""
        mock_session = Mock()
        mock_create_session.return_value = mock_session
        self.mock_opts.api_key = "test-api-key"

        session, headers, auth_source = download.resolve_auth(self.mock_opts)

        self.assertEqual(session, mock_session)
        self.assertEqual(headers, {"X-Api-Key": "test-api-key"})
        self.assertEqual(auth_source, "api-key")

    @patch("cloudsmith_cli.core.download.create_requests_session")
    def test_resolve_auth_api_key_override(self, mock_create_session):
        """Test auth resolution with API key override."""
        mock_session = Mock()
        mock_create_session.return_value = mock_session
        self.mock_opts.api_key = "config-key"

        _session, headers, auth_source = download.resolve_auth(
            self.mock_opts, api_key_opt="override-key"
        )

        self.assertEqual(headers, {"X-Api-Key": "override-key"})
        self.assertEqual(auth_source, "api-key")

    @patch("cloudsmith_cli.core.download.create_requests_session")
    @patch("cloudsmith_cli.core.download.keyring")
    def test_resolve_auth_token_only(self, mock_keyring, mock_create_session):
        """Test auth resolution with token only."""
        mock_session = Mock()
        mock_create_session.return_value = mock_session
        mock_keyring.get_access_token.return_value = None  # No SSO token

        _session, headers, auth_source = download.resolve_auth(
            self.mock_opts, token_opt="test-token"
        )

        self.assertEqual(headers, {})
        self.assertEqual(auth_source, "token")

    @patch("cloudsmith_cli.core.download.create_requests_session")
    @patch("click.echo")
    def test_resolve_auth_both_api_key_and_token_debug(
        self, mock_echo, mock_create_session
    ):
        """Test warning when both API key and token provided in debug mode."""
        mock_session = Mock()
        mock_create_session.return_value = mock_session
        self.mock_opts.debug = True
        self.mock_opts.api_key = "test-api-key"

        _session, _headers, auth_source = download.resolve_auth(
            self.mock_opts, token_opt="test-token"
        )

        self.assertEqual(auth_source, "api-key")
        mock_echo.assert_called_once()


class TestResolvePackage(unittest.TestCase):
    """Test package resolution logic."""

    @patch("cloudsmith_cli.core.download.list_packages")
    def test_resolve_package_single_match(self, mock_list_packages):
        """Test package resolution with single match."""
        mock_package = {"name": "test-package", "version": "1.0.0", "slug": "test-slug"}
        mock_page_info = Mock()
        mock_page_info.is_valid = True
        mock_page_info.page = 1
        mock_page_info.page_total = 1
        mock_list_packages.return_value = ([mock_package], mock_page_info)

        result = download.resolve_package("owner", "repo", "test-package")

        self.assertEqual(result, mock_package)
        mock_list_packages.assert_called_once_with(
            owner="owner", repo="repo", query="name:test-package", page=1, page_size=100
        )

    @patch("cloudsmith_cli.core.download.list_packages")
    def test_resolve_package_no_matches(self, mock_list_packages):
        """Test package resolution with no matches."""
        mock_page_info = Mock()
        mock_page_info.is_valid = True
        mock_page_info.page = 1
        mock_page_info.page_total = 1
        mock_list_packages.return_value = ([], mock_page_info)

        with self.assertRaises(click.ClickException) as cm:
            download.resolve_package("owner", "repo", "nonexistent")

        self.assertEqual(cm.exception.exit_code, 2)

    @patch("cloudsmith_cli.core.download.list_packages")
    @patch("cloudsmith_cli.core.download._select_best_package")
    @patch("click.echo")
    def test_resolve_package_multiple_matches_yes(
        self, mock_echo, mock_select_best, mock_list_packages
    ):
        """Test package resolution with multiple matches and --yes."""
        mock_packages = [
            {"name": "test-package", "version": "1.0.0"},
            {"name": "test-package", "version": "2.0.0"},
        ]
        mock_page_info = Mock()
        mock_page_info.is_valid = True
        mock_page_info.page = 1
        mock_page_info.page_total = 1
        mock_list_packages.return_value = (mock_packages, mock_page_info)
        mock_select_best.return_value = mock_packages[1]

        result = download.resolve_package("owner", "repo", "test-package", yes=True)

        self.assertEqual(result, mock_packages[1])
        mock_select_best.assert_called_once_with(mock_packages)

    @patch("cloudsmith_cli.core.download.list_packages")
    @patch("cloudsmith_cli.cli.utils.pretty_print_table")
    @patch("click.echo")
    def test_resolve_package_multiple_matches_no_yes(
        self, mock_echo, mock_pretty_print, mock_list_packages
    ):
        """Test package resolution with multiple matches without --yes."""
        mock_packages = [
            {"name": "test-package", "version": "1.0.0"},
            {"name": "test-package", "version": "2.0.0"},
        ]
        mock_page_info = Mock()
        mock_page_info.is_valid = True
        mock_page_info.page = 1
        mock_page_info.page_total = 1
        mock_list_packages.return_value = (mock_packages, mock_page_info)

        with self.assertRaises(click.ClickException) as cm:
            download.resolve_package("owner", "repo", "test-package", yes=False)

        self.assertEqual(cm.exception.exit_code, 3)
        mock_pretty_print.assert_called_once()

    @patch("cloudsmith_cli.core.download.list_packages")
    def test_resolve_package_with_filters(self, mock_list_packages):
        """Test package resolution with version and format filters."""
        mock_package = {"name": "test-package", "version": "1.0.0"}
        mock_page_info = Mock()
        mock_page_info.is_valid = True
        mock_page_info.page = 1
        mock_page_info.page_total = 1
        mock_list_packages.return_value = ([mock_package], mock_page_info)

        download.resolve_package(
            "owner", "repo", "test-package", version="1.0.0", format_filter="deb"
        )

        mock_list_packages.assert_called_once_with(
            owner="owner",
            repo="repo",
            query="name:test-package AND version:1.0.0 AND format:deb",
            page=1,
            page_size=100,
        )

    @patch("cloudsmith_cli.core.download.list_packages")
    def test_resolve_package_exact_name_match(self, mock_list_packages):
        """Test that only exact name matches are returned (not partial)."""
        # API returns both partial and exact matches
        mock_packages = [
            {
                "name": "Microsoft.Extensions.DependencyInjection.Abstractions",
                "version": "9.0.7",
            },
            {"name": "Microsoft.Extensions.DependencyInjection", "version": "9.0.7"},
        ]
        mock_page_info = Mock()
        mock_page_info.is_valid = True
        mock_page_info.page = 1
        mock_page_info.page_total = 1
        mock_list_packages.return_value = (mock_packages, mock_page_info)

        # Should only return exact match
        result = download.resolve_package(
            "owner", "repo", "Microsoft.Extensions.DependencyInjection"
        )

        self.assertEqual(result["name"], "Microsoft.Extensions.DependencyInjection")
        self.assertNotEqual(
            result["name"], "Microsoft.Extensions.DependencyInjection.Abstractions"
        )


class TestGetDownloadUrl(unittest.TestCase):
    """Test download URL extraction."""

    def test_get_download_url_cdn_url(self):
        """Test extracting cdn_url."""
        package = {"cdn_url": "https://example.com/file.deb"}
        result = download.get_download_url(package)
        self.assertEqual(result, "https://example.com/file.deb")

    def test_get_download_url_fallback_fields(self):
        """Test fallback to other URL fields."""
        package = {"download_url": "https://example.com/file.deb"}
        result = download.get_download_url(package)
        self.assertEqual(result, "https://example.com/file.deb")

    def test_get_download_url_no_url(self):
        """Test error when no download URL is available."""
        package = {"name": "test-package"}
        with self.assertRaises(click.ClickException):
            download.get_download_url(package)


class TestStreamDownload(unittest.TestCase):
    """Test file streaming and download."""

    def setUp(self):
        self.session = Mock()
        self.temp_dir = tempfile.mkdtemp()

    @patch("os.path.exists")
    def test_stream_download_file_exists_no_overwrite(self, mock_exists):
        """Test error when file exists and overwrite is False."""
        mock_exists.return_value = True

        with self.assertRaises(click.ClickException):
            download.stream_download(
                "https://example.com/file.deb",
                "/path/to/file.deb",
                self.session,
                overwrite=False,
            )

    @patch("os.makedirs")
    @patch("click.open_file")
    @patch("click.progressbar")
    def test_stream_download_success(
        self, mock_progressbar, mock_open_file, mock_makedirs
    ):
        """Test successful download."""
        # Mock response
        mock_response = Mock()
        mock_response.headers = {"content-length": "1024"}
        mock_response.iter_content.return_value = [b"data1", b"data2"]
        self.session.get.return_value = mock_response
        mock_response.raise_for_status.return_value = None

        # Mock file operations
        mock_file = Mock()
        mock_open_file.return_value.__enter__.return_value = mock_file

        # Mock progress bar
        mock_progress = Mock()
        mock_progressbar.return_value.__enter__.return_value = mock_progress

        download.stream_download(
            "https://example.com/file.deb",
            "/path/to/file.deb",
            self.session,
            overwrite=True,
        )

        # Verify file was written
        mock_file.write.assert_any_call(b"data1")
        mock_file.write.assert_any_call(b"data2")

    def test_stream_download_auth_retry_with_token(self):
        """Test retry with entitlement token on 401."""
        # First request fails with 401
        mock_response_401 = Mock()
        mock_response_401.status_code = 401
        mock_error_401 = requests.exceptions.HTTPError(response=mock_response_401)

        # Second request succeeds
        mock_response_200 = Mock()
        mock_response_200.headers = {"content-length": "1024"}
        mock_response_200.iter_content.return_value = [b"data"]
        mock_response_200.raise_for_status.return_value = None

        # Configure session to fail first, succeed second
        self.session.get.side_effect = [mock_error_401, mock_response_200]

        with patch("os.makedirs"), patch("click.open_file") as mock_open_file, patch(
            "click.progressbar"
        ), patch("click.echo"):

            mock_file = Mock()
            mock_open_file.return_value.__enter__.return_value = mock_file

            download.stream_download(
                "https://example.com/file.deb",
                "/path/to/file.deb",
                self.session,
                token="test-token",
                overwrite=True,
            )

            # Verify two requests were made
            self.assertEqual(self.session.get.call_count, 2)

            # Verify second request used Basic Auth with token
            second_call = self.session.get.call_args_list[1]
            auth = second_call[1]["auth"]
            self.assertEqual(auth, ("test-token", ""))


class TestSelectBestPackage(unittest.TestCase):
    """Test package selection logic."""

    def test_select_best_package_version_priority(self):
        """Test selection prioritizes higher version."""
        packages = [
            {"version": "1.0.0", "uploaded_at": "2023-01-01"},
            {"version": "2.0.0", "uploaded_at": "2023-01-01"},
            {"version": "1.5.0", "uploaded_at": "2023-01-01"},
        ]

        result = download._select_best_package(packages)
        self.assertEqual(result["version"], "2.0.0")

    def test_select_best_package_date_tiebreaker(self):
        """Test selection uses date as tiebreaker for same version."""
        packages = [
            {"version": "1.0.0", "uploaded_at": "2023-01-01"},
            {"version": "1.0.0", "uploaded_at": "2023-01-02"},
        ]

        result = download._select_best_package(packages)
        self.assertEqual(result["uploaded_at"], "2023-01-02")


class TestUtilityFunctions(unittest.TestCase):
    """Test utility functions."""

    def test_format_size(self):
        """Test size formatting."""
        self.assertEqual(download._format_size(0), "0 B")
        self.assertEqual(download._format_size(1024), "1.0 KB")
        self.assertEqual(download._format_size(1024 * 1024), "1.0 MB")

    def test_format_date(self):
        """Test date formatting."""
        self.assertEqual(download._format_date(""), "")
        self.assertEqual(download._format_date("2023-12-25T10:30:00Z"), "2023-12-25")
        self.assertEqual(download._format_date("short"), "short")

    @patch("cloudsmith_cli.core.download.utils.calculate_file_md5")
    def test_verify_checksum_md5(self, mock_calculate_md5):
        """Test MD5 checksum verification."""
        mock_calculate_md5.return_value = (
            "abc123def456789012345678901234ef"  # 32 chars for MD5
        )

        # Matching checksum
        result = download._verify_checksum(
            "/path/file", "abc123def456789012345678901234ef"
        )
        self.assertTrue(result)

        # Non-matching checksum
        result = download._verify_checksum(
            "/path/file", "different12345678901234567890ab"
        )
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
