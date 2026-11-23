"""Commands that read a JSON config file reject invalid files with a usage error."""

from unittest.mock import patch

import pytest

from ...commands.main import main

HERMETIC_ARGS = ["--api-key", "fake-api-key"]

# Each entry: (command path, positional arguments before the config file,
# param hint shown in the error, the core API function the command would call).
CONFIG_FILE_COMMANDS = [
    (["repos", "create"], ["your-org"], "REPO_CONFIG_FILE", "repos.create_repo"),
    (
        ["repos", "update"],
        ["your-org/your-repo"],
        "REPO_CONFIG_FILE",
        "repos.update_repo",
    ),
    (
        ["upstream", "npm", "create"],
        ["your-org/your-repo"],
        "UPSTREAM_CONFIG_FILE",
        "upstreams.create_upstream",
    ),
    (
        ["upstream", "npm", "update"],
        ["your-org/your-repo/abc123"],
        "UPSTREAM_CONFIG_FILE",
        "upstreams.update_upstream",
    ),
    (
        ["policy", "deny", "create"],
        ["your-org"],
        "POLICY_CONFIG_FILE",
        "orgs.create_deny_policy",
    ),
    (
        ["policy", "deny", "update"],
        ["your-org", "abc123"],
        "POLICY_CONFIG_FILE",
        "orgs.update_deny_policy",
    ),
    (
        ["policy", "license", "create"],
        ["your-org"],
        "POLICY_CONFIG_FILE",
        "orgs.create_license_policy",
    ),
    (
        ["policy", "license", "update"],
        ["your-org", "abc123"],
        "POLICY_CONFIG_FILE",
        "orgs.update_license_policy",
    ),
    (
        ["policy", "vulnerability", "create"],
        ["your-org"],
        "POLICY_CONFIG_FILE",
        "orgs.create_vulnerability_policy",
    ),
    (
        ["policy", "vulnerability", "update"],
        ["your-org", "abc123"],
        "POLICY_CONFIG_FILE",
        "orgs.update_vulnerability_policy",
    ),
]

INVALID_DOCUMENTS = [
    pytest.param(
        '{\n  "name": "your-repo",\n  "slug": "your-repo",\n}\n',
        "Invalid JSON:",
        id="trailing-comma",
    ),
    pytest.param("", "Invalid JSON:", id="empty"),
    pytest.param(b"\xff\xfe\x00", "Invalid JSON:", id="not-utf8"),
    pytest.param('["your-repo"]', "must contain a JSON object", id="not-an-object"),
]


@pytest.mark.usefixtures("set_fake_api_host_env_var")
@pytest.mark.parametrize("command,args,param_hint,api_function", CONFIG_FILE_COMMANDS)
@pytest.mark.parametrize("document,message", INVALID_DOCUMENTS)
def test_invalid_config_file_is_a_usage_error(
    runner, tmp_path, command, args, param_hint, api_function, document, message
):
    config_file = tmp_path / "config.json"
    if isinstance(document, bytes):
        config_file.write_bytes(document)
    else:
        config_file.write_text(document)

    with patch(f"cloudsmith_cli.core.api.{api_function}") as mock_api:
        result = runner.invoke(
            main, [*command, *HERMETIC_ARGS, *args, str(config_file)]
        )

    assert result.exit_code == 2, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert f"Invalid value for '{param_hint}'" in result.output
    assert message in result.output
    mock_api.assert_not_called()
