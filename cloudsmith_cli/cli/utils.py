# -*- coding: utf-8 -*-
"""CLI - Utilities."""
from __future__ import absolute_import, print_function, unicode_literals

import json
import platform
from contextlib import contextmanager

import click
import six
from click_spinner import spinner

from ..core.api.version import get_version as get_api_version
from ..core.version import get_version as get_cli_version
from .table import make_table


def make_user_agent(prefix=None):
    """Get a suitable user agent for identifying the CLI process."""
    prefix = (prefix or platform.platform(terse=1)).strip().lower()
    return "cloudsmith-cli/%(prefix)s cli:%(version)s api:%(api_version)s" % {
        "version": get_cli_version(),
        "api_version": get_api_version(),
        "prefix": prefix,
    }


def pretty_print_list_info(num_results, page_info=None, suffix=None):
    """Pretty print list info, with pagination, for user display."""
    num_results_fg = "green" if num_results else "red"
    num_results_text = click.style(str(num_results), fg=num_results_fg)

    if page_info and page_info.is_valid:
        page_range = page_info.calculate_range(num_results)
        page_info_text = "page: %(page)s/%(page_total)s, page size: %(page_size)s" % {
            "page": click.style(str(page_info.page), bold=True),
            "page_size": click.style(str(page_info.page_size), bold=True),
            "page_total": click.style(str(page_info.page_total), bold=True),
        }
        range_results_text = "%(from)s-%(to)s (%(num_results)s) of %(total)s" % {
            "num_results": num_results_text,
            "from": click.style(str(page_range[0]), fg=num_results_fg),
            "to": click.style(str(page_range[1]), fg=num_results_fg),
            "total": click.style(str(page_info.count), fg=num_results_fg),
        }
    else:
        page_info_text = ""
        range_results_text = num_results_text

    click.secho(
        "Results: %(range_results)s %(suffix)s%(page_info)s"
        % {
            "range_results": range_results_text,
            "page_info": " (%s)" % page_info_text if page_info_text else "",
            "suffix": suffix or "item(s)",
        }
    )


def pretty_print_table(headers, rows, title=None):
    """Pretty print a table from headers and rows."""
    table = make_table(headers=headers, rows=rows)

    def pretty_print_row(styled, plain):
        """Pretty print a row."""
        click.secho(
            " | ".join(
                v + " " * (table.column_widths[k] - len(plain[k]))
                for k, v in enumerate(styled)
            )
        )

    if title:
        click.secho(title, fg="white", bold=True)
        click.secho("-" * 80, fg="yellow")

    pretty_print_row(table.headers, table.plain_headers)
    for k, row in enumerate(table.rows):
        pretty_print_row(row, table.plain_rows[k])


def print_rate_limit_info(opts, rate_info):
    """Tell the user when we're being rate limited."""
    if not rate_info:
        return

    show_info = (
        opts.always_show_rate_limit or rate_info.interval > opts.rate_limit_warning
    )

    if not show_info:
        return

    click.echo(err=True)
    click.secho(
        "Throttling (rate limited) for: %(throttle)s seconds ... "
        % {"throttle": click.style(six.text_type(rate_info.interval), reverse=True)},
        err=True,
        reset=False,
    )


def maybe_print_as_json(opts, data, page_info=None):
    """Maybe print data as JSON."""
    if opts.output not in ("json", "pretty_json"):
        return False

    # Attempt to convert the data to dicts (usually from API objects)
    try:
        data = data.to_dict()
    except AttributeError:
        pass

    if isinstance(data, list):
        for k, item in enumerate(data):
            try:
                data[k] = item.to_dict()
            except AttributeError:
                pass

    root = {"data": data}

    if page_info is not None and page_info.is_valid:
        meta = root["meta"] = {}
        meta["pagination"] = page_info.as_dict(num_results=len(data))

    try:
        if opts.output == "pretty_json":
            dump = json.dumps(root, indent=4, sort_keys=True)
        else:
            dump = json.dumps(root, sort_keys=True)
    except (TypeError, ValueError) as e:
        click.secho(
            "Failed to convert to JSON: %(err)s" % {"err": str(e)}, fg="red", err=True
        )
        return True

    click.echo(dump)
    return True


def confirm_operation(prompt, prefix=None, assume_yes=False, err=False):
    """Prompt the user for confirmation for dangerous actions."""
    if assume_yes:
        return True

    prefix = prefix or click.style(
        "Are you %s certain you want to" % (click.style("absolutely", bold=True))
    )

    prompt = "%(prefix)s %(prompt)s?" % {"prefix": prefix, "prompt": prompt}

    if click.confirm(prompt, err=err):
        return True

    click.echo(err=err)
    click.secho("OK, phew! Close call. :-)", fg="green", err=err)
    return False


@contextmanager
def maybe_spinner(opts):
    """Only activate the spinner if not in debug mode."""
    if opts.debug:
        # No spinner
        yield
    else:
        with spinner() as spin:
            yield spin
