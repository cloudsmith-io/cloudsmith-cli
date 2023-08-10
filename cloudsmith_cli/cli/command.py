"""CLI - Group/Command classes."""

from collections import OrderedDict

import click.exceptions
from click_didyoumean import DYMGroup


class AliasGroup(DYMGroup):
    """A command group with DYM and alias support."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aliases = OrderedDict()
        self.inverse = {}

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
        commands = super().list_commands(ctx)

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
        if getattr(ctx, "showing_help", False):
            if "|" in cmd_name:
                cmd_name = cmd_name.split("|")[0]

        try:
            cmd_name = self.inverse[cmd_name]
        except KeyError:
            pass

        return super().get_command(ctx, cmd_name)

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
