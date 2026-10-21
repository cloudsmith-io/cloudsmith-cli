import pytest

from ...commands.main import main


@pytest.mark.parametrize(
    "command,config,message",
    [
        (["upstream", "npm", "create", "ws/repo"], "{}", "UPSTREAM_CONFIG_FILE"),
        (["repositories", "create", "ws"], "{}", "REPO_CONFIG_FILE"),
        (["policy", "deny", "create", "ws"], "{}", "POLICY_CONFIG_FILE"),
        (["policy", "license", "create", "ws"], "{}", "POLICY_CONFIG_FILE"),
        (
            ["policy", "license", "create", "ws"],
            '{"name": "licences"}',
            "SPDX Identifiers is a required field",
        ),
        (["policy", "vulnerability", "create", "ws"], "{}", "POLICY_CONFIG_FILE"),
    ],
)
def test_missing_config_field_is_a_usage_error(
    runner, tmp_path, command, config, message
):
    config_file = tmp_path / "config.json"
    config_file.write_text(config)

    result = runner.invoke(
        main,
        [
            *command,
            str(config_file),
            "--config-file",
            str(tmp_path),
            "--credentials-file",
            str(tmp_path),
            "--api-key",
            "fake-api-key",
        ],
    )

    assert result.exit_code == 2
    assert message in result.stderr
    assert "Traceback" not in result.output
