# Copyright 2026 Cloudsmith Ltd
"""The one-time usage telemetry notice.

Bump ``NOTICE_VERSION`` whenever what is collected changes, so the notice is
shown again.
"""

import click

from . import state

NOTICE_VERSION = 2
NOTICE_TEXT = (
    "The Cloudsmith CLI collects pseudonymous usage data to help improve the "
    "CLI. It never collects argument values, file names or credentials.\n"
    "Read what is collected (and how to opt out): "
    "https://docs.cloudsmith.com/developer-tools/cli-telemetry\n"
    "Nothing was sent for this command."
)


def needs_notice():
    return state.read().get("notice_version") != NOTICE_VERSION


def show():
    click.echo(NOTICE_TEXT, err=True)
    return state.write({"notice_version": NOTICE_VERSION})
