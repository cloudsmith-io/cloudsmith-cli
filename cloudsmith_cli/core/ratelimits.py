"""Core rate limit utilities."""
from __future__ import absolute_import, print_function, unicode_literals

import datetime

from future.utils import python_2_unicode_compatible


@python_2_unicode_compatible
class RateLimitsInfo(object):
    """Data for rate limits."""

    interval = None
    limit = None
    remaining = None
    reset = None
    throttled = None

    def __str__(self):
        """Get rate limit information as text."""
        return (
            'Throttled: %(throttled)s, Remaining: %(remaining)d/%(limit)d, '
            'Interval: %(interval)f, Reset: %(reset)s' % {
                'throttled': 'Yes' if self.throttled else 'No',
                'remaining': self.remaining,
                'limit': self.limit,
                'interval': self.interval,
                'reset': self.reset
            }
        )

    @classmethod
    def from_dict(cls, data):
        info = RateLimitsInfo()

        if 'interval' in data:
            info.interval = data['interval']
        if 'limit' in data:
            info.limit = data['limit']
        if 'remaining' in data:
            info.remaining = data['remaining']
        if 'reset' in data:
            info.reset = datetime.datetime.utcfromtimestamp(data['reset'])
        if 'throtted' in data:
            info.throttled = data['throttled']

        return info
