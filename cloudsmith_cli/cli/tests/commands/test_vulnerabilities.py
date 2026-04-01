import unittest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from cloudsmith_cli.cli.commands.vulnerabilities import vulnerabilities


class TestVulnerabilitiesCommand(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    def test_vulnerabilities_basic(self, mock_get_scan):
        """Test basic vulnerabilities command invocation."""
        result = self.runner.invoke(
            vulnerabilities,
            [
                "testorg/testrepo/pkg-slug",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        mock_get_scan.assert_called_once()

        # Verify args passed to core logic
        args = mock_get_scan.call_args[1]
        self.assertEqual(args["owner"], "testorg")
        self.assertEqual(args["repo"], "testrepo")
        self.assertEqual(args["package"], "pkg-slug")
        self.assertFalse(args["show_assessment"])
        self.assertIsNone(args["severity_filter"])

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    def test_vulnerabilities_show_assessment(self, mock_get_scan):
        """Test vulnerabilities command with --show-assessment flag."""
        result = self.runner.invoke(
            vulnerabilities,
            [
                "testorg/testrepo/pkg-slug",
                "--show-assessment",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        args = mock_get_scan.call_args[1]
        self.assertTrue(args["show_assessment"])

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    def test_vulnerabilities_alias_flags(self, mock_get_scan):
        """Test vulnerabilities command with short flags (-A)."""
        result = self.runner.invoke(
            vulnerabilities,
            [
                "testorg/testrepo/pkg-slug",
                "-A",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        args = mock_get_scan.call_args[1]
        self.assertTrue(args["show_assessment"])

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    def test_vulnerabilities_severity_filter(self, mock_get_scan):
        """Test vulnerabilities command with --severity filter."""
        result = self.runner.invoke(
            vulnerabilities,
            [
                "testorg/testrepo/pkg-slug",
                "--severity",
                "CRITICAL,HIGH",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        args = mock_get_scan.call_args[1]
        self.assertEqual(args["severity_filter"], "CRITICAL,HIGH")

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    def test_vulnerabilities_fixable_filter(self, mock_get_scan):
        """Test vulnerabilities command with --fixable filter."""
        result = self.runner.invoke(
            vulnerabilities,
            [
                "testorg/testrepo/pkg-slug",
                "--fixable",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        args = mock_get_scan.call_args[1]
        self.assertTrue(args["fixable"])

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    def test_vulnerabilities_non_fixable_filter(self, mock_get_scan):
        """Test vulnerabilities command with --non-fixable filter."""
        result = self.runner.invoke(
            vulnerabilities,
            [
                "testorg/testrepo/pkg-slug",
                "--non-fixable",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        args = mock_get_scan.call_args[1]
        self.assertFalse(args["fixable"])


# ---------------------------------------------------------------------------
# Helpers shared by repo-summary tests
# ---------------------------------------------------------------------------


def _pkg_dict(slug_perm, name, version="1.0.0"):
    return {"slug_perm": slug_perm, "name": name, "version": version}


def _page_info(page=1, page_total=1):
    pi = MagicMock()
    pi.page = page
    pi.page_total = page_total
    return pi


def _scan_data_vulnerable(name, version, severities):
    """Scan result with at least one vulnerability."""
    data = MagicMock()
    data.package.name = name
    data.package.version = version
    scan = MagicMock()
    scan.results = [MagicMock(severity=s) for s in severities]
    data.scans = [scan]
    return data


def _scan_data_safe(name, version):
    """Scan result with no vulnerabilities (package was scanned, nothing found)."""
    data = MagicMock()
    data.package.name = name
    data.package.version = version
    scan = MagicMock()
    scan.results = []
    data.scans = [scan]
    return data


def _scan_data_no_scan():
    """No scan data available (package not yet scanned or unsupported format)."""
    data = MagicMock()
    data.scans = []
    return data


# ---------------------------------------------------------------------------
# Repo-level summary tests (OWNER/REPO, no package slug)
# ---------------------------------------------------------------------------


class TestRepoSummaryMode(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    # --show-assessment is rejected for repo-level summary ──────────────────

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_show_assessment_rejected(self, mock_list):
        """--show-assessment with OWNER/REPO prints a warning and exits cleanly."""
        result = self.runner.invoke(
            vulnerabilities, ["testorg/testrepo", "--show-assessment"]
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("not supported", result.output)
        mock_list.assert_not_called()

    # Single-package scenarios ───────────────────────────────────────────────

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_single_vulnerable_package(self, mock_list, mock_scan):
        """A repo with one vulnerable package produces a summary table."""
        mock_list.return_value = ([_pkg_dict("slug-abc", "my-lib")], _page_info())
        mock_scan.return_value = _scan_data_vulnerable(
            "my-lib", "1.0.0", ["critical", "high"]
        )

        result = self.runner.invoke(vulnerabilities, ["testorg/testrepo"])

        self.assertEqual(result.exit_code, 0)
        mock_scan.assert_called_once()
        scan_args = mock_scan.call_args[1]
        self.assertEqual(scan_args["owner"], "testorg")
        self.assertEqual(scan_args["repo"], "testrepo")
        self.assertEqual(scan_args["package"], "slug-abc")

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_single_safe_package(self, mock_list, mock_scan):
        """A scanned package with no vulnerabilities is included in the summary."""
        mock_list.return_value = ([_pkg_dict("slug-safe", "clean-lib")], _page_info())
        mock_scan.return_value = _scan_data_safe("clean-lib", "2.0.0")

        result = self.runner.invoke(vulnerabilities, ["testorg/testrepo"])

        self.assertEqual(result.exit_code, 0)
        mock_scan.assert_called_once()

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_single_no_scan_package(self, mock_list, mock_scan):
        """A package with no scan data (unsupported format) is included with no-scan status."""
        mock_list.return_value = ([_pkg_dict("slug-bin", "binary-pkg")], _page_info())
        mock_scan.return_value = _scan_data_no_scan()

        result = self.runner.invoke(vulnerabilities, ["testorg/testrepo"])

        self.assertEqual(result.exit_code, 0)
        mock_scan.assert_called_once()

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_scan_fetch_exception_treated_as_no_scan(self, mock_list, mock_scan):
        """A package whose scan fetch raises is included with no-scan status, not dropped."""
        mock_list.return_value = ([_pkg_dict("slug-err", "error-pkg")], _page_info())
        mock_scan.side_effect = Exception("connection refused")

        result = self.runner.invoke(vulnerabilities, ["testorg/testrepo"])

        # Command should still exit cleanly — the package appears as no-scan
        self.assertEqual(result.exit_code, 0)

    # Multiple packages ──────────────────────────────────────────────────────

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_multiple_packages_mixed_statuses(self, mock_list, mock_scan):
        """Three packages with different statuses are all fetched and summarised."""
        packages = [
            _pkg_dict("slug-vuln", "vuln-lib"),
            _pkg_dict("slug-safe", "safe-lib"),
            _pkg_dict("slug-none", "unsupported-pkg"),
        ]
        mock_list.return_value = (packages, _page_info())
        mock_scan.side_effect = [
            _scan_data_vulnerable("vuln-lib", "1.0.0", ["critical"]),
            _scan_data_safe("safe-lib", "1.0.0"),
            _scan_data_no_scan(),
        ]

        result = self.runner.invoke(vulnerabilities, ["testorg/testrepo"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(mock_scan.call_count, 3)

    # Pagination ─────────────────────────────────────────────────────────────

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_pagination_fetches_all_pages(self, mock_list, mock_scan):
        """Packages spanning two pages are all fetched."""
        page1_pkgs = [_pkg_dict("slug-a", "pkg-a"), _pkg_dict("slug-b", "pkg-b")]
        page2_pkgs = [_pkg_dict("slug-c", "pkg-c")]
        mock_list.side_effect = [
            (page1_pkgs, _page_info(page=1, page_total=2)),
            (page2_pkgs, _page_info(page=2, page_total=2)),
        ]
        mock_scan.return_value = _scan_data_safe("pkg", "1.0.0")

        result = self.runner.invoke(vulnerabilities, ["testorg/testrepo"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(mock_list.call_count, 2)
        self.assertEqual(mock_scan.call_count, 3)

        # Verify page numbers were incremented correctly
        page_numbers = [c[1]["page"] for c in mock_list.call_args_list]
        self.assertEqual(page_numbers, [1, 2])

    # Empty repo ─────────────────────────────────────────────────────────────

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_empty_repo_exits_with_error(self, mock_list):
        """An empty repository raises a ClickException with a helpful message."""
        mock_list.return_value = ([], None)

        result = self.runner.invoke(vulnerabilities, ["testorg/testrepo"])

        self.assertNotEqual(result.exit_code, 0)

    # --severity filter ──────────────────────────────────────────────────────

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_severity_filter_passed_to_scan(self, mock_list, mock_scan):
        """--severity is forwarded to get_package_scan_result."""
        mock_list.return_value = ([_pkg_dict("slug-a", "pkg-a")], _page_info())
        mock_scan.return_value = _scan_data_vulnerable("pkg-a", "1.0.0", ["critical"])

        result = self.runner.invoke(
            vulnerabilities, ["testorg/testrepo", "--severity", "CRITICAL"]
        )

        self.assertEqual(result.exit_code, 0)
        scan_args = mock_scan.call_args[1]
        self.assertEqual(scan_args["severity_filter"], "CRITICAL")

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_severity_filter_no_matches_shows_message(self, mock_list, mock_scan):
        """When --severity matches nothing, a descriptive message is shown."""
        mock_list.return_value = ([_pkg_dict("slug-a", "pkg-a")], _page_info())
        # Safe package — no critical vulnerabilities
        mock_scan.return_value = _scan_data_safe("pkg-a", "1.0.0")

        result = self.runner.invoke(
            vulnerabilities, ["testorg/testrepo", "--severity", "CRITICAL"]
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("No packages found matching filter", result.output)
        self.assertIn("CRITICAL", result.output)

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    def test_severity_filter_excludes_safe_and_no_scan(self, mock_list, mock_scan):
        """With --severity active, safe and no-scan packages are not included in results."""
        packages = [
            _pkg_dict("slug-vuln", "vuln-lib"),
            _pkg_dict("slug-safe", "safe-lib"),
        ]
        mock_list.return_value = (packages, _page_info())
        mock_scan.side_effect = [
            _scan_data_vulnerable("vuln-lib", "1.0.0", ["critical"]),
            _scan_data_safe("safe-lib", "1.0.0"),
        ]

        # Patch the table printer so we can inspect what rows were passed
        with patch(
            "cloudsmith_cli.cli.commands.vulnerabilities._print_repo_summary_table"
        ) as mock_table:
            result = self.runner.invoke(
                vulnerabilities, ["testorg/testrepo", "--severity", "CRITICAL"]
            )

        self.assertEqual(result.exit_code, 0)
        passed_rows = mock_table.call_args[0][0]
        statuses = [row[3] for row in passed_rows]
        self.assertIn("vulnerable", statuses)
        self.assertNotIn("safe", statuses)
        self.assertNotIn("no_issues_found", statuses)
        self.assertNotIn("no_scan", statuses)

    # JSON output ────────────────────────────────────────────────────────────

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.list_packages")
    @patch("cloudsmith_cli.cli.commands.vulnerabilities.utils")
    def test_json_output_includes_status_field(self, mock_utils, mock_list, mock_scan):
        """JSON output includes slug_perm, package, status, and vulnerabilities per package."""
        mock_list.return_value = ([_pkg_dict("slug-abc", "my-lib")], _page_info())
        mock_scan.return_value = _scan_data_vulnerable("my-lib", "1.0.0", ["high"])
        mock_utils.should_use_stderr.return_value = False
        mock_utils.maybe_print_as_json.return_value = True  # pretend JSON was printed

        result = self.runner.invoke(vulnerabilities, ["testorg/testrepo"])

        self.assertEqual(result.exit_code, 0)
        json_payload = mock_utils.maybe_print_as_json.call_args[0][1]
        self.assertEqual(json_payload["owner"], "testorg")
        self.assertEqual(json_payload["repository"], "testrepo")
        self.assertEqual(len(json_payload["packages"]), 1)
        pkg = json_payload["packages"][0]
        self.assertEqual(pkg["slug_perm"], "slug-abc")
        self.assertIn("status", pkg)
        self.assertIn("vulnerabilities", pkg)


if __name__ == "__main__":
    unittest.main()
