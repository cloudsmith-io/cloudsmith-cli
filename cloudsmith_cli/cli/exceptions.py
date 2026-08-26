"""CLI - Exceptions."""

import collections
import contextlib
import sys

import click

from ..core.api.exceptions import ApiException


@contextlib.contextmanager
def handle_api_exceptions(
    ctx,
    opts,
    context_msg=None,
    nl=False,
    exit_on_error=True,
    reraise_on_error=False,
    error_summaries=None,
    summarise_error=None,
):
    """Context manager that handles API exceptions.

    ``error_summaries`` optionally maps an HTTP status to a single-line
    message that replaces the default context/detail/hint block in
    human-readable output. Statuses that aren't mapped (and JSON output)
    keep the standard rendering.

    ``summarise_error`` is an optional callable taking ``(exc, detail,
    fields)`` and returning a single sentence to show instead of the default
    context/detail/field block, or ``None`` to keep the default. Unlike
    ``error_summaries``, this replaces the JSON ``detail`` too - use it
    where the API's field-indexed errors read poorly next to the rest of
    their output; returning ``None`` for statuses it doesn't recognise keeps
    the status code visible where it still matters.
    """
    # flake8: ignore=C901

    # Use stderr for messages if the output is something else (e.g.  # JSON)
    is_json_output = getattr(opts, "output", None) in ("json", "pretty_json")
    use_stderr = is_json_output

    try:
        yield
    except ApiException as exc:
        context_msg = context_msg or "Failed to perform operation!"
        detail, fields = get_details(exc)
        hint = get_error_hint(ctx, opts, exc)
        summary = summarise_error(exc, detail, fields) if summarise_error else None

        if is_json_output:
            # Construct JSON error object
            error_data = {
                "detail": summary or detail or exc.status_description,
                "help": {
                    "context": context_msg,
                    "hint": hint,
                },
                "meta": {
                    "code": exc.status,
                    "description": exc.status_description,
                },
            }

            if fields:
                error_data["fields"] = fields

            # Surface push-time metadata context (validation/attach result)
            # in the same JSON envelope so a downstream package-create or
            # sync failure does not lose the earlier metadata signal.
            metadata_context = getattr(opts, "push_metadata_info", None)
            if metadata_context is not None:
                error_data["metadata_attachment"] = metadata_context

            # Print to stdout
            import json

            click.echo(
                json.dumps(
                    error_data, indent=4 if opts.output == "pretty_json" else None
                )
            )

        else:
            # Standard CLI output to stderr (or interleaved if output != pretty, but we force use_stderr now)
            if nl:
                click.echo(err=use_stderr)
                click.secho("ERROR: ", fg="red", nl=False, err=use_stderr)
            else:
                click.secho("ERROR", fg="red", err=use_stderr)

            # A command-specific one-liner - from either mechanism - replaces
            # the generic context/detail/fields/hint block entirely.
            summary = summary or (error_summaries or {}).get(exc.status)
            if summary:
                click.secho(summary, fg="red", err=use_stderr)
            else:
                print_error_details(
                    context_msg, exc, detail, fields, hint, use_stderr=use_stderr
                )

            if opts.verbose and not opts.debug and exc.headers:
                click.echo(err=use_stderr)
                click.echo("Headers in Reply:", err=use_stderr)
                for k, v in exc.headers.items():
                    click.echo(f"{k} = {v}", err=use_stderr)

        if reraise_on_error:
            raise

        if exit_on_error:
            ctx.exit(exc.status or 1)


def print_error_details(context_msg, exc, detail, fields, hint, use_stderr=False):
    """Print the standard context/detail/fields/hint block for an error."""
    click.secho(
        f"{context_msg} (status: {exc.status} - {exc.status_description})",
        fg="red",
        err=use_stderr,
    )

    if detail or fields:
        click.echo(err=use_stderr)

        if detail:
            click.secho(
                "Detail: {detail}".format(
                    detail=click.style(detail, fg="red", bold=False)
                ),
                bold=True,
                err=use_stderr,
            )

        for k, v in (fields or {}).items():
            field = f"{k.capitalize()} Field"

            # Flatten list/tuple error messages for text output
            if isinstance(v, (list, tuple)):
                v = " ".join(v)

            click.secho(
                "{field}: {message}".format(
                    field=click.style(field, bold=True),
                    message=click.style(v, fg="red"),
                ),
                err=use_stderr,
            )

    if hint:
        click.echo(
            f"Hint: {click.style(hint, fg='yellow')}",
            err=use_stderr,
        )


def get_details(exc):
    """Get the details from the exception."""
    detail = None
    fields = collections.OrderedDict()

    if exc.detail:
        detail = exc.detail

    if exc.fields:
        for k, v in exc.fields.items():
            try:
                field_detail = v["detail"]
            except (TypeError, KeyError):
                field_detail = v

            if k == "non_field_errors":
                # Ensure we handle list/tuple for non_field_errors details joining
                if isinstance(field_detail, (list, tuple)):
                    field_detail = " ".join(field_detail)

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
    get_specific_error_hint = getattr(module, f"get_{exc.status}_error_hint", None)
    if get_specific_error_hint:
        return get_specific_error_hint(ctx, opts, exc)
    return None


def get_401_error_hint(ctx, opts, exc):
    """Get the hint for a 401/Unauthorised error."""
    # pylint: disable=unused-argument
    credential = getattr(opts, "credential", None)

    if credential and credential.auth_type == "bearer":
        return "Since you have an SSO access token set, this probably means that it has expired. Try getting a new token with 'cloudsmith auth', then try again."

    if credential:
        return (
            "This usually means your API key is invalid, expired, or "
            "lacks access to this resource - check your credentials and "
            "try again."
        )

    if ctx.info_name == "token":
        # This is already the token command
        return (
            "The login failed - Either your email address and/or "
            "your password was incorrect. Please check them and "
            "try again!"
        )

    return (
        "You don't have an API key or access token set, but it seems this action "
        "requires authentication - Try getting your API key via "
        "'cloudsmith token', or access token via 'cloudsmith auth', then try again."
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
