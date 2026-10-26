# Copyright 2026 Cloudsmith Ltd
"""The one-time usage telemetry notice.

Bump ``NOTICE_VERSION`` whenever what is collected changes, so the notice is
shown again. The wording is a draft.
"""

import click

from . import state

NOTICE_VERSION = 2
NOTICE_TEXT = (
    "The Cloudsmith CLI collects pseudonymous usage data: which commands run, "
    "how they end and how long they take, plus CLI, Python and OS versions. It "
    "never collects argument values, file names, credentials or account "
    "names. A random install ID is kept on this machine so repeat use can "
    "be counted; see it with 'cloudsmith telemetry id' and replace it with "
    "'cloudsmith telemetry reset'.\n"
    "To opt out, set CLOUDSMITH_NO_TELEMETRY=1 or DO_NOT_TRACK=1, or add "
    "'telemetry = false' to config.ini. To see exactly what is sent, set "
    "CLOUDSMITH_TELEMETRY=log.\n"
    "Learn more: https://docs.cloudsmith.com/developer-tools/cli\n"
    "Nothing was sent for this command. This notice will not be shown again."
)


def needs_notice():
    return state.read().get("notice_version") != NOTICE_VERSION


def show():
    click.echo(NOTICE_TEXT, err=True)
    return state.write({"notice_version": NOTICE_VERSION})
