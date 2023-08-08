"""Core rate limit utilities."""

from collections import namedtuple

# pylint: disable=ungrouped-imports
import click
from click.utils import strip_ansi

Table = namedtuple(
    "Table", ["headers", "plain_headers", "rows", "plain_rows", "column_widths"]
)


def make_table(headers=None, rows=None):
    """Make a table from headers and rows."""
    if callable(headers):
        headers = headers()
    if callable(rows):
        rows = rows()
    assert isinstance(headers, list)
    assert isinstance(rows, list)
    assert all(len(row) == len(headers) for row in rows)

    plain_headers = [strip_ansi(str(v)) for v in headers]
    plain_rows = [row for row in [strip_ansi(str(v)) for v in rows]]

    plain_headers = []
    column_widths = []

    for k, v in enumerate(headers):
        v = str(v)
        plain = strip_ansi(v)
        plain_headers.append(plain)
        column_widths.append(len(plain))

        if len(v) == len(plain):
            # Value was unstyled, make it bold
            v = click.style(v, bold=True)

        headers[k] = v

    plain_rows = []
    for row in rows:
        plain_row = []
        for k, v in enumerate(row):
            v = str(v)
            plain = strip_ansi(v)
            plain_row.append(plain)
            column_widths[k] = max(column_widths[k], len(plain))

        plain_rows.append(plain_row)

    return Table(
        headers=headers,
        plain_headers=plain_headers,
        rows=rows,
        plain_rows=plain_rows,
        column_widths=column_widths,
    )
