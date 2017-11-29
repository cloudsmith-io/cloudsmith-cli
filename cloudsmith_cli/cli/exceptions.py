"""CLI - Exceptions."""
from __future__ import absolute_import, print_function, unicode_literals

import contextlib
import sys

import click
import six

from ..core.api.exceptions import ApiException


@contextlib.contextmanager
def handle_api_exceptions(
        ctx, opts, exit_code=1, context_msg=None, nl=False,
        exit_on_error=True, reraise_on_error=False):
    """Context manager that handles API exceptions."""
    # flake8: ignore=C901
    try:
        yield
    except ApiException as exc:
        if nl:
            click.echo()
            click.secho('ERROR: ', fg='red', nl=False)
        else:
            click.secho('ERROR', fg='red', nl=False)
            click.echo()

        context_msg = context_msg or 'Failed to perform operation!'
        click.secho(
            '%(context)s (status: %(code)s - %(code_text)s)' % {
                'context': context_msg,
                'code': exc.status,
                'code_text': exc.status_description
            }, fg='red'
        )

        if exc.detail:
            click.echo()
            click.secho(
                'Reason: %(detail)s' % {
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
                    '%(field)s: %(message)s' % {
                        'field': click.style(k, bold=True),
                        'message': click.style(' '.join(v), fg='red')
                    }
                )

        if opts.verbose and not opts.debug:
            if exc.headers:
                click.echo()
                click.echo('Headers in Reply:')
                for k, v in six.iteritems(exc.headers):
                    click.echo(
                        '%(key)s = %(value)s' % {
                            'key': k,
                            'value': v
                        }
                    )

        if reraise_on_error:
            six.reraise(*sys.exc_info())

        if exit_on_error:
            ctx.exit(exc.status)
