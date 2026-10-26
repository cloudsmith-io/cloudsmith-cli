# Copyright 2026 Cloudsmith Ltd
"""Record usage facts from the live Click context.

Only names defined in code leave this module: command names, parameter
names, the option spellings declared on each option, env var names declared
on each option, and alias names. Argument and option values are never read.
"""

import os
import sys

import click
from click.core import ParameterSource

META_KEY = "cloudsmith_usage"
_HELP_SPELLINGS = frozenset({"-h", "--help"})
_SOURCE_BY_CLICK = {
    ParameterSource.COMMANDLINE: "flag",
    ParameterSource.ENVIRONMENT: "env",
}
#: Click env vars that carry no information (set on almost every run).
_IGNORED_ENVVARS = frozenset({"TERM"})

# The env vars and spellings of the host and SSL options declared in
# ``decorators.initialise_session``. Their values reach ``opts`` only when
# that decorator runs, which ``--version``, ``--help`` and usage errors never
# reach, so the host and SSL gates also read them here.
API_HOST_ENV = "CLOUDSMITH_API_HOST"
SSL_VERIFY_ENV = "CLOUDSMITH_SSL_VERIFY"
WITHOUT_SSL_VERIFY_ENV = "CLOUDSMITH_WITHOUT_API_SSL_VERIFY"
API_HOST_SPELLINGS = frozenset({"--api-host"})
SSL_OFF_SPELLINGS = frozenset(
    {"--without-ssl-verify", "--without-api-ssl-verify", "-S"}
)
#: The config file and profile options of ``decorators.common_cli_config_options``.
#: A typed one names a file or profile only that decorator loads.
CONFIG_SPELLINGS = frozenset({"-C", "--config-file", "-P", "--profile"})
#: Not a host: a typed ``--api-host`` that never reached opts fails the gate.
UNRESOLVED_HOST = "unresolved"
#: Click's boolean spellings (``BoolParamType``); an empty env var is unset.
_FALSE = frozenset({"0", "false", "no", "off", "n", "f"})
_TRUE = frozenset({"1", "true", "yes", "on", "y", "t"})


def _store(ctx):
    return ctx.meta.setdefault(META_KEY, {"contexts": [], "typed": [], "aliases": []})


def _takes_value(param):
    return not (
        param.is_flag or param.count or getattr(param, "_flag_needs_value", False)
    )


def _short_cluster(token, spellings):
    """Expand ``-vSPname`` the way Click does: ``-v``, ``-S``, ``-P``.

    Stops at the first option that takes a value (the rest of the token is
    that value) or at an undeclared character.
    """
    found = []
    for char in token[1:]:
        spelling = f"-{char}"
        if spelling not in spellings:
            break
        found.append(spelling)
        if spellings[spelling]:
            break
    return found


def match_typed_flags(params, args):
    """Return the declared option spellings present in ``args`` (no values)."""
    # spelling -> whether the option takes a value
    spellings = {}
    for param in params:
        if isinstance(param, click.Option):
            for spelling in param.opts:
                spellings[spelling] = _takes_value(param)
            for spelling in param.secondary_opts:
                spellings[spelling] = False
    found = set()
    for token in args:
        if token == "--":
            break
        if not token.startswith("-") or token == "-":
            continue
        name = token.split("=", 1)[0]
        if name in spellings:
            found.add(name)
        elif not name.startswith("--"):
            found.update(_short_cluster(token, spellings))
    return sorted(found)


_RUN = {"depth": 0, "root_meta": None, "completion": False}


def enter_run():
    """Mark the start of a top-level ``main()``; return the nesting depth."""
    _RUN["depth"] += 1
    if _RUN["depth"] == 1:
        _RUN["root_meta"] = None
        _RUN["completion"] = False
    return _RUN["depth"]


def exit_run():
    """Mark the end of a ``main()`` run."""
    _RUN["depth"] = max(0, _RUN["depth"] - 1)
    if _RUN["depth"] == 0:
        _RUN["root_meta"] = None
        _RUN["completion"] = False


def mark_completion_run():
    """Record that this run only serves shell completion."""
    _RUN["completion"] = True


def is_completion_run():
    """Tell whether this run only serves shell completion."""
    return _RUN["completion"]


def current_root_meta():
    """Return the ``ctx.meta`` of the root context of the current run."""
    return _RUN["root_meta"]


class TrackingMixin:
    """Record each context and its typed option spellings before parsing.

    Recording happens before ``super().parse_args`` so usage errors and
    ``--help`` (which exit during parsing) still have a command path.
    """

    def parse_args(self, ctx, args):
        if _RUN["depth"] >= 1 and ctx.parent is None and _RUN["root_meta"] is None:
            _RUN["root_meta"] = ctx.meta
        store = _store(ctx)
        store["contexts"].append(ctx)
        store["typed"].extend(match_typed_flags(self.get_params(ctx), args))
        return super().parse_args(ctx, args)


class TrackedCommand(TrackingMixin, click.Command):
    """A command whose invocation is recorded for usage facts."""


class TrackedGroup(TrackingMixin, click.Group):
    """A group whose invocation is recorded; subcommands default to tracked."""

    command_class = TrackedCommand


def record_alias(ctx, name):
    """Record that a command was reached through an alias (or ``<prefix>``)."""
    _store(ctx)["aliases"].append(name)


def record_api_status(ctx, status):
    """Record the HTTP status of the API error that ended the run.

    Best effort: this runs on the error path, which usage capture must
    never change, so a context that cannot hold the status is ignored.
    """
    try:
        _store(ctx)["api_status"] = status
    except (AttributeError, TypeError):
        pass


def _command_path(contexts):
    leaf = contexts[-1] if contexts else None
    names = []
    while leaf is not None and leaf.parent is not None:
        if leaf.command.name:
            names.append(leaf.command.name)
        leaf = leaf.parent
    return " ".join(reversed(names)) or "<root>"


def _env_names(param):
    if isinstance(param.envvar, str):
        return [param.envvar]
    return list(param.envvar or [])


def _param_facts(contexts):
    from ..core.usage.event import SETTING_ALIASES

    flags, envvars, sources = set(), set(), {}
    for ctx in contexts:
        for param in ctx.command.params:
            if not param.name or not isinstance(param, click.Option):
                continue  # arguments are neither flags nor settings
            source = ctx.get_parameter_source(param.name)
            if source == ParameterSource.COMMANDLINE:
                flags.add(param.name)
            if source == ParameterSource.ENVIRONMENT:
                # Click uses the first non-empty variable, not the first set one.
                used = next((n for n in _env_names(param) if os.environ.get(n)), None)
                if used and used not in _IGNORED_ENVVARS:
                    envvars.add(used)
            if source in _SOURCE_BY_CLICK:
                setting = SETTING_ALIASES.get(param.name, param.name)
                sources[setting] = _SOURCE_BY_CLICK[source]
    return sorted(flags), sorted(envvars), sources


def _config_sources(meta):
    from . import config_sources

    return config_sources.detect(
        config_file=meta.get("config_file"),
        creds_file=meta.get("creds_file"),
        profile=meta.get("profile"),
    )


def _options():
    from . import config

    return getattr(config.OPTIONS, "value", None)


def record_session(ctx):
    """Record that ``initialise_session`` put the host and SSL options in opts."""
    _store(ctx)["session"] = ctx


def record_credential(ctx, credential):
    """Record how the run logged in, by provider name only.

    A command that hands off (``list repos`` to ``repositories get``)
    resolves credentials again where the env key is not passed on, so a
    later ``None`` must not replace the login the run used.
    """
    source = getattr(credential, "source_name", None)
    if source:
        _store(ctx)["auth_source"] = source


def record_config(ctx):
    """Record that ``common_cli_config_options`` loaded the config files."""
    _store(ctx)["config"] = ctx


def _set_up_by_leaf(store, key):
    # A group (e.g. `list`) loads config and sets up the session before its
    # subcommand parses, so only work done by the leaf counts: in the leaf's
    # own context, or in a sub-context below it when the leaf hands off to
    # another command (`list repos` runs `repositories get` via ctx.forward).
    contexts = store.get("contexts", [])
    ctx = store.get(key)
    while contexts and ctx is not None:
        if ctx is contexts[-1]:
            return True
        ctx = ctx.parent
    return False


def _session_resolved(store):
    return _set_up_by_leaf(store, "session")


def _config_resolved(store):
    return _set_up_by_leaf(store, "config")


def resolve_api_host(opts, *, resolved, typed=()):
    """Return the API host the run targets, for the host gate (never sent)."""
    if resolved:
        return getattr(opts, "api_host", None)
    if API_HOST_SPELLINGS & set(typed):
        return UNRESOLVED_HOST
    # The env var beats config.ini, as it does in initialise_session.
    return os.environ.get(API_HOST_ENV) or getattr(opts, "api_host", None)


def resolve_ssl_verify(opts, typed=()):
    """Tell whether SSL verification is on; any sign of it being off wins."""
    if getattr(opts, "ssl_verify", True) is False or SSL_OFF_SPELLINGS & set(typed):
        return False
    verify = os.environ.get(SSL_VERIFY_ENV, "").strip().lower()
    without = os.environ.get(WITHOUT_SSL_VERIFY_ENV, "").strip().lower()
    return verify not in _FALSE and without not in _TRUE


def _ssl_verify_strict(opts):
    """The resolved ``--without-ssl-verify-strict`` setting, or None if unset.

    Set by ``initialise_session`` even for commands that never load the SDK
    (``update``), whose Configuration the sender would otherwise fall back to.
    """
    value = getattr(opts, "ssl_verify_strict", None)
    return value if isinstance(value, bool) else None


def typed_flags(meta):
    """The option spellings typed in this run, from its root ``ctx.meta``."""
    return sorted(set((meta or {}).get(META_KEY, {}).get("typed", [])))


def collect_facts(meta, *, outcome, exit_code, duration_ms, nested):
    """Build the ``RunFacts`` for a run from its recorded context metadata."""
    from ..core.usage.event import RunFacts

    store = meta.get(META_KEY, {})
    contexts = store.get("contexts", [])
    flags, envvars, sources = _param_facts(contexts)
    opts = _options()
    typed = typed_flags(meta)
    credential = getattr(opts, "credential", None)
    return RunFacts(
        command=_command_path(contexts),
        flags=flags,
        flags_typed=typed,
        envvars=envvars,
        aliases_used=list(store.get("aliases", [])),
        output_format=getattr(opts, "output", None),
        # A typed --help only means help was shown if the run then succeeded:
        # `whoami --no-such-flag --help` is still a usage error.
        outcome="help"
        if _HELP_SPELLINGS & set(typed) and outcome == "success"
        else outcome,
        exit_code=exit_code,
        api_status=store.get("api_status"),
        duration_ms=duration_ms,
        setting_sources=sources,
        auth_source=store.get("auth_source")
        or getattr(credential, "source_name", None),
        api_host=resolve_api_host(opts, resolved=_session_resolved(store), typed=typed),
        ssl_verify=resolve_ssl_verify(opts, typed),
        ssl_verify_strict=_ssl_verify_strict(opts),
        stdout_tty=bool(sys.stdout and sys.stdout.isatty()),
        stdin_tty=bool(sys.stdin and sys.stdin.isatty()),
        nested=nested,
        # A typed config file or profile that the leaf never loaded may hold
        # an opt-out or a host this run cannot see: never send.
        config_unresolved=bool(CONFIG_SPELLINGS & set(typed))
        and not _config_resolved(store),
        # Reads the ini files, so it runs only once a run is known to send.
        deferred_sources=lambda: _config_sources(meta),
    )
