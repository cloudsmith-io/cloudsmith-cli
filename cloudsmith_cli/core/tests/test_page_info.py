import pytest

from ..pagination import PageInfo


@pytest.mark.parametrize(
    "headers,expected",
    [
        (
            {
                "X-Pagination-Count": "3",
                "X-Pagination-Page": "1",
                "X-Pagination-PageTotal": "2",
                "X-Pagination-PageSize": "2",
            },
            "Valid: True, Count: 3, Page: 1, Pages: 2, Size: 2, Total: 3",
        ),
        (
            {},
            "Valid: False, Count: None, Page: None, Pages: None, Size: None, "
            "Total: None",
        ),
    ],
    ids=["valid", "invalid"],
)
def test_page_info_str(headers, expected):
    assert str(PageInfo.from_headers(headers)) == expected
