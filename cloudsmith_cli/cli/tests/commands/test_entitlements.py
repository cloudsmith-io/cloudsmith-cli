import pytest

from ...commands.entitlements import list_ as list_entitlements


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
def test_entitlements_list_with_show_all(runner, organization, tmp_repository):
    """Test listing entitlements with --show-all flag."""
    org_repo = f'{organization}/{tmp_repository["slug"]}'

    # Minimal show-all success (no pagination args besides flag)
    result = runner.invoke(
        list_entitlements,
        args=[org_repo, "--show-all"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Getting list of entitlements" in result.output
    assert "OK" in result.output
    assert "Invalid value for '--show-all'" not in result.output
