import json

import pytest

from ...commands.repos import create, delete, get, update
from ..utils import random_str


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
    seperator = "|"
    column_headers = []
    row_values = []

    for line in output.split("\n"):
        if seperator in line:
            raw_values = [raw_value.strip() for raw_value in line.split(seperator)]
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
