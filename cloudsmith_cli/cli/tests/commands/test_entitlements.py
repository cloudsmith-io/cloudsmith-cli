import pytest

from ....core.pagination import PageInfo
from ...commands.entitlements import list_ as list_entitlements
from ...commands.entitlements import print_entitlements
from ...config import Options


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
def test_entitlements_list_with_show_all(runner, organization, tmp_repository):
    """Test listing entitlements with --show-all flag."""
    org_repo = f"{organization}/{tmp_repository['slug']}"

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


def _make_entitlement(name):
    return {
        "name": name,
        "user": None,
        "token": "abc123",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "slug_perm": "slugperm",
    }


def _make_page_info(count, page, page_size, page_total):
    page_info = PageInfo()
    page_info.count = count
    page_info.page = page
    page_info.page_size = page_size
    page_info.page_total = page_total
    return page_info


def test_print_entitlements_includes_pagination_info(capsys):
    """Paged output includes the range/page details like other list commands."""
    opts = Options()
    opts.output = "pretty"
    data = [_make_entitlement(f"token-{i}") for i in range(30)]
    page_info = _make_page_info(count=120, page=1, page_size=30, page_total=4)

    print_entitlements(opts=opts, data=data, page_info=page_info)

    output = capsys.readouterr().out
    assert (
        "Results: 1-30 (30) of 120 entitlements visible "
        "(page: 1/4, page size: 30)" in output
    )


def test_print_entitlements_page_all_shows_retrieved_total(capsys):
    """--page-all output reports the retrieved total instead of page details."""
    opts = Options()
    opts.output = "pretty"
    data = [_make_entitlement(f"token-{i}") for i in range(120)]
    page_info = _make_page_info(count=120, page=1, page_size=500, page_total=1)

    print_entitlements(opts=opts, data=data, page_info=page_info, page_all=True)

    output = capsys.readouterr().out
    assert "Results: 120 entitlements retrieved" in output
    assert "page size" not in output
