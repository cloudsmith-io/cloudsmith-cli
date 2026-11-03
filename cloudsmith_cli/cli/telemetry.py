# Copyright 2026 Cloudsmith Ltd
"""What a command may send: ``@telemetry.send(telemetry.ERRORS)``.

``ALL`` (error reports and usage events) is the default, so only commands
that send less need the decorator:

* ``NONE``: nothing.
* ``ERRORS``: Sentry reports of unexpected exceptions only.
* ``USAGE``: the usage event only.

A policy on a group applies to every command under it unless a command sets
its own. The user's opt-outs always win. Imported by command modules, so it
must stay light: only the stdlib-only ``core.telemetry_common``.
"""

from ..core.telemetry_common import Send, send

NONE = Send.NONE
ERRORS = Send.ERRORS
USAGE = Send.USAGE
ALL = Send.ALL

__all__ = ["ALL", "ERRORS", "NONE", "USAGE", "Send", "send"]
