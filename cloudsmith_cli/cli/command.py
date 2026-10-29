"""CLI - Group/Command classes."""

import importlib
from collections import OrderedDict

import click.exceptions
from click_didyoumean import DYMGroup

from ..core.certificate_errors import describe_certificate_error
from .usage_capture import TrackedCommand, TrackingMixin, record_alias


def _is_json_output_requested(exception):
    """Determine if JSON output was requested, checking context and argv."""
    # Check context if available
    ctx = getattr(exception, "ctx", None)
    if ctx and ctx.params:
        fmt = ctx.params.get("output")
        if fmt in ("json", "pretty_json"):
            return True

    # Fallback: check sys.argv for output format flags
    import sys

    argv = sys.argv

    if "--output-format=json" in argv or "--output-format=pretty_json" in argv:
        return True

    for idx, arg in enumerate(argv):
        if (
            arg in ("-F", "--output-format")
            and idx + 1 < len(argv)
            and argv[idx + 1] in ("json", "pretty_json")
        ):
            return True

    return False


def _is_debug_requested(args=None):
    """Determine if --debug was passed (the click context is gone by now).

    ``args`` are the arguments given to ``main``; click falls back to
    ``sys.argv`` when they are ``None``, so we do the same.
    """
    import sys

    if args is None:
        args = sys.argv[1:]
    return any(arg in ("-d", "--debug") for arg in args)


def _format_click_exception_as_json(exception):
    """Format a ClickException as a JSON error dict."""
    return {
        "detail": exception.format_message(),
        "meta": {
            "code": exception.exit_code,
            "description": "Usage Error",
        },
        "help": {
            "context": "Invalid usage",
            "hint": describe_certificate_error(exception)
            or "Check your command arguments/flags.",
        },
    }


def _echo_certificate_hint(exception):
    """Explain a TLS certificate failure behind ``exception`` on stderr."""
    hint = describe_certificate_error(exception)
    if hint:
        click.echo(f"Hint: {click.style(hint, fg='yellow')}", err=True)


class AliasGroup(TrackingMixin, DYMGroup):
    """A command group with DYM, alias and lazy-subcommand support.

    ``lazy_commands`` maps a command name to the module that registers it.
    The module is imported on first use, which keeps startup fast because
    an invocation imports only the module of the invoked command.
    ``lazy_aliases`` supplies the alias map for those commands up front.
    """

    command_class = TrackedCommand

    def __init__(self, *args, **kwargs):
        lazy_commands = kwargs.pop("lazy_commands", None)
        lazy_aliases = kwargs.pop("lazy_aliases", None)
        super().__init__(*args, **kwargs)
        self.lazy_commands = dict(lazy_commands or {})
        self.aliases = OrderedDict()
        self.inverse = {}
        for name, aliases in (lazy_aliases or {}).items():
            self.aliases[name] = aliases
            for alias in aliases:
                self.inverse[alias] = name

    def resolve_command(self, ctx, args):
        if args and args[0] in self.inverse:
            record_alias(ctx, args[0])
        try:
            return super().resolve_command(ctx, args)
        except click.exceptions.UsageError:
            # Before DYM kicks in, check to see if the command prefix matches
            # exactly one command, then use that instead.
            if args:
                cmd_name = args[0]
                cmds = self.list_commands(ctx)
                matched = [cmd for cmd in cmds if cmd.startswith(cmd_name)]
                if len(matched) == 1 and len(cmd_name) > 1:
                    record_alias(ctx, "<prefix>")
                    args[0] = matched[0]
                    return super().resolve_command(ctx, args)

            raise

    def list_commands(self, ctx):
        commands = sorted(set(super().list_commands(ctx)) | set(self.lazy_commands))

        if getattr(ctx, "showing_help", False):
            for k, v in enumerate(commands):
                try:
                    commands[k] = f"{v}|{'|'.join(self.aliases[v])}"
                except KeyError:
                    pass

            return commands

        for k in self.inverse:
            commands.append(k)

        return commands

    def get_command(self, ctx, cmd_name):
        if getattr(ctx, "showing_help", False) and "|" in cmd_name:
            cmd_name = cmd_name.split("|")[0]

        try:
            cmd_name = self.inverse[cmd_name]
        except KeyError:
            pass

        cmd = super().get_command(ctx, cmd_name)
        if cmd is None and cmd_name in self.lazy_commands:
            importlib.import_module(self.lazy_commands[cmd_name])
            cmd = super().get_command(ctx, cmd_name)
        return cmd

    def command(self, *args, **kwargs):
        def decorator(f):
            # pylint: disable=missing-docstring
            aliases = kwargs.pop("aliases", [])
            cmd = super(AliasGroup, self).command(*args, **kwargs)(f)

            if aliases:
                self.aliases[cmd.name] = aliases
                for alias in aliases:
                    self.inverse[alias] = cmd.name

            return cmd

        return decorator

    def group(self, *args, **kwargs):
        def decorator(f):
            # pylint: disable=missing-docstring
            aliases = kwargs.pop("aliases", [])
            cmd = super(AliasGroup, self).group(*args, **kwargs)(f)

            if aliases:
                self.aliases[cmd.name] = aliases
                for alias in aliases:
                    self.inverse[alias] = cmd.name

            return cmd

        return decorator

    def format_commands(self, ctx, formatter):
        ctx.showing_help = True
        return super().format_commands(ctx, formatter)

    def _main_shell_completion(self, ctx_args, prog_name, complete_var=None):
        """Mark shell completion runs so usage telemetry ignores them.

        Click handles ``*_source`` before any context exists, so the
        ``resilient_parsing`` check in ``_finish_usage`` never sees it.
        """
        import os

        from . import usage_capture

        name = complete_var
        if name is None:
            # Same derivation as Click's own _main_shell_completion.
            name = prog_name.replace("-", "_").replace(".", "_")
            name = f"_{name}_COMPLETE".upper()
        if os.environ.get(name):
            usage_capture.mark_completion_run()
        return super()._main_shell_completion(ctx_args, prog_name, complete_var)

    def main(self, *args, **kwargs):
        """Override main to intercept exceptions and format as JSON if requested."""
        import sys
        import time

        from . import usage_capture

        original_standalone_mode = kwargs.get("standalone_mode", True)
        kwargs["standalone_mode"] = False
        usage = {"outcome": "unexpected_error", "exit_code": 1}
        depth = usage_capture.enter_run()
        started = time.monotonic()

        try:
            rv = super().main(*args, **kwargs)
            usage.update(
                outcome="success" if not rv else "error_exit",
                exit_code=(rv if isinstance(rv, int) else 1) if rv else 0,
            )
            return rv
        except click.exceptions.Abort:
            usage.update(outcome="aborted", exit_code=1)
            if not original_standalone_mode:
                raise
            click.echo("Aborted!", err=True)
            sys.exit(1)
        except click.exceptions.ClickException as e:
            usage.update(
                outcome=(
                    "usage_error"
                    if isinstance(e, click.exceptions.UsageError)
                    else "click_error"
                ),
                exit_code=e.exit_code,
            )
            if _is_json_output_requested(e):
                import json

                click.echo(json.dumps(_format_click_exception_as_json(e), indent=4))
                sys.exit(e.exit_code)

            if not original_standalone_mode:
                raise
            e.show()
            _echo_certificate_hint(e)
            sys.exit(e.exit_code)
        except SystemExit as e:
            code = e.code
            usage.update(
                exit_code=code if isinstance(code, int) else (0 if code is None else 1),
                outcome="success" if code in (0, None) else "error_exit",
            )
            raise
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Anything reaching here is unexpected: click's own errors and
            # handled API errors (which exit via ctx.exit) are dealt with
            # above or never get this far.
            usage.update(outcome="unexpected_error", exit_code=1)
            if not original_standalone_mode:
                raise
            main_args = kwargs.get("args", args[0] if args else None)
            if _is_debug_requested(main_args):
                import traceback

                click.echo(traceback.format_exc(), err=True, nl=False)
            from ..core import telemetry

            # Reporting is silent: the user sees the same line either way.
            telemetry.report_exception(e)
            click.echo(f"Error: {telemetry.format_exception_summary(e)}", err=True)
            _echo_certificate_hint(e)
            sys.exit(1)
        finally:
            _finish_usage(usage, started, nested=depth > 1)
            usage_capture.exit_run()


def _finish_usage(usage, started, *, nested):
    """Hand the run to usage telemetry; never raises, never prints."""
    try:
        import time

        from ..core.usage import run
        from . import usage_capture

        meta = usage_capture.current_root_meta() or {}
        contexts = meta.get(usage_capture.META_KEY, {}).get("contexts", [])
        # Shell completion parses with resilient_parsing (or, for the
        # *_source script, not at all); never report it.
        completing = usage_capture.is_completion_run() or any(
            getattr(c, "resilient_parsing", False) for c in contexts
        )
        facts = usage_capture.collect_facts(
            meta,
            outcome=usage["outcome"],
            exit_code=usage["exit_code"],
            duration_ms=int((time.monotonic() - started) * 1000),
            nested=nested or completing,
        )
        if facts.api_status is not None and facts.outcome == "error_exit":
            facts.outcome = "api_error"
        run.finish(facts)
    except BaseException:  # pylint: disable=broad-exception-caught
        return
