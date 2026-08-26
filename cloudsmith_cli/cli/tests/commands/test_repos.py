import json
from unittest.mock import patch

import pytest

from ....core.api.exceptions import ApiException
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

    @patch("cloudsmith_cli.cli.commands.repos.stdin_is_a_terminal", return_value=True)
    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_prompts_for_passphrase_when_no_file_given(
        self, mock_create, _is_tty, runner, tmp_path
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

    @patch("cloudsmith_cli.cli.commands.repos.stdin_is_a_terminal", return_value=True)
    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    @pytest.mark.parametrize(
        "passphrase", [" leading-space", "trailing-space ", " \t "]
    )
    def test_prompt_preserves_passphrase_whitespace(
        self, mock_create, _is_tty, runner, tmp_path, passphrase
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

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_no_terminal_means_no_passphrase_rather_than_a_stall(
        self, mock_create, runner, tmp_path
    ):
        """An unattended run uploads an unencrypted key instead of blocking."""
        mock_create.return_value = dict(_GPG_KEY)
        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload", "my-org/my-repo", "--private-key-file", str(key_file)
            ),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert "GPG passphrase" not in result.output
        mock_create.assert_called_once_with(
            "my-org",
            "my-repo",
            gpg_private_key=_FAKE_GPG_KEY_MATERIAL,
            gpg_passphrase=None,
        )

    @patch("cloudsmith_cli.cli.commands.repos.stdin_is_a_terminal", return_value=True)
    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_passphrase_prompt_keeps_out_of_json_output(
        self, mock_create, _is_tty, runner, tmp_path
    ):
        """stdout must stay a single parseable document when JSON is asked for."""
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
                "-F",
                "json",
            ),
            input="\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert document["data"]["fingerprint"] == _GPG_KEY["fingerprint"]

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_dry_run_names_the_key_it_would_replace(
        self, mock_create, mock_list, runner, tmp_path
    ):
        mock_list.return_value = dict(_GPG_KEY)
        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)
        passphrase_file = tmp_path / "pass.txt"
        passphrase_file.write_text("hunter2\n")

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--passphrase-file",
                str(passphrase_file),
                "--dry-run",
            ),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert "Checking current GPG key ... OK" in result.output
        assert "Would set the GPG key" in result.output
        assert _GPG_KEY["fingerprint"] in result.output
        assert "--passphrase-file" in result.output
        assert "hunter2" not in result.output
        mock_list.assert_called_once_with("my-org", "my-repo")
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_dry_run_reports_an_unreachable_repository(
        self, mock_create, mock_list, runner, tmp_path
    ):
        """A mistyped repository or a stale token fails here, not on the real run."""
        mock_list.side_effect = ApiException(status=404, detail="Not found.")
        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--dry-run",
            ),
            catch_exceptions=False,
        )

        assert result.return_value == 404
        assert "Checking current GPG key ... ERROR" in result.output
        assert "Could not set GPG key for my-org/my-repo: not found." in result.output
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_dry_run_400_keeps_the_standard_rendering(
        self, mock_create, mock_list, runner, tmp_path
    ):
        """The dry-run pre-flight is a GET; a 400 there can't mean "bad key" either."""
        mock_list.side_effect = ApiException(
            status=400, detail="Some other validation problem."
        )
        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--dry-run",
            ),
            catch_exceptions=False,
        )

        assert result.return_value == 400
        assert "the provided key is not valid" not in result.output
        assert "Detail: Some other validation problem." in result.output
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.stdin_is_a_terminal", return_value=True)
    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_dry_run_never_asks_for_a_passphrase(
        self, mock_create, mock_list, _is_tty, runner, tmp_path
    ):
        """Nothing is sent, so nobody should have to type a real secret."""
        mock_list.return_value = dict(_GPG_KEY)
        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--dry-run",
            ),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert "GPG passphrase" not in result.output
        assert "you'd be asked for the passphrase" in result.output
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_dry_run_still_rejects_an_empty_key_file(
        self, mock_create, runner, tmp_path
    ):
        key_file = tmp_path / "key.asc"
        key_file.write_text("   \n")

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--dry-run",
            ),
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert "private key file is empty" in result.output
        mock_create.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_dry_run_json_output(self, mock_create, mock_list, runner, tmp_path):
        mock_list.return_value = dict(_GPG_KEY)
        key_file = tmp_path / "key.asc"
        key_file.write_text(_FAKE_GPG_KEY_MATERIAL)

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload",
                "my-org/my-repo",
                "--private-key-file",
                str(key_file),
                "--dry-run",
                "-F",
                "json",
            ),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert document["data"] == {
            "dry_run": True,
            "action": "set",
            "namespace": "my-org",
            "repository": "my-repo",
            "current_fingerprint": _GPG_KEY["fingerprint"],
        }
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

    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_binary_key_file_fails_cleanly(self, mock_create, runner, tmp_path):
        """A non-armored (binary) export must not surface a raw UnicodeDecodeError."""
        key_file = tmp_path / "key.gpg"
        key_file.write_bytes(bytes(range(256)))

        result = runner.invoke(
            main,
            gpg_command_args(
                "upload", "my-org/my-repo", "--private-key-file", str(key_file)
            ),
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert "UnicodeDecodeError" not in result.output
        assert "binary key export" in result.output
        assert "--armor" in result.output
        mock_create.assert_not_called()


class TestReposGpgRegenerate:
    @patch("cloudsmith_cli.cli.commands.repos.stdin_is_a_terminal", return_value=True)
    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_typed_confirmation_regenerates(self, mock_regenerate, _is_tty, runner):
        new_key = dict(_GPG_KEY, fingerprint="9999FFFF8888EEEE7777DDDD6666CCCC5555BBBB")
        mock_regenerate.return_value = new_key

        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo"),
            input="regenerate\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert "irrevocable" in result.output
        assert "Type 'regenerate' to confirm" in result.output
        mock_regenerate.assert_called_once_with("my-org", "my-repo")
        assert new_key["fingerprint"] in result.output

    @pytest.mark.parametrize("answer", ["", "n", "REGENERATE", "regen"])
    @patch("cloudsmith_cli.cli.commands.repos.stdin_is_a_terminal", return_value=True)
    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_anything_but_the_word_declines(
        self, mock_regenerate, _is_tty, runner, answer
    ):
        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo"),
            input=f"{answer}\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert "Not confirmed. No changes made." in result.output
        mock_regenerate.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_fails_fast_without_a_terminal(self, mock_regenerate, runner):
        """An unattended run must fail, not block on a question nobody can answer."""
        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo"),
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        assert "stdin is not a terminal" in result.output
        assert "-y/--yes" in result.output
        mock_regenerate.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_dry_run_names_the_key_it_would_replace(
        self, mock_regenerate, mock_list, runner
    ):
        mock_list.return_value = dict(_GPG_KEY)

        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo", "--dry-run"),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert "Checking current GPG key ... OK" in result.output
        assert "Would regenerate the GPG key" in result.output
        assert _GPG_KEY["fingerprint"] in result.output
        mock_list.assert_called_once_with("my-org", "my-repo")
        mock_regenerate.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_dry_run_reports_an_unreachable_repository(
        self, mock_regenerate, mock_list, runner
    ):
        mock_list.side_effect = ApiException(status=404, detail="Not found.")

        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo", "--dry-run"),
            catch_exceptions=False,
        )

        assert result.return_value == 404
        assert "Checking current GPG key ... ERROR" in result.output
        assert (
            "Could not regenerate GPG key for my-org/my-repo: not found."
            in result.output
        )
        mock_regenerate.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_dry_run_json_output_stays_parseable_on_error(
        self, mock_regenerate, mock_list, runner
    ):
        """The new pre-flight progress text must not land on stdout with -F json."""
        mock_list.side_effect = ApiException(status=404, detail="Not found.")

        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo", "--dry-run", "-F", "json"),
            catch_exceptions=False,
        )

        assert result.return_value == 404
        document = json.loads(result.stdout)
        assert document["detail"] == "Not found."
        assert document["meta"]["code"] == 404
        mock_regenerate.assert_not_called()

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_dry_run_json_output(self, mock_regenerate, mock_list, runner):
        mock_list.return_value = dict(_GPG_KEY)

        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo", "--dry-run", "-F", "json"),
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert document["data"] == {
            "dry_run": True,
            "action": "regenerate",
            "namespace": "my-org",
            "repository": "my-repo",
            "current_fingerprint": _GPG_KEY["fingerprint"],
        }
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


class TestReposGpgErrorVoice:
    """The failures a person can act on read as one plain sentence."""

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    def test_get_not_found(self, mock_list, runner):
        mock_list.side_effect = ApiException(status=404, detail="Not found.")

        result = runner.invoke(
            main,
            gpg_command_args("get", "my-org/my-repo"),
            catch_exceptions=False,
        )

        # AliasGroup.main runs click with standalone_mode=False, so the status
        # comes back as the command's return value rather than an exit code.
        assert result.return_value == 404
        assert "Could not get GPG key for my-org/my-repo: not found." in result.output
        assert "status: 404" not in result.output

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (
                400,
                "Could not set GPG key for my-org/my-repo: the provided key is not "
                "valid.",
            ),
            (
                402,
                "Could not set GPG key for my-org/my-repo: custom GPG keys require a "
                "paid plan.",
            ),
            (404, "Could not set GPG key for my-org/my-repo: not found."),
        ],
    )
    @patch("cloudsmith_cli.cli.commands.repos.api.create_repo_gpg_key")
    def test_upload_failures(self, mock_create, runner, tmp_path, status, expected):
        mock_create.side_effect = ApiException(status=status, detail="Whatever.")
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

        assert result.return_value == status
        assert expected in result.output
        assert "Whatever." not in result.output

    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_regenerate_failure(self, mock_regenerate, runner):
        mock_regenerate.side_effect = ApiException(
            status=402, detail="Custom GPG keys are not active; upgrade your account!"
        )

        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo", "-y"),
            catch_exceptions=False,
        )

        assert result.return_value == 402
        assert (
            "Could not regenerate GPG key for my-org/my-repo: custom GPG keys "
            "require a paid plan." in result.output
        )

    @patch("cloudsmith_cli.cli.commands.repos.api.regenerate_repo_gpg_key")
    def test_regenerate_400_keeps_the_standard_rendering(self, mock_regenerate, runner):
        """No key is sent by 'regenerate', so a 400 can't mean "bad key"."""
        mock_regenerate.side_effect = ApiException(
            status=400, detail="Some other validation problem."
        )

        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo", "-y"),
            catch_exceptions=False,
        )

        assert result.return_value == 400
        assert "the provided key is not valid" not in result.output
        assert "Detail: Some other validation problem." in result.output

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    def test_regenerate_dry_run_400_keeps_the_standard_rendering(
        self, mock_list, runner
    ):
        """The dry-run pre-flight is a GET; a 400 there can't mean "bad key" either."""
        mock_list.side_effect = ApiException(
            status=400, detail="Some other validation problem."
        )

        result = runner.invoke(
            main,
            gpg_command_args("regenerate", "my-org/my-repo", "--dry-run"),
            catch_exceptions=False,
        )

        assert result.return_value == 400
        assert "the provided key is not valid" not in result.output
        assert "Detail: Some other validation problem." in result.output

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    def test_unmapped_status_keeps_the_standard_rendering(self, mock_list, runner):
        mock_list.side_effect = ApiException(status=500, detail="Boom.")

        result = runner.invoke(
            main,
            gpg_command_args("get", "my-org/my-repo"),
            catch_exceptions=False,
        )

        assert result.return_value == 500
        assert "Failed to get the repository GPG key!" in result.output
        assert "Detail: Boom." in result.output

    @patch("cloudsmith_cli.cli.commands.repos.api.list_repo_gpg_key")
    def test_json_output_keeps_the_full_error_envelope(self, mock_list, runner):
        mock_list.side_effect = ApiException(status=404, detail="Not found.")

        result = runner.invoke(
            main,
            gpg_command_args("get", "my-org/my-repo", "-F", "json"),
            catch_exceptions=False,
        )

        assert result.return_value == 404
        document = json.loads(result.stdout)
        assert document["detail"] == "Not found."
        assert document["meta"]["code"] == 404
