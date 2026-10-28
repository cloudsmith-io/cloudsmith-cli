import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    @patch("cloudsmith_cli.core.api.vulnerabilities.get_vulnerabilities_api")
    def test_vulnerabilities_no_scan_results(self, mock_get_api):
        """Test that a package with no scan results gives a JSON error."""
        mock_get_api.return_value.vulnerabilities_package_list_with_http_info.return_value = (
            [],
            200,
            {},
        )

        result = self.runner.invoke(
            vulnerabilities, ["testorg/testrepo/pkg-slug", "-F", "json"]
        )

        self.assertEqual(result.exit_code, 404)
        self.assertEqual(
            json.loads(result.stdout)["detail"],
            "The package has no vulnerability scan results.",
        )

    @patch("cloudsmith_cli.core.api.vulnerabilities.get_vulnerabilities_api")
    def test_vulnerabilities_no_scan_results_pretty(self, mock_get_api):
        """Test that a package with no scan results shows no user/org hint."""
        mock_get_api.return_value.vulnerabilities_package_list_with_http_info.return_value = (
            [],
            200,
            {},
        )

        result = self.runner.invoke(vulnerabilities, ["testorg/testrepo/pkg-slug"])

        self.assertEqual(result.exit_code, 404)
        self.assertIn("The package has no vulnerability scan results.", result.output)
        self.assertNotIn("user/org", result.output)

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    def test_vulnerabilities_null_scans(self, mock_get_scan):
        """Test that a scan result with null scans shows an empty summary."""
        mock_get_scan.return_value = SimpleNamespace(
            package=None, scans=None, num_vulnerabilities=None
        )

        result = self.runner.invoke(
            vulnerabilities, ["testorg/testrepo/pkg-slug", "--severity", "high"]
        )

        self.assertEqual(result.exit_code, 0, result.output)

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    def test_vulnerabilities_null_results_and_severity(self, mock_get_scan):
        """Test that null results and a null severity count as unknown."""
        vulnerability = SimpleNamespace(
            vulnerability_id="CVE-1",
            severity=None,
            package_name=None,
            affected_version=None,
            fixed_version=None,
            title=None,
        )
        mock_get_scan.return_value = SimpleNamespace(
            package=None,
            num_vulnerabilities=1,
            scans=[
                SimpleNamespace(results=None),
                SimpleNamespace(results=[vulnerability]),
            ],
        )

        result = self.runner.invoke(
            vulnerabilities,
            ["testorg/testrepo/pkg-slug", "-A", "--severity", "unknown"],
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("CVE-1", result.stdout)


if __name__ == "__main__":
    unittest.main()
