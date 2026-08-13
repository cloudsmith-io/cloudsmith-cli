import json
from unittest.mock import patch

import pytest

from ...commands.list_ import repos as list_repos
from ...commands.main import main
from ...commands.repos import create, delete, get, update
from ..utils import random_str

HERMETIC_ARGS = ["--api-key", "fake-api-key"]

# Not a real GPG key - deliberately not using the literal
# "-----BEGIN ... PRIVATE KEY-----" marker so secret-scanning tooling (e.g.
# the detect-private-key pre-commit hook) doesn't flag this fixture.
_FAKE_GPG_KEY_MATERIAL = "fake-armored-gpg-private-key-material-for-tests-only"

_GPG_KEY = {
    "active": True,
    "comment": "my-repo GPG key",
    "created_at": "2026-01-01T00:00:00Z",
    "default": True,
    "fingerprint": "AAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
    "fingerprint_short": "EEEE5555",
    "public_key": "-----BEGIN PGP PUBLIC KEY BLOCK-----\n...\n-----END PGP PUBLIC KEY BLOCK-----",
}


def gpg_command_args(command, *args):
    """Build arguments that exercise the registered repos GPG command tree."""
    return [
        "repos",
        *HERMETIC_ARGS,
        "gpg",
        command,
        *args,
        *HERMETIC_ARGS,
    ]


def create_repo_config_file(directory, name, description, repository_type_str, slug):
    """Create a REPO-CONFIG.json file in `directory` with the values provided."""
    file_path = directory / "REPO_CONFIG.json"
    data = {
        "name": name,
        "description": description,
        "repository_type_str": repository_type_str,
        "slug": slug,
    }
    file_path.write_text(str(json.dumps(data)))
    return file_path


def parse_table(output):
    """Return a dict of repo properties parsed from the tabular output of a `cloudsmith repos` invocation.

    This function expects (and validates) that there is one row in the table.

    Here is an example output, for `cloudsmith repos update`:
    ```
        Updating eggs repository in the cloudsmith namespace ...OK

        Name | Type    | Packages | Groups | Downloads | Size | Owner / Repository (Identifier)
        spam | Private | 0        | 0      | 0         | 0.0B | cloudsmith/eggs

        Results: 1 repository visible
    ```
    """
    separator = "|"
    column_headers = []
    row_values = []

    for line in output.split("\n"):
        if separator in line:
            raw_values = [raw_value.strip() for raw_value in line.split(separator)]
            if not column_headers:
                # If we don't have keys yet, then this must be the column headers
                column_headers = raw_values
            else:
                # If we already have keys, then this must be a table row
                if row_values:
                    raise Exception(
                        "Multiple rows detected in output table - expected 1."
                    )
                row_values = raw_values

    if not column_headers:
        raise Exception("Output table not found.")

    if not row_values:
        raise Exception("Output table contained no rows.")

    return dict(zip(column_headers, row_values))


def assert_output_is_equal_to_repo_config(output, organisation, repo_config_file_path):
    output_table = parse_table(output)
    repo_config = json.loads(repo_config_file_path.read_text())
    assert output_table["Name"] == repo_config["name"]
    assert output_table["Type"] == repo_config["repository_type_str"]
    assert (
        output_table["Owner / Repository (Identifier)"]
        == organisation + "/" + repo_config["slug"]
    )


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
@pytest.mark.integration
def test_repos_commands(runner, organization, tmp_path):
    """Test CRUD operations for repositories."""

    # Generate some random repository data.
    repository_name = random_str()
    repository_description = random_str()
    repository_slug = random_str()
    repository_type_str = "Private"
    owner_slash_repo = organization + "/" + repository_slug

    # Generate the repository configuration file.
    repo_config_file_path = create_repo_config_file(
        directory=tmp_path,
        name=repository_name,
        description=repository_description,
        repository_type_str=repository_type_str,
        slug=repository_slug,
    )

    # Use the cli to create the repository.
    result = runner.invoke(
        create, [organization, str(repo_config_file_path)], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert (
        "Creating "
        + repository_name
        + " repository for the "
        + organization
        + " namespace ...OK"
        in result.output
    )
    assert "Results: 1 repository visible" in result.output
    assert_output_is_equal_to_repo_config(
        result.output, organization, repo_config_file_path
    )

    # Try getting the repository via the cli.
    result = runner.invoke(get, [owner_slash_repo], catch_exceptions=False)
    assert result.exit_code == 0
    assert "Getting list of repositories ... OK" in result.output
    assert "Results: 1 repository visible" in result.output
    assert_output_is_equal_to_repo_config(
        result.output, organization, repo_config_file_path
    )

    # Demonstrate list repos with --page-size '-1'succeeds (no pagination args).
    result = runner.invoke(
        list_repos, [organization, "--page-size", "-1"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "Getting list of repositories ... OK" in result.output

    # Show that --page-all with an explicit page conflicts.
    conflict = runner.invoke(
        list_repos, [organization, "--page-all", "--page", "2"], catch_exceptions=False
    )
    assert conflict.exit_code != 0
    assert "Invalid value for '--page-all'" in conflict.output
    assert "Cannot be used with --page (-p) or --page-size (-l)." in conflict.output

    # Change the repository description in the repo config file.
    repository_description = random_str()
    repo_config_file_path = create_repo_config_file(
        tmp_path,
        name=repository_name,
        description=repository_description,
        repository_type_str=repository_type_str,
        slug=repository_slug,
    )

    # Check that the update command updates the repository.
    result = runner.invoke(
        update, [owner_slash_repo, str(repo_config_file_path)], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert (
        "Updating "
        + repository_slug
        + " repository in the "
        + organization
        + " namespace ...OK"
        in result.output
    )
    assert "Results: 1 repository visible" in result.output
    assert_output_is_equal_to_repo_config(
        result.output, organization, repo_config_file_path
    )

    # Check that deleting a repo prompts for confirmation.
    result = runner.invoke(
        delete, [owner_slash_repo], input="N", catch_exceptions=False
    )
    assert result.exit_code == 0
    assert (
        "Are you absolutely certain you want to delete the "
        + repository_slug
        + " from the "
        + organization
        + " namespace? [y/N]: N"
        in result.output
    )
    assert "OK, phew! Close call. :-)" in result.output

    # Then delete it for real.
    result = runner.invoke(
        delete, [owner_slash_repo], input="Y", catch_exceptions=False
    )
    assert result.exit_code == 0
    assert (
        "Are you absolutely certain you want to delete the "
        + repository_slug
        + " from the "
        + organization
        + " namespace? [y/N]: Y"
        in result.output
    )
    assert (
        "Deleting "
        + repository_slug
        + " from the "
        + organization
        + " namespace ... OK"
        in result.output
    )


class TestReposGpgGet:
    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    @pytest.mark.parametrize("command_name", ["get", "list", "ls"])
    def test_registered_commands_print_fingerprint(
        self, mock_list, runner, command_name
    ):
        mock_list.return_value = dict(_GPG_KEY)

        result = runner.invoke(
            main,
            gpg_command_args(command_name, "my-org/my-repo"),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        mock_list.assert_called_once_with("my-org", "my-repo")
        assert _GPG_KEY["fingerprint"] in result.output
        assert _GPG_KEY["fingerprint_short"] in result.output

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    def test_json_output(self, mock_list, runner):
        mock_list.return_value = dict(_GPG_KEY)

        result = runner.invoke(
            main,
            gpg_command_args("get", "my-org/my-repo", "-F", "json"),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        # "Getting GPG key ... " progress text goes to stderr, but the runner
        # merges streams, so pick out the JSON line specifically.
        json_line = next(
            line for line in result.output.splitlines() if line.startswith("{")
        )
        document = json.loads(json_line)
        assert document["data"]["fingerprint"] == _GPG_KEY["fingerprint"]

    def test_invalid_owner_repo_rejected(self, runner):
        result = runner.invoke(
            main,
            gpg_command_args("get", "not-a-valid-argument"),
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert "Must be in the form of OWNER/REPO" in result.output

    def test_structural_group_does_not_advertise_inert_common_options(self, runner):
        result = runner.invoke(
            main,
            ["repos", *HERMETIC_ARGS, "gpg", "--help"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert "--output-format" not in result.output
        assert "--debug" not in result.output
        assert "--verbose" not in result.output

        misplaced = runner.invoke(
            main,
            ["repos", *HERMETIC_ARGS, "gpg", "-F", "json", "get", "my-org/my-repo"],
            catch_exceptions=False,
        )
        assert misplaced.exit_code != 0
        assert "No such option '-F'" in misplaced.output


class TestReposGpgUpload:
    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_uploads_key_and_passphrase_from_files(self, mock_create, runner, tmp_path):
        mock_create.return_value = dict(_GPG_KEY)

        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)
        passphrase_file = tmp_path / "passphrase.txt"
        passphrase_file.write_text("s3cret\n")

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--passphrase-file",
                str(passphrase_file),
            ),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        mock_create.assert_called_once_with(
            "my-org",
            "my-repo",
            gpg_private_key=_FAKE_GPG_KEY_MATERIAL,
            gpg_passphrase="s3cret",
        )

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_json_output(self, mock_create, runner, tmp_path):
        mock_create.return_value = dict(_GPG_KEY)
        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)
        passphrase_file = tmp_path / "passphrase.txt"
        passphrase_file.write_text("passphrase\n")

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--passphrase-file",
                str(passphrase_file),
                "-F",
                "json",
            ),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert document["data"]["fingerprint"] == _GPG_KEY["fingerprint"]

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_prompts_for_passphrase_when_no_file_given(
        self, mock_create, runner, tmp_path
    ):
        mock_create.return_value = dict(_GPG_KEY)

        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload", "my-org/my-repo", "--private-key-file", str(key_file)
            ),
            input="\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        mock_create.assert_called_once_with(
            "my-org",
            "my-repo",
            gpg_private_key=_FAKE_GPG_KEY_MATERIAL,
            gpg_passphrase=None,
        )

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    @pytest.mark.parametrize(
        "passphrase,expected",
        [
            (" leading-space\n", " leading-space"),
            ("trailing-space \n", "trailing-space "),
            (" \t \n", " \t "),
            ("windows-line-ending\r\n", "windows-line-ending"),
        ],
    )
    def test_passphrase_file_preserves_whitespace_and_removes_one_line_ending(
        self, mock_create, runner, tmp_path, passphrase, expected
    ):
        mock_create.return_value = dict(_GPG_KEY)
        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)
        passphrase_file = tmp_path / "passphrase.txt"
        passphrase_file.write_bytes(passphrase.encode())

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--passphrase-file",
                str(passphrase_file),
            ),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert mock_create.call_args.kwargs["gpg_passphrase"] == expected

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    @pytest.mark.parametrize(
        "passphrase", [" leading-space", "trailing-space ", " \t "]
    )
    def test_prompt_preserves_passphrase_whitespace(
        self, mock_create, runner, tmp_path, passphrase
    ):
        mock_create.return_value = dict(_GPG_KEY)
        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload", "my-org/my-repo", "--private-key-file", str(key_file)
            ),
            input=f"{passphrase}\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert mock_create.call_args.kwargs["gpg_passphrase"] == passphrase

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_private_key_stdin_requires_separate_passphrase_file(
        self, mock_create, runner
    ):
        result = runner.invoke(
            main,
            gpg_command_args("upload", "my-org/my-repo", "--private-key-file", "-"),
            input=_FAKE_GPG_KEY_MATERIAL,
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert "--passphrase-file" in result.output
        assert "Must be a file path (not '-')" in result.output
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_uploads_private_key_from_stdin_with_passphrase_file(
        self, mock_create, runner, tmp_path
    ):
        mock_create.return_value = dict(_GPG_KEY)
        passphrase_file = tmp_path / "passphrase.txt"
        passphrase_file.write_text("passphrase\n")

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                "-",
                "--passphrase-file",
                str(passphrase_file),
            ),
            input=_FAKE_GPG_KEY_MATERIAL,
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        mock_create.assert_called_once_with(
            "my-org",
            "my-repo",
            gpg_private_key=_FAKE_GPG_KEY_MATERIAL,
            gpg_passphrase="passphrase",
        )

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_rejects_using_stdin_for_both_secret_inputs(self, mock_create, runner):
        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                "-",
                "--passphrase-file",
                "-",
            ),
            input=_FAKE_GPG_KEY_MATERIAL,
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert "Must be a file path (not '-')" in result.output
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_passphrase_can_be_read_from_stdin_when_key_uses_path(
        self, mock_create, runner, tmp_path
    ):
        mock_create.return_value = dict(_GPG_KEY)
        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--passphrase-file",
                "-",
            ),
            input=" stdin-passphrase \n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert mock_create.call_args.kwargs["gpg_passphrase"] == " stdin-passphrase "

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_debug_is_rejected_without_disclosing_secrets(
        self, mock_create, runner, tmp_path
    ):
        private_key = "private-key-debug-sentinel"
        passphrase = "passphrase-debug-sentinel"
        key_file = tmp_path / "key.asc"
        key_file.write_text(private_key)
        passphrase_file = tmp_path / "passphrase.txt"
        passphrase_file.write_text(passphrase)

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--passphrase-file",
                str(passphrase_file),
                "--debug",
            ),
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert "Debug output is disabled for this command" in result.output
        for output in (result.stdout, result.stderr):
            assert private_key not in output
            assert passphrase not in output
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_empty_private_key_file_rejected(self, mock_create, runner, tmp_path):
        key_file = tmp_path / "key.asc"
        key_file.write_text("   \n")

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload", "my-org/my-repo", "--private-key-file", str(key_file)
            ),
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert "private key file is empty" in result.output
        mock_create.assert_not_called()

    def test_private_key_flag_not_accepted(self, runner):
        """Key material must never be a plain CLI value (shell-history/process-list leak)."""
        result = runner.invoke(
            main,
            gpg_command_args("upload", "my-org/my-repo", "--private-key", "sekrit"),
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert "no such option" in result.output.lower()


class TestReposGpgRegenerate:
    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_prompts_for_confirmation_and_declines(self, mock_regenerate, runner):
        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo"),
            input="N",
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert "OK, phew! Close call. :-)" in result.output
        mock_regenerate.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_yes_flag_skips_confirmation(self, mock_regenerate, runner):
        new_key = dict(_GPG_KEY, fingerprint="1111AAAA2222BBBB3333CCCC4444DDDD5555EEEE")
        mock_regenerate.return_value = new_key

        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo", "-y"),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        mock_regenerate.assert_called_once_with("my-org", "my-repo")
        assert new_key["fingerprint"] in result.output

    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_pretty_json_output(self, mock_regenerate, runner):
        mock_regenerate.return_value = dict(_GPG_KEY)

        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo", "-y", "-F", "pretty_json"),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert document["data"]["fingerprint"] == _GPG_KEY["fingerprint"]
        assert result.stdout.startswith("{\n    ")
