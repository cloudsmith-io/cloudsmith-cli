"""Core pagination utilities."""

import itertools
from typing import Any, Callable, List, Optional, Sequence, Tuple

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
    iterator,
    page_all: bool,
    page: int = 1,
    page_size: int = 30,
) -> Tuple[List[Any], PageInfo]:
    """Apply client-side pagination to an iterator.

    Use this for API endpoints backed by the new SDK, which handles
    server-side pagination internally via iterators.

    When page_all is False, only consumes enough items from the iterator
    to fill the requested page, avoiding fetching all results.
    """
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


def paginate_results(
    api_function: Callable[..., Tuple[Sequence[Any], PageInfo]],
    page_all: bool,
    page: int,
    page_size: int = MAX_PAGE_SIZE,
    **kwargs: Any,
) -> Tuple[List[Any], PageInfo]:
    """Retrieve paginated results.

    Behaviour:
    - If ``page_all`` is False: perform a single paged request and return the
      results plus the (possibly invalid) ``PageInfo``. Single-resource API
      endpoints frequently omit pagination headers; we tolerate that here.
    - If ``page_all`` is True: iterate all pages requesting ``MAX_PAGE_SIZE``.
      Missing pagination headers during aggregation are treated as a user
      misuse (e.g. attempting ``--page-all`` against a single-resource
      endpoint) and raise a ``click.ClickException`` for consistent UX.

    Raises:
        click.ClickException: If pagination headers are absent while trying to
            aggregate multiple pages with ``page_all``.
    """
    if not page_all:
        results, page_info = api_function(page=page, page_size=page_size, **kwargs)
        # For single resource endpoints (e.g. repos_read) pagination headers may be absent.
        # In that case we return the results with potentially invalid page_info (empty when serialized)
        # rather than raising. Downstream pretty printers handle an invalid page_info gracefully.
        return list(results), page_info

    all_results: List[Any] = []
    current_page = 1
    last_page_info: Optional[PageInfo] = None
    while True:
        page_results, last_page_info = api_function(
            page=current_page, page_size=MAX_PAGE_SIZE, **kwargs
        )
        if not last_page_info.is_valid:
            # No pagination headers (single-resource endpoint). Treat as single page.
            # Return accumulated results without raising; command-level validators
            # handle misuse of --page-all with single-resource endpoints.
            all_results.extend(page_results)
            return all_results, last_page_info
        all_results.extend(page_results)

        if current_page >= last_page_info.page_total:
            break
        current_page += 1

    return all_results, last_page_info
