import pytest

from ..pagination import PageInfo


def make_page_info(page):
    return PageInfo.from_headers(
        {
            "X-Pagination-Count": "3",
            "X-Pagination-Page": str(page),
            "X-Pagination-PageSize": "2",
            "X-Pagination-PageTotal": "2",
        }
    )


@pytest.mark.parametrize(
    ("page", "num_results", "expected"),
    [
        (1, 2, {"page_results_len": 2, "page_results_from": 1, "page_results_to": 2}),
        (2, 1, {"page_results_len": 1, "page_results_from": 3, "page_results_to": 3}),
        (1, 0, {"page_results_len": 0, "page_results_from": 0, "page_results_to": 0}),
    ],
    ids=["full_page", "partial_last_page", "zero_results"],
)
def test_as_dict_reports_page_results(page, num_results, expected):
    data = make_page_info(page).as_dict(num_results=num_results)

    assert {key: data[key] for key in expected} == expected


def test_from_headers_treats_non_integer_value_as_missing():
    page_info = PageInfo.from_headers(
        {
            "X-Pagination-Count": "many",
            "X-Pagination-Page": "1",
            "X-Pagination-PageSize": "2",
            "X-Pagination-PageTotal": "2",
        }
    )

    assert page_info.count is None
    assert not page_info.is_valid
