"""Tests for deny policy commands."""

import json

import pytest

from ....commands.policy.deny import (
    create_deny_policy,
    delete_deny_policy,
    list_deny_policies,
    update_deny_policy,
)
from ...utils import random_bool, random_str


def create_deny_policy_config_file(
    directory, name, description, package_query_string, enabled
):
    """Create a deny policy config file in `directory` and return its path."""
    data = {
        "name": name,
        "description": description,
        "package_query_string": package_query_string,
        "enabled": enabled,
    }

    file_path = directory / "DENY-POLICY-CONFIG.json"
    file_path.write_text(str(json.dumps(data)))
    return file_path


def parse_table_from_output(output, policy_name):
    """Return a dict of deny policy properties parsed from tabular cli output."""
    headers = []
    row = []

    separator = "|"

    for line in output.split("\n"):
        if not headers and line.startswith("Name"):
            headers = [header.strip() for header in line.split(separator)]
        elif line.startswith(policy_name):
            if row:
                raise Exception("Multiple deny policies detected - expected 1.")
            row = [val.strip() for val in line.split(separator)]

    if not headers:
        raise Exception("Table not found in output!")

    if not row:
        raise Exception("No deny policies found - expected 1.")

    return dict(zip(headers, row))


def assert_output_matches_policy_config(output, config_file_path):
    """Assert that tabular output matches policy config."""
    config = json.loads(config_file_path.read_text())
    output_table = parse_table_from_output(output, policy_name=config["name"])

    # Assert that configurable values are set correctly
    assert output_table["Name"] == config["name"]
    assert output_table["Description"] == config["description"]
    assert output_table["Package Query"] == str(config["package_query_string"])
    assert output_table["Enabled"] == ("Yes" if config["enabled"] else "No")

    # We just require non-configurable values to be truthy
    assert output_table["Created"]
    assert output_table["Updated"]
    assert output_table["Identifier"]

    # Return the slug_perm in case we need it for other cli calls
    return output_table["Identifier"]


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
def test_deny_policy_commands(runner, organization, tmp_path):
    """Test CRUD operations for deny policies."""
    # Generate the deny policy configuration file.
    policy_name = random_str()

    policy_config_file_path = create_deny_policy_config_file(
        directory=tmp_path,
        name=policy_name,
        description=random_str(),
        package_query_string=f"format:python and downloads:>50 and name:{random_str()}",
        enabled=random_bool(),
    )

    # Create the deny policy
    result = runner.invoke(
        create_deny_policy,
        args=[organization, str(policy_config_file_path)],
        catch_exceptions=False,
    )
    assert (
        "Creating "
        + policy_name
        + " deny policy for the "
        + organization
        + " namespace ...OK"
        in result.output
    )
    slug_perm = assert_output_matches_policy_config(
        result.output, policy_config_file_path
    )

    # Use the cli to get the policy
    result = runner.invoke(
        list_deny_policies, args=[organization, "--page-all"], catch_exceptions=False
    )
    assert "Getting deny policies ... OK" in result.output
    assert_output_matches_policy_config(result.output, policy_config_file_path)

    # Change the values in the config file
    policy_config_file_path = create_deny_policy_config_file(
        directory=tmp_path,
        name=random_str(),
        description=random_str(),
        package_query_string=f"format:go and downloads:>15 and name:{random_str()}",
        enabled=random_bool(),
    )

    # Use the cli to update the policy
    result = runner.invoke(
        update_deny_policy,
        args=[organization, slug_perm, str(policy_config_file_path)],
        catch_exceptions=False,
    )
    assert (
        "Updating "
        + slug_perm
        + " deny policy in the "
        + organization
        + " namespace ...OK"
        in result.output
    )
    assert_output_matches_policy_config(result.output, policy_config_file_path)

    # Check that delete prompts for confirmation
    result = runner.invoke(
        delete_deny_policy,
        args=[organization, slug_perm],
        input="N",
        catch_exceptions=False,
    )
    assert (
        "Are you absolutely certain you want to delete the "
        + slug_perm
        + " deny policy from the "
        + organization
        + " namespace? [y/N]: N"
        in result.output
    )
    assert "OK, phew! Close call. :-)" in result.output

    # Then actually delete it
    result = runner.invoke(
        delete_deny_policy,
        args=[organization, slug_perm],
        input="Y",
        catch_exceptions=False,
    )
    assert (
        "Are you absolutely certain you want to delete the "
        + slug_perm
        + " deny policy from the "
        + organization
        + " namespace? [y/N]: Y"
        in result.output
    )
    assert (
        "Deleting " + slug_perm + " from the " + organization + " namespace ... OK"
        in result.output
    )
