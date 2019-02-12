# -*- coding: utf-8 -*-
"""Core pagination utilities."""
from __future__ import absolute_import, print_function, unicode_literals

from future.utils import python_2_unicode_compatible


@python_2_unicode_compatible
class PageInfo(object):
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
    def from_headers(cls, headers):
        """Create PageInfo from HTTP headers."""
        info = PageInfo()

        if "X-Pagination-Count" in headers:
            info.count = int(headers["X-Pagination-Count"])
        if "X-Pagination-Page" in headers:
            info.page = int(headers["X-Pagination-Page"])
        if "X-Pagination-PageSize" in headers:
            info.page_size = int(headers["X-Pagination-PageSize"])
        if "X-Pagination-PageTotal" in headers:
            info.page_total = int(headers["X-Pagination-PageTotal"])

        return info
