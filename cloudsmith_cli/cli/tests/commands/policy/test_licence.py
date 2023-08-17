import json

import pytest

from ....commands.policy.license import create, delete, ls, update
from ...utils import random_bool, random_str


def create_license_policy_config_file(
    directory,
    name,
    description,
    allow_unknown_licenses,
    package_query_string,
    spdx_identifiers,
    on_violation_quarantine,
):
    """Create a license policy config file in `directory` and return its path."""

    data = {
        "name": name,
        "description": description,
        "spdx_identifiers": list(spdx_identifiers),
        "allow_unknown_licenses": allow_unknown_licenses,
        "package_query_string": package_query_string,
        "on_violation_quarantine": on_violation_quarantine,
    }

    file_path = directory / "LICENSE-POLICY-CONFIG.json"
    file_path.write_text(str(json.dumps(data)))
    return file_path


def parse_table_from_output(output, policy_name):
    """Return a dict of license policy properties parsed from tabular cli output."""

    headers = []
    row = []

    separator = "|"

    for line in output.split("\n"):
        if not headers and line.startswith("Name"):
            headers = [header.strip() for header in line.split(separator)]
        elif line.startswith(policy_name):
            if row:
                raise Exception("Multiple license policies detected - expected 1.")
            row = [val.strip() for val in line.split(separator)]

    if not headers:
        raise Exception("Table not found in output!")

    if not row:
        raise Exception("No license policies found - expected 1.")

    return dict(zip(headers, row))


def assert_output_matches_policy_config(output, config_file_path):
    """Assert that tabular output from a command invocation matches policy config."""

    config = json.loads(config_file_path.read_text())
    output_table = parse_table_from_output(output, policy_name=config["name"])

    # Assert that configurable values are set correctly
    assert output_table["Name"] == config["name"]
    assert output_table["Description"] == config["description"]
    assert output_table["SPDX Identifiers"] == str(config["spdx_identifiers"])
    assert (
        output_table["Allow Unknown Licenses"]
        == str(config["allow_unknown_licenses"]).lower()
    )
    assert (
        output_table["Quarantine On Violation"]
        == str(config["on_violation_quarantine"]).lower()
    )
    assert output_table["Package Query"] == str(config["package_query_string"])

    # We just require non-configurable values to be truthy
    assert output_table["Created"]
    assert output_table["Updated"]
    assert output_table["Identifier"]

    # Return the slug_perm in case we need it for other cli calls
    return output_table["Identifier"]


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
def test_license_policy_commands(runner, organization, tmp_path):
    """Test CRUD operations for license policies."""

    # Generate the license policy configuration file.
    policy_name = random_str()

    policy_config_file_path = create_license_policy_config_file(
        directory=tmp_path,
        name=policy_name,
        description=random_str(),
        allow_unknown_licenses=random_bool(),
        on_violation_quarantine=random_bool(),
        package_query_string="format:python AND downloads:>50",
        spdx_identifiers=["Apache-2.0"],
    )

    # Create the license policy
    result = runner.invoke(
        create,
        args=[organization, str(policy_config_file_path)],
        catch_exceptions=False,
    )
    assert (
        "Creating " + policy_name + " license policy for the cloudsmith namespace ...OK"
        in result.output
    )
    slug_perm = assert_output_matches_policy_config(
        result.output, policy_config_file_path
    )

    # Use the cli to get the policy
    result = runner.invoke(ls, args=[organization], catch_exceptions=False)
    assert "Getting license policies ... OK" in result.output
    assert_output_matches_policy_config(result.output, policy_config_file_path)

    # Change the values in the config file
    policy_config_file_path = create_license_policy_config_file(
        directory=tmp_path,
        name=random_str(),
        description=random_str(),
        allow_unknown_licenses=random_bool(),
        on_violation_quarantine=random_bool(),
        package_query_string="format:go AND downloads:>15",
        spdx_identifiers=["Apache-1.0"],
    )

    # Use the cli to update the policy
    result = runner.invoke(
        update,
        args=[organization, slug_perm, str(policy_config_file_path)],
        catch_exceptions=False,
    )
    assert (
        "Updating " + slug_perm + " license policy in the cloudsmith namespace ...OK"
        in result.output
    )
    assert_output_matches_policy_config(result.output, policy_config_file_path)

    # Check that delete prompts for confirmation
    result = runner.invoke(
        delete, args=[organization, slug_perm], input="N", catch_exceptions=False
    )
    assert (
        "Are you absolutely certain you want to delete the "
        + slug_perm
        + " license policy from the cloudsmith namespace? [y/N]: N"
        in result.output
    )
    assert "OK, phew! Close call. :-)" in result.output

    # Then actually delete it
    result = runner.invoke(
        delete, args=[organization, slug_perm], input="Y", catch_exceptions=False
    )
    assert (
        "Are you absolutely certain you want to delete the "
        + slug_perm
        + " license policy from the cloudsmith namespace? [y/N]: Y"
        in result.output
    )
    assert (
        "Deleting " + slug_perm + " from the cloudsmith namespace ... OK"
        in result.output
    )
