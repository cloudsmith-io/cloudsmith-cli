"""Core pagination utilities."""

import itertools
from typing import Any, List, Tuple

MAX_PAGE_SIZE = 500


class PageInfo:
    """Data for pagination results."""

    count = None
    page = None
    page_size = None
    page_total = None

    def __str__(self):
        """Get page information as text."""
        data = self.as_dict()
        data["valid"] = self.is_valid
        return (
            "Valid: %(valid)s, Count: %(count)s, Page: %(page)s, "
            "Size: %(page_size)s, Total: %(results_total)s" % data
        )

    def calculate_range(self, num_results):
        """Calculate beginning and end of page range for results."""
        if self.is_valid and num_results:
            from_range = (self.page - 1) * self.page_size
            to_range = from_range + num_results
            from_range += 1
        else:
            from_range = 0
            to_range = 0

        return from_range, to_range

    def as_dict(self, num_results=None):
        """Create PageInfo from a dictionary."""
        if not self.is_valid:
            return {}

        data = {
            "results_total": self.count,
            "page": self.page,
            "page_size": self.page_size,
            "page_max": self.page_total,
        }

        if num_results is not None:
            from_range, to_range = self.calculate_range(num_results)
            data["page_results_len"] = to_range - from_range
            data["page_results_from"] = from_range
            data["page_results_to"] = to_range

        return data

    @property
    def is_valid(self):
        """Check if the page information is valid."""
        return all(
            x is not None
            for x in (self.count, self.page, self.page_size, self.page_total)
        )

    @classmethod
    def from_page_iterator(cls, iterator, page=None):
        """Create PageInfo from an SDK PageIterator."""

        def _get_int_attr(obj, name):
            value = getattr(obj, name, None)
            return value if isinstance(value, int) else None

        info = PageInfo()
        info.count = _get_int_attr(iterator, "count")
        info.page = page or _get_int_attr(iterator, "current_page")
        info.page_size = _get_int_attr(iterator, "page_size")
        info.page_total = _get_int_attr(iterator, "page_total")
        return info


def paginate_iterator(
    make_iterator,
    page_all: bool,
    page: int = 1,
    page_size: int = 30,
) -> Tuple[List[Any], PageInfo]:
    """Apply client-side pagination to an iterator.

    Use this for API endpoints backed by the new SDK, which handles
    server-side pagination internally via iterators.

    Args:
        make_iterator: Callable that accepts a page_size int and returns an
            iterator. The page_size passed will be resolved internally
            (MAX_PAGE_SIZE when page_size <= 0).
        page_all: If True, consume all results from the iterator.
        page: 1-based page number to return.
        page_size: Number of items per page. Values <= 0 are treated as
            "use server max".
    """
    api_page_size = page_size if page_size > 0 else MAX_PAGE_SIZE
    iterator = make_iterator(api_page_size)

    if page_all:
        all_results = list(iterator)
        page_info = PageInfo.from_page_iterator(iterator, page=1)
        page_info.count = page_info.count or len(all_results)
        page_info.page_size = MAX_PAGE_SIZE
        page_info.page_total = (
            -(-page_info.count // MAX_PAGE_SIZE) if page_info.count else 0
        )
        return all_results, page_info

    start = (page - 1) * page_size
    page_results = list(itertools.islice(iterator, start, start + page_size))
    page_info = PageInfo.from_page_iterator(iterator, page=page)
    if page_info.count is not None:
        page_info.page_size = page_size

    return page_results, page_info
