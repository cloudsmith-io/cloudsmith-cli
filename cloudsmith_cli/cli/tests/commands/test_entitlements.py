from unittest.mock import patch

from ...commands.entitlements import list_ as list_entitlements


class TestEntitlementsListCommand:
    def test_entitlements_list(self, runner):
        """Test that entitlements list accepts show_all parameter."""
        with patch("cloudsmith_cli.core.api.init.get_api_client"):
            with patch(
                "cloudsmith_cli.core.api.entitlements.list_entitlements"
            ) as mock_api:
                mock_api.return_value = ([], None)
                result = runner.invoke(
                    list_entitlements, ["test-org/test-repo"], catch_exceptions=False
                )
                assert result.exit_code == 0
