"""CLI - Group/Command classes."""

import importlib
from collections import OrderedDict

import click.exceptions
from click_didyoumean import DYMGroup


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
            "hint": "Check your command arguments/flags.",
        },
    }


class AliasGroup(DYMGroup):
    """A command group with DYM, alias and lazy-subcommand support.

    ``lazy_commands`` maps a command name to the module that registers it.
    The module is imported on first use, which keeps startup fast because
    an invocation imports only the module of the invoked command.
    ``lazy_aliases`` supplies the alias map for those commands up front.
    """

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

    def main(self, *args, **kwargs):
        """Override main to intercept exceptions and format as JSON if requested."""
        import sys

        original_standalone_mode = kwargs.get("standalone_mode", True)
        kwargs["standalone_mode"] = False

        try:
            return super().main(*args, **kwargs)
        except click.exceptions.Abort:
            if not original_standalone_mode:
                raise
            click.echo("Aborted!", err=True)
            sys.exit(1)
        except click.exceptions.ClickException as e:
            if _is_json_output_requested(e):
                import json

                click.echo(json.dumps(_format_click_exception_as_json(e), indent=4))
                sys.exit(e.exit_code)

            if not original_standalone_mode:
                raise
            e.show()
            sys.exit(e.exit_code)
