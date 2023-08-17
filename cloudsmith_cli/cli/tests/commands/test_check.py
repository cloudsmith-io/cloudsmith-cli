from unittest.mock import patch

import pytest

from ....cli.commands.check import check
from ....cli.tests.utils import random_str


@pytest.mark.usefixtures("set_api_host_env_var")
class TestCheckServiceCommand:
    @pytest.mark.parametrize(
        "service_version,api_binding_version",
        [
            ("1.0.0", "1.0.0"),
            ("2.0.0", "1.0.0"),
            ("1.0.0", "2.0.0"),
        ],
    )
    def test_check_service_command_output(
        self, runner, api_host, service_version, api_binding_version
    ):
        """Unit test the command output given different combinations of service/binding version."""
        service_status = random_str()

        with patch(
            "cloudsmith_cli.cli.commands.check.get_status"
        ) as get_status_mock, patch(
            "cloudsmith_cli.cli.commands.check.get_api_version_info"
        ) as get_version_mock:
            get_status_mock.return_value = (service_status, service_version)
            get_version_mock.return_value = api_binding_version
            result = runner.invoke(check, args="service", catch_exceptions=False)

        output = result.output.splitlines()

        get_status_mock.assert_called_once()
        get_version_mock.assert_called_once()

        assert output[0] == "Retrieving service status ... OK"
        assert output[1] == ""
        assert output[2] == f"The service endpoint is: {api_host}"
        assert output[3] == f"The service status is:   {service_status}"
        assert (
            output[4]
            == f"The service version is:  {service_version} ({'maybe out-of-date' if api_binding_version < service_version else 'up-to-date'})"
        )
        assert output[5] == ""
        assert output[6] == (
            f"The API library used by this CLI tool is built against service version: {api_binding_version}"
            if api_binding_version < service_version
            else "The API library used by this CLI tool seems to be up-to-date."
        )

    def test_check_service_command(self, runner, api_host):
        """Integration test the `cloudsmith check service` command (actually hit the API)."""
        result = runner.invoke(check, args="service", catch_exceptions=False)
        assert result.exit_code == 0

        output = result.output.splitlines()

        assert output[0] == "Retrieving service status ... OK"
        assert output[1] == ""
        assert output[2] == f"The service endpoint is: {api_host}"
        assert output[3].startswith("The service status is:")
        assert output[4].startswith("The service version is:")
        assert output[5] == ""
        assert (
            output[6].startswith(
                "The API library used by this CLI tool is built against service version:"
            )
            or output[6]
            == "The API library used by this CLI tool seems to be up-to-date."
        )
