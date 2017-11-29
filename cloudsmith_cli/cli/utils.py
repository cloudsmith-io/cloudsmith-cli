"""CLI - Utilities."""
from __future__ import absolute_import, print_function, unicode_literals

import platform

from ..core.api.version import get_version as get_api_version
from ..core.version import get_version as get_cli_version


def make_user_agent(prefix=None):
    """Get a suitable user agent for identifying the CLI process."""
    prefix = (prefix or platform.platform(terse=1)).strip().lower()
    return 'cloudsmith-cli/%(prefix)s cli:%(version)s api:%(api_version)s' % {
        'version': get_cli_version(),
        'api_version': get_api_version(),
        'prefix': prefix
    }
