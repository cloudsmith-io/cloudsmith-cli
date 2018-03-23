"""CLI - Group/Command classes."""
from __future__ import absolute_import, print_function, unicode_literals
from future.builtins import super

from collections import OrderedDict

from click_didyoumean import DYMGroup
import six


class AliasGroup(DYMGroup):
    """
    A group with DYM and alias support.
    """

    def __init__(self, *args, **kwargs):
        super(AliasGroup, self).__init__(*args, **kwargs)
        self.aliases = OrderedDict()
        self.inverse = {}

    def list_commands(self, ctx):
        commands = super(AliasGroup, self).list_commands(ctx)

        if getattr(ctx, 'showing_help', False):
            for k, v in enumerate(commands):
                try:
                    commands[k] = '%s|%s' % (v, '|'.join(self.aliases[v]))
                except KeyError:
                    pass

            return commands

        for k in six.iterkeys(self.inverse):
            commands.append(k)

        return commands

    def get_command(self, ctx, cmd_name):
        if getattr(ctx, 'showing_help', False):
            if '|' in cmd_name:
                cmd_name = cmd_name.split('|')[0]

        try:
            cmd_name = self.inverse[cmd_name]
        except KeyError:
            pass

        return super(AliasGroup, self).get_command(ctx, cmd_name)

    def command(self, *args, **kwargs):
        def decorator(f):
            aliases = kwargs.pop('aliases', [])
            cmd = super(AliasGroup, self).command(*args, **kwargs)(f)

            if aliases:
                self.aliases[cmd.name] = aliases
                for alias in aliases:
                    self.inverse[alias] = cmd.name

            return cmd

        return decorator

    def group(self, *args, **kwargs):
        def decorator(f):
            aliases = kwargs.pop('aliases', [])
            cmd = super(AliasGroup, self).group(*args, **kwargs)(f)

            if aliases:
                self.aliases[cmd.name] = aliases
                for alias in aliases:
                    self.inverse[alias] = cmd.name

            return cmd

        return decorator

    def format_commands(self, ctx, formatter):
        ctx.showing_help = True
        return super(AliasGroup, self).format_commands(ctx, formatter)
