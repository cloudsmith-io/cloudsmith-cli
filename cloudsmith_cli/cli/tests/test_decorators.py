import click
import click.testing

from ..decorators import report_retry


def test_report_retry_writes_to_stderr():
    @click.command()
    def command():
        click.echo('{"data": []}')
        report_retry(30, context="retry-after")

    result = click.testing.CliRunner().invoke(command, catch_exceptions=False)

    assert result.stdout == '{"data": []}\n'
    assert "Request was throttled (429)" in result.stderr
