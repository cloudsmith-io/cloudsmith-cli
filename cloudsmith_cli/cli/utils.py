"""CLI - Utilities."""
import json
import platform
from contextlib import contextmanager
from datetime import date, datetime

import click
from click_spinner import spinner

from ..core.api.version import get_version as get_api_version
from ..core.version import get_version as get_cli_version
from .table import make_table


def make_user_agent(prefix=None):
    """Get a suitable user agent for identifying the CLI process."""
    prefix = (prefix or platform.platform(terse=1)).strip().lower()
    return f"cloudsmith-cli/{prefix} cli:{get_cli_version()} api:{get_api_version()}"


def pretty_print_list_info(num_results, page_info=None, suffix="", show_all=False):
    """Print information about list results."""
    if show_all:
        click.echo(
            "Results: %(num_results)d %(suffix)s"
            % {
                "num_results": num_results,
                "suffix": suffix,
            }
        )
    elif page_info:
        start = (page_info.page - 1) * page_info.page_size + 1
        end = min(start + num_results - 1, page_info.count)
        click.echo(
            "Results: %(start)d-%(end)d (%(count)d) of %(total)d %(suffix)s "
            "(page: %(page)d/%(pages)d, page size: %(page_size)d)"
            % {
                "start": start,
                "end": end,
                "count": num_results,
                "total": page_info.count,
                "suffix": suffix,
                "page": page_info.page,
                "pages": page_info.page_total,
                "page_size": page_info.page_size,
            }
        )
    else:
        click.echo(
            "Results: %(num_results)d %(suffix)s"
            % {"num_results": num_results, "suffix": suffix}
        )


def fmt_datetime(value):
    """Convert a datetime value to string."""
    if isinstance(value, (date, datetime)):
        return value.isoformat().replace("+00:00", "Z")
    return value


def fmt_bool(value):
    """Convert a boolean value to string."""
    if isinstance(value, bool):
        return str(value).lower()
    return value


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
        % {"throttle": click.style(str(rate_info.interval), reverse=True)},
        err=True,
        reset=False,
    )


def json_serializer(obj):
    """JSON serializer for objects not serializable by default."""

    # convert date/datetime objects to strings
    if isinstance(obj, (datetime, date)):
        return fmt_datetime(obj)
    raise TypeError("Type %s not serializable." % type(obj))


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
            dump = json.dumps(root, indent=4, sort_keys=True, default=json_serializer)
        else:
            dump = json.dumps(root, sort_keys=True, default=json_serializer)
    except (TypeError, ValueError) as e:
        click.secho(f"Failed to convert to JSON: {str(e)}", fg="red", err=True)
        return True

    click.echo(dump)
    return True


def maybe_truncate_string(data, max_len=50):
    """Maybe truncate a string"""
    if data is not None and len(data) > max_len:
        return data[: max_len - 3] + "..."
    return data


def maybe_truncate_list(data, max_len=5):
    """Maybe truncate list"""
    if data is not None and len(data) > max_len:
        return data[:max_len] + ["..."]
    return data


def confirm_operation(prompt, prefix=None, assume_yes=False, err=False):
    """Prompt the user for confirmation for dangerous actions."""
    if assume_yes:
        return True

    prefix = prefix or click.style(
        "Are you %s certain you want to" % (click.style("absolutely", bold=True))
    )

    prompt = f"{prefix} {prompt}?"

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
