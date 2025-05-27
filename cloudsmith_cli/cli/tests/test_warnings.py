from cloudsmith_cli.cli.warnings import (
    ApiAuthenticationWarning,
    CliWarnings,
    ConfigLoadWarning,
    ProfileNotFoundWarning,
)


class TestWarnings:
    def test_warning_append(self):
        """Test appending warnings to the CliWarnings."""

        config_load_warning_1 = ConfigLoadWarning({"test_path_1": False})
        config_load_warning_2 = ConfigLoadWarning({"test_path_2": True})
        profile_load_warning = ProfileNotFoundWarning(
            {"test_path_1": False}, "test_profile"
        )
        api_authentication_warning = ApiAuthenticationWarning("test.cloudsmith.io")
        cli_warnings = CliWarnings()
        cli_warnings.append(config_load_warning_1)
        cli_warnings.append(config_load_warning_2)
        cli_warnings.append(profile_load_warning)
        cli_warnings.append(profile_load_warning)
        cli_warnings.append(api_authentication_warning)
        assert len(cli_warnings) == 5
        assert len(cli_warnings.__dedupe__()) == 4
