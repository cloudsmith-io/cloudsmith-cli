import pytest

from ..utils import maybe_truncate_list, maybe_truncate_string


@pytest.mark.parametrize(
    "data,max_length,expected_len",
    [(range(0, 1), 5, 1), (range(0, 5), 5, 5), (list(), 5, 0), (None, 5, 0)],
)
def test_maybe_truncate_list(data, max_length, expected_len):
    truncated = maybe_truncate_list(data, max_length)

    if data is None:
        assert truncated is None
    else:
        assert len(truncated) == expected_len

    if expected_len > max_length:
        assert truncated[:-1] == "..."


@pytest.mark.parametrize(
    "data,max_length,expected_len",
    [("test", 10, 4), ("test" * 5, 10, 10), ("", 10, 0), (None, 10, 0)],
)
def test_maybe_truncate_string(data, max_length, expected_len):
    truncated = maybe_truncate_string(data, max_length)

    if data is None:
        assert truncated is None
    else:
        assert len(truncated) == expected_len

    if expected_len > max_length:
        assert truncated[-4:-1] == "..."
