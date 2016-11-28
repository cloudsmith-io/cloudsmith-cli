"""CLI - Exceptions."""
from __future__ import absolute_import, print_function, unicode_literals
import contextlib

import click
import six
from ..core.api.exceptions import ApiException


@contextlib.contextmanager
def handle_api_exceptions(
        ctx, opts=None, exit_code=1, context_msg=None, nl=False):
    """Context manager that handles API exceptions."""
    try:
        yield
    except ApiException as exc:
        if nl:
            click.echo()
            click.secho("ERROR: ", fg='red', nl=False)
        else:
            click.secho("ERROR", fg='red', nl=False)
            click.echo()

        if exc.status == 422:
            description = 'Unprocessable Entity'
        else:
            description = exc.status_description

        context_msg = context_msg or "Failed to perform operation!"
        click.secho(
            "%(context)s (status: %(code)s - %(code_text)s)" % {
                'context': context_msg,
                'code': exc.status,
                'code_text': description
            }, fg='red'
        )

        if exc.detail:
            click.echo()
            click.secho(
                "Reason: %(detail)s" % {
                    'detail': exc.detail
                }, bold=True
            )

        if exc.fields:
            if not exc.detail:
                click.echo()

            for k, v in six.iteritems(exc.fields):
                if k == 'non_field_errors':
                    k = 'Validation'
                click.secho(
                    "%(field)s: %(message)s" % {
                        'field': click.style(k, bold=True),
                        'message': click.style(' '.join(v), fg='red')
                    }
                )

        debug = opts.get('DEBUG', False)
        verbose = opts.get('VERBOSE') or debug
        if verbose and not debug:
            if exc.headers:
                click.echo()
                click.echo("Headers in Reply:")
                for k, v in six.iteritems(exc.headers):
                    click.echo(
                        "%(key)s = %(value)s" % {
                            'key': k,
                            'value': v
                        }
                    )

        ctx.exit(exit_code)
