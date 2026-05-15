"""CLI tests for the `cloudsmith metadata` command group."""

import json
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from cloudsmith_cli.cli.commands.metadata import metadata_
from cloudsmith_cli.core.pagination import MAX_PAGE_SIZE, PageInfo


def _empty_page_info():
    """Return an invalid PageInfo, matching current v2 API responses."""
    return PageInfo()


def _page_info(*, page, page_total, count, page_size=MAX_PAGE_SIZE):
    info = PageInfo()
    info.count = count
    info.page = page
    info.page_size = page_size
    info.page_total = page_total
    return info


class TestMetadataGroupSmoke(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_help_lists_subcommands(self):
        result = self.runner.invoke(metadata_, ["--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("list", result.output)
        self.assertIn("add", result.output)
        self.assertIn("update", result.output)
        self.assertIn("remove", result.output)

    def test_help_preserves_example_lines(self):
        result = self.runner.invoke(metadata_, ["list", "--help"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn(
            "$ cloudsmith metadata list your-org/your-repo/your-pkg\n",
            result.output,
        )
        self.assertIn(
            "$ cloudsmith metadata list your-org/your-repo/your-pkg "
            "--classification provenance\n",
            result.output,
        )
        self.assertIn(
            "$ cloudsmith metadata list your-org/your-repo/your-pkg meta-slug-perm\n",
            result.output,
        )

    def test_add_help_preserves_multiline_example(self):
        result = self.runner.invoke(metadata_, ["add", "--help"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn(
            "$ cloudsmith metadata add your-org/your-repo/your-pkg \\\n",
            result.output,
        )
        self.assertIn("--content-type application/json \\\n", result.output)
        self.assertIn('--content \'{"foo": "bar"}\'', result.output)
        self.assertIn("cat metadata.json | cloudsmith metadata add", result.output)
        self.assertIn("--file -", result.output)
        self.assertIn("application/vnd.jfrog.buildinfo+json", result.output)
        self.assertIn("--file buildinfo.json", result.output)

    def test_update_help_preserves_stdin_example(self):
        result = self.runner.invoke(metadata_, ["update", "--help"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("cat metadata.json | cloudsmith metadata update", result.output)
        self.assertIn("--file -", result.output)


class TestMetadataList(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    @patch("cloudsmith_cli.cli.commands.metadata.api_list_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_list_resolves_slug_perm_and_calls_list(self, mock_resolve, mock_list):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_list.return_value = ([], _empty_page_info())

        result = self.runner.invoke(metadata_, ["list", "myorg/myrepo/mypkg"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_resolve.assert_called_once_with(
            owner="myorg", repo="myrepo", identifier="mypkg"
        )
        mock_list.assert_called_once()
        kwargs = mock_list.call_args.kwargs
        self.assertEqual(kwargs["package_slug_perm"], "pkg-slug-perm")
        self.assertIsNone(kwargs.get("source_kind"))
        self.assertIsNone(kwargs.get("classification"))

    @patch("cloudsmith_cli.cli.commands.metadata.api_list_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_list_passes_filters(self, mock_resolve, mock_list):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_list.return_value = ([], _empty_page_info())

        result = self.runner.invoke(
            metadata_,
            [
                "list",
                "myorg/myrepo/mypkg",
                "--source-kind",
                "customer",
                "--classification",
                "4",
            ],
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        kwargs = mock_list.call_args.kwargs
        self.assertEqual(kwargs["source_kind"], "customer")
        self.assertEqual(kwargs["classification"], "4")

    @patch("cloudsmith_cli.cli.commands.metadata.api_list_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_list_json_output(self, mock_resolve, mock_list):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_list.return_value = (
            [
                {
                    "slug_perm": "abc",
                    "content_type": "application/json",
                    "classification": "GENERIC",
                    "source_kind": "CUSTOMER",
                    "source_identity": "cloudsmith-cli@1.16.0",
                }
            ],
            _empty_page_info(),
        )

        result = self.runner.invoke(
            metadata_, ["list", "-F", "json", "myorg/myrepo/mypkg"]
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["data"]), 1)
        self.assertEqual(payload["data"][0]["slug_perm"], "abc")

    @patch("cloudsmith_cli.cli.commands.metadata.api_list_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_list_invalid_filter_value_is_usage_error(self, mock_resolve, mock_list):
        mock_resolve.return_value = "pkg-slug-perm"

        result = self.runner.invoke(
            metadata_,
            ["list", "myorg/myrepo/mypkg", "--source-kind", "not-a-kind"],
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("source_kind", result.output.lower())
        mock_list.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.metadata.api_list_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_list_page_all_aggregates_all_pages(self, mock_resolve, mock_list):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_list.side_effect = [
            (
                [
                    {
                        "slug_perm": "first",
                        "content_type": "application/json",
                    }
                ],
                _page_info(page=1, page_total=2, count=2),
            ),
            (
                [
                    {
                        "slug_perm": "second",
                        "content_type": "application/json",
                    }
                ],
                _page_info(page=2, page_total=2, count=2),
            ),
        ]

        result = self.runner.invoke(
            metadata_, ["list", "-F", "json", "myorg/myrepo/mypkg", "--page-all"]
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.stdout)
        self.assertEqual(
            [item["slug_perm"] for item in payload["data"]], ["first", "second"]
        )
        self.assertNotIn("meta", payload)
        self.assertEqual(mock_list.call_count, 2)
        self.assertEqual(
            [call.kwargs["page"] for call in mock_list.call_args_list], [1, 2]
        )
        self.assertTrue(
            all(
                call.kwargs["page_size"] == MAX_PAGE_SIZE
                for call in mock_list.call_args_list
            )
        )

    @patch("cloudsmith_cli.cli.commands.metadata.api_list_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_list_ls_alias(self, mock_resolve, mock_list):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_list.return_value = ([], _empty_page_info())

        result = self.runner.invoke(metadata_, ["ls", "myorg/myrepo/mypkg"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_list.assert_called_once()


class TestMetadataListSingle(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    @patch("cloudsmith_cli.cli.commands.metadata.api_get_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_list_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_single_fetch_calls_get_and_skips_list(
        self, mock_resolve, mock_list, mock_get
    ):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_get.return_value = {
            "slug_perm": "meta-slug",
            "content_type": "application/json",
            "content": {"hello": "world"},
        }

        result = self.runner.invoke(
            metadata_, ["list", "myorg/myrepo/mypkg", "meta-slug"]
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_get.assert_called_once_with("pkg-slug-perm", "meta-slug")
        mock_list.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.metadata.api_get_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_single_fetch_json_output(self, mock_resolve, mock_get):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_get.return_value = {
            "slug_perm": "meta-slug",
            "content_type": "application/json",
            "content": {"hello": "world"},
        }

        result = self.runner.invoke(
            metadata_,
            ["list", "-F", "json", "myorg/myrepo/mypkg", "meta-slug"],
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["data"]["slug_perm"], "meta-slug")
        self.assertEqual(payload["data"]["content"], {"hello": "world"})


class TestMetadataAdd(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    @patch("cloudsmith_cli.cli.commands.metadata.api_create_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_add_with_inline_content(self, mock_resolve, mock_create):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_create.return_value = {"slug_perm": "new-slug"}

        result = self.runner.invoke(
            metadata_,
            [
                "add",
                "myorg/myrepo/mypkg",
                "--content-type",
                "application/json",
                "--content",
                '{"foo": "bar"}',
            ],
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["content"], {"foo": "bar"})
        self.assertEqual(kwargs["content_type"], "application/json")
        self.assertTrue(kwargs["source_identity"].startswith("cloudsmith-cli@"))
        # First positional arg is the resolved slug_perm.
        self.assertEqual(mock_create.call_args.args[0], "pkg-slug-perm")

    @patch("cloudsmith_cli.cli.commands.metadata.api_create_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_add_with_file(self, mock_resolve, mock_create):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_create.return_value = {"slug_perm": "new-slug"}

        with self.runner.isolated_filesystem():
            with open("payload.json", "w", encoding="utf-8") as fh:
                fh.write('{"hello": "world"}')

            result = self.runner.invoke(
                metadata_,
                [
                    "add",
                    "myorg/myrepo/mypkg",
                    "--content-type",
                    "application/json",
                    "--file",
                    "payload.json",
                ],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["content"], {"hello": "world"})

    @patch("cloudsmith_cli.cli.commands.metadata.api_create_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_add_with_stdin_file(self, mock_resolve, mock_create):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_create.return_value = {"slug_perm": "new-slug"}

        result = self.runner.invoke(
            metadata_,
            [
                "add",
                "myorg/myrepo/mypkg",
                "--content-type",
                "application/json",
                "--file",
                "-",
            ],
            input='{"from": "stdin"}',
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["content"], {"from": "stdin"})

    @patch("cloudsmith_cli.cli.commands.metadata.api_create_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_add_rejects_both_sources(self, mock_resolve, mock_create):
        mock_resolve.return_value = "pkg-slug-perm"

        with self.runner.isolated_filesystem():
            with open("payload.json", "w", encoding="utf-8") as fh:
                fh.write("{}")

            result = self.runner.invoke(
                metadata_,
                [
                    "add",
                    "myorg/myrepo/mypkg",
                    "--content-type",
                    "application/json",
                    "--file",
                    "payload.json",
                    "--content",
                    "{}",
                ],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("mutually exclusive", result.output.lower())
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.metadata.api_create_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_add_requires_one_source(self, mock_resolve, mock_create):
        mock_resolve.return_value = "pkg-slug-perm"

        result = self.runner.invoke(
            metadata_,
            [
                "add",
                "myorg/myrepo/mypkg",
                "--content-type",
                "application/json",
            ],
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--file", result.output)
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.metadata.api_create_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_add_invalid_json_is_usage_error(self, mock_resolve, mock_create):
        mock_resolve.return_value = "pkg-slug-perm"

        result = self.runner.invoke(
            metadata_,
            [
                "add",
                "myorg/myrepo/mypkg",
                "--content-type",
                "application/json",
                "--content",
                "{not json",
            ],
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("invalid", result.output.lower())
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.metadata.api_create_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_add_invalid_stdin_json_is_usage_error(self, mock_resolve, mock_create):
        mock_resolve.return_value = "pkg-slug-perm"

        result = self.runner.invoke(
            metadata_,
            [
                "add",
                "myorg/myrepo/mypkg",
                "--content-type",
                "application/json",
                "--file",
                "-",
            ],
            input="{not json",
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("invalid json in stdin", result.output.lower())
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.metadata.api_create_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_add_rejects_non_object_content(self, mock_resolve, mock_create):
        mock_resolve.return_value = "pkg-slug-perm"

        for raw in ("null", "[]"):
            result = self.runner.invoke(
                metadata_,
                [
                    "add",
                    "myorg/myrepo/mypkg",
                    "--content-type",
                    "application/json",
                    "--content",
                    raw,
                ],
            )

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("json object", result.output.lower())

        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.metadata.api_create_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_add_uses_explicit_source_identity(self, mock_resolve, mock_create):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_create.return_value = {"slug_perm": "new-slug"}

        result = self.runner.invoke(
            metadata_,
            [
                "add",
                "myorg/myrepo/mypkg",
                "--content-type",
                "application/json",
                "--content",
                "{}",
                "--source-identity",
                "ci-pipeline:42",
            ],
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["source_identity"], "ci-pipeline:42")


class TestMetadataUpdate(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    @patch("cloudsmith_cli.cli.commands.metadata.api_update_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_update_patches_content(self, mock_resolve, mock_update):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_update.return_value = {"slug_perm": "meta-slug"}

        result = self.runner.invoke(
            metadata_,
            [
                "update",
                "myorg/myrepo/mypkg",
                "meta-slug",
                "--content",
                '{"foo": "baz"}',
            ],
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_update.assert_called_once()
        args = mock_update.call_args.args
        kwargs = mock_update.call_args.kwargs
        self.assertEqual(args, ("pkg-slug-perm", "meta-slug"))
        self.assertEqual(kwargs["content"], {"foo": "baz"})
        self.assertNotIn("source_identity", kwargs)

    @patch("cloudsmith_cli.cli.commands.metadata.api_update_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_update_patches_stdin_file(self, mock_resolve, mock_update):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_update.return_value = {"slug_perm": "meta-slug"}

        result = self.runner.invoke(
            metadata_,
            [
                "update",
                "myorg/myrepo/mypkg",
                "meta-slug",
                "--file",
                "-",
            ],
            input='{"foo": "from-stdin"}',
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        kwargs = mock_update.call_args.kwargs
        self.assertEqual(kwargs["content"], {"foo": "from-stdin"})
        self.assertNotIn("source_identity", kwargs)

    @patch("cloudsmith_cli.cli.commands.metadata.api_update_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_update_patches_source_identity_only(self, mock_resolve, mock_update):
        mock_resolve.return_value = "pkg-slug-perm"
        mock_update.return_value = {"slug_perm": "meta-slug"}

        result = self.runner.invoke(
            metadata_,
            [
                "update",
                "myorg/myrepo/mypkg",
                "meta-slug",
                "--source-identity",
                "ci-pipeline:99",
            ],
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        kwargs = mock_update.call_args.kwargs
        self.assertEqual(kwargs["source_identity"], "ci-pipeline:99")
        self.assertNotIn("content", kwargs)

    @patch("cloudsmith_cli.cli.commands.metadata.api_update_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_update_rejects_both_content_sources(self, mock_resolve, mock_update):
        mock_resolve.return_value = "pkg-slug-perm"

        with self.runner.isolated_filesystem():
            with open("payload.json", "w", encoding="utf-8") as fh:
                fh.write("{}")

            result = self.runner.invoke(
                metadata_,
                [
                    "update",
                    "myorg/myrepo/mypkg",
                    "meta-slug",
                    "--file",
                    "payload.json",
                    "--content",
                    "{}",
                ],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("mutually exclusive", result.output.lower())
        mock_update.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.metadata.api_update_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_update_requires_some_field(self, mock_resolve, mock_update):
        mock_resolve.return_value = "pkg-slug-perm"

        result = self.runner.invoke(
            metadata_,
            ["update", "myorg/myrepo/mypkg", "meta-slug"],
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("nothing to update", result.output.lower())
        mock_update.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.metadata.api_update_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_update_rejects_non_object_content(self, mock_resolve, mock_update):
        mock_resolve.return_value = "pkg-slug-perm"

        result = self.runner.invoke(
            metadata_,
            [
                "update",
                "myorg/myrepo/mypkg",
                "meta-slug",
                "--content",
                "[]",
            ],
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("json object", result.output.lower())
        mock_update.assert_not_called()

    def test_update_rejects_content_type_flag(self):
        result = self.runner.invoke(
            metadata_,
            [
                "update",
                "myorg/myrepo/mypkg",
                "meta-slug",
                "--content-type",
                "application/json",
            ],
        )

        self.assertNotEqual(result.exit_code, 0)
        # Click's default is "no such option"
        self.assertIn("--content-type", result.output)


class TestMetadataRemove(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    @patch("cloudsmith_cli.cli.commands.metadata.api_delete_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_remove_calls_delete(self, mock_resolve, mock_delete):
        mock_resolve.return_value = "pkg-slug-perm"

        result = self.runner.invoke(
            metadata_, ["remove", "-y", "myorg/myrepo/mypkg", "meta-slug"]
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_delete.assert_called_once_with("pkg-slug-perm", "meta-slug")

    @patch("cloudsmith_cli.cli.commands.metadata.api_delete_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_remove_prompts_and_aborts(self, mock_resolve, mock_delete):
        result = self.runner.invoke(
            metadata_, ["remove", "myorg/myrepo/mypkg", "meta-slug"], input="N\n"
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Are you absolutely certain", result.output)
        mock_resolve.assert_not_called()
        mock_delete.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.metadata.api_delete_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_remove_alias_rm(self, mock_resolve, mock_delete):
        mock_resolve.return_value = "pkg-slug-perm"

        result = self.runner.invoke(
            metadata_, ["rm", "-y", "myorg/myrepo/mypkg", "meta-slug"]
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        mock_delete.assert_called_once_with("pkg-slug-perm", "meta-slug")

    @patch("cloudsmith_cli.cli.commands.metadata.api_delete_metadata")
    @patch("cloudsmith_cli.cli.commands.metadata.api_get_package_slug_perm")
    def test_remove_json_output(self, mock_resolve, mock_delete):
        mock_resolve.return_value = "pkg-slug-perm"

        result = self.runner.invoke(
            metadata_,
            ["remove", "-F", "json", "-y", "myorg/myrepo/mypkg", "meta-slug"],
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["data"]["deleted"])
        self.assertEqual(payload["data"]["slug_perm"], "meta-slug")


if __name__ == "__main__":
    unittest.main()
