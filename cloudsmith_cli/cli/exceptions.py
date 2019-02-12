# -*- coding: utf-8 -*-
"""CLI - Exceptions."""
from __future__ import absolute_import, print_function, unicode_literals

import collections
import contextlib
import sys

import click
import six

from ..core.api.exceptions import ApiException


@contextlib.contextmanager
def handle_api_exceptions(
    ctx, opts, context_msg=None, nl=False, exit_on_error=True, reraise_on_error=False
):
    """Context manager that handles API exceptions."""
    # flake8: ignore=C901
    # Use stderr for messages if the output is something else (e.g.  # JSON)
    use_stderr = opts.output != "pretty"

    try:
        yield
    except ApiException as exc:
        if nl:
            click.echo(err=use_stderr)
            click.secho("ERROR: ", fg="red", nl=False, err=use_stderr)
        else:
            click.secho("ERROR", fg="red", err=use_stderr)

        context_msg = context_msg or "Failed to perform operation!"
        click.secho(
            "%(context)s (status: %(code)s - %(code_text)s)"
            % {
                "context": context_msg,
                "code": exc.status,
                "code_text": exc.status_description,
            },
            fg="red",
            err=use_stderr,
        )

        detail, fields = get_details(exc)
        if detail or fields:
            click.echo(err=use_stderr)

            if detail:
                click.secho(
                    "Detail: %(detail)s"
                    % {"detail": click.style(detail, fg="red", bold=False)},
                    bold=True,
                    err=use_stderr,
                )

            if fields:
                for k, v in six.iteritems(fields):
                    field = "%s Field" % k.capitalize()
                    click.secho(
                        "%(field)s: %(message)s"
                        % {
                            "field": click.style(field, bold=True),
                            "message": click.style(v, fg="red"),
                        },
                        err=use_stderr,
                    )

        hint = get_error_hint(ctx, opts, exc)
        if hint:
            click.echo(
                "Hint: %(hint)s" % {"hint": click.style(hint, fg="yellow")},
                err=use_stderr,
            )

        if opts.verbose and not opts.debug:
            if exc.headers:
                click.echo(err=use_stderr)
                click.echo("Headers in Reply:", err=use_stderr)
                for k, v in six.iteritems(exc.headers):
                    click.echo(
                        "%(key)s = %(value)s" % {"key": k, "value": v}, err=use_stderr
                    )

        if reraise_on_error:
            six.reraise(*sys.exc_info())

        if exit_on_error:
            ctx.exit(exc.status or 1)


def get_details(exc):
    """Get the details from the exception."""
    detail = None
    fields = collections.OrderedDict()

    if exc.detail:
        detail = exc.detail

    if exc.fields:
        for k, v in six.iteritems(exc.fields):
            try:
                field_detail = v["detail"]
            except (TypeError, KeyError):
                field_detail = v

            if isinstance(field_detail, (list, tuple)):
                field_detail = " ".join(field_detail)

            if k == "non_field_errors":
                if detail:
                    detail += " " + field_detail
                else:
                    detail = field_detail
                continue

            fields[k] = field_detail

    return detail, fields


def get_error_hint(ctx, opts, exc):
    """Get a hint to show to the user (if any)."""
    module = sys.modules[__name__]
    get_specific_error_hint = getattr(module, "get_%s_error_hint" % exc.status, None)
    if get_specific_error_hint:
        return get_specific_error_hint(ctx, opts, exc)
    return None


def get_401_error_hint(ctx, opts, exc):
    """Get the hint for a 401/Unauthorised error."""
    # pylint: disable=unused-argument
    if opts.api_key:
        return (
            "Since you have an API key set, this probably means "
            "you don't have the permision to perform this action."
        )

    if ctx.info_name == "token":
        # This is already the token command
        return (
            "The login failed - Either your email address and/or "
            "your password was incorrect. Please check them and "
            "try again!"
        )

    return (
        "You don't have an API key set, but it seems this action "
        "requires authentication - Try getting your API key via "
        "'cloudsmith token' first then try again."
    )


def get_404_error_hint(ctx, opts, exc):
    """Get the hint for a 404/NotFound error."""
    # pylint: disable=unused-argument
    # pylint: disable=fixme
    # TODO(ls): Expand this to be contextual (we could look at the
    # arguments for the command).
    return "This usually means the user/org is wrong or not visible."


def get_500_error_hint(ctx, opts, exc):
    """Get the hint for a 500/InternalServerError error."""
    # pylint: disable=unused-argument
    return (
        "This usually means the Cloudsmith service is encountering "
        "issues, either with this specific command or as a whole. "
        "Please accept our apologies and try again later."
    )
