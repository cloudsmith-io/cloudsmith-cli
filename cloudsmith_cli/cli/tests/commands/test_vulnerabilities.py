import unittest
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

    def test_vulnerabilities_invalid_slug(self):
        """Test validation of invalid package slug."""
        result = self.runner.invoke(
            vulnerabilities,
            [
                "invalid-slug-format",
            ],
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Invalid format", result.output)

    @patch("cloudsmith_cli.cli.commands.vulnerabilities.get_package_scan_result")
    def test_vulnerabilities_html_report(self, mock_get_scan):
        """Test vulnerabilities command with --html flag."""
        result = self.runner.invoke(
            vulnerabilities,
            [
                "testorg/testrepo/pkg-slug",
                "--html",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        args = mock_get_scan.call_args[1]
        self.assertEqual(args["html_report"], "DEFAULT")


if __name__ == "__main__":
    unittest.main()
