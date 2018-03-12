"""CLI - Utilities."""
from __future__ import absolute_import, print_function, unicode_literals

import platform

import click

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


def print_list_info(num_results, page_info=None, suffix=None):
    """Print list info, with pagination, for user display."""
    num_results_fg = 'green' if num_results else 'red'
    num_results_text = click.style(str(num_results), fg=num_results_fg)

    if page_info and page_info.is_valid:
        page_range = page_info.calculate_range(num_results)
        page_info_text = (
            'page: %(page)s/%(page_total)s, page size: %(page_size)s' % {
                'page': click.style(str(page_info.page), bold=True),
                'page_size': click.style(str(page_info.page_size), bold=True),
                'page_total': click.style(
                    str(page_info.page_total), bold=True
                ),
            }
        )
        range_results_text = (
            '%(from)s-%(to)s (%(num_results)s) of %(total)s' % {
                'num_results': num_results_text,
                'from': click.style(str(page_range[0]), fg=num_results_fg),
                'to': click.style(str(page_range[1]), fg=num_results_fg),
                'total': click.style(str(page_info.count), fg=num_results_fg)
            }
        )
    else:
        page_info_text = ''
        range_results_text = num_results_text

    click.secho(
        'Results: %(range_results)s %(suffix)s%(page_info)s' % {
            'range_results': range_results_text,
            'page_info': ' (%s)' % page_info_text if page_info_text else '',
            'suffix': suffix or 'item(s)',
        }
    )
