"""CLI - Deprecation warnings for old command, option and setting names."""

import os
from dataclasses import dataclass

import click
from click.core import ParameterSource

from ..core.utils import (
    JSON_OUTPUT_FORMATS,
    json_output_in_argv,
    output_format_in_argv,
)

#: The release that removes the deprecated aliases.
REMOVAL_VERSION = "2.0.0"

#: Set to 1, true or yes to turn off every deprecation warning.
SUPPRESS_ENVVAR = "CLOUDSMITH_SUPPRESS_DEPRECATIONS"
_TRUTHY_ENV_VALUES = ("1", "true", "yes")


@dataclass(frozen=True, kw_only=True)
class Deprecation:
    """A deprecated command, option or setting, and what replaces it.

    `what` and `use` are written as they appear in the warning, for example
    "`--token`" and "`--request-api-key`". `use` is None when nothing replaces
    `what`. `since` is the release that first deprecated it.
    """

    id: str
    what: str
    use: str | None
    since: str
    removed_in: str = REMOVAL_VERSION


#: Every deprecation that `warn` can report, so the warnings, the help output,
#: the tests and the usage data read from the same list.
DEPRECATIONS: list[Deprecation] = []


def get(deprecation_id):
    """Return the entry in `DEPRECATIONS` with the id `deprecation_id`."""
    for entry in DEPRECATIONS:
        if entry.id == deprecation_id:
            return entry
    raise KeyError(f"No deprecation with id {deprecation_id!r}")


#: Credential helper commands that package managers run. Their users cannot act
#: on a warning in the middle of a `docker pull` or `terraform init`, so these
#: commands print none.
CREDENTIAL_HELPER_RUNTIMES = frozenset(
    {"cargo", "docker", "generic", "pnpm", "terraform"}
)

#: Deprecated config.ini keys and the keys that replace them.
CONFIG_KEY_REPLACEMENTS = {
    "api_proxy": "proxy",
    "api_ssl_verify": "ssl_verify",
    "org": "workspace",
    "organization": "workspace",
    "oidc_org": "workspace",
}

#: Deprecated option spellings and the spellings that replace them.
PROXY_ALIASES = {"--api-proxy": "--proxy"}
PROXY_SUFFIXES_ALIASES = {"--allowed-api-proxy-suffixes": "--allowed-proxy-suffixes"}
SSL_VERIFY_ALIASES = {
    "--without-api-ssl-verify": "--without-ssl-verify",
    "-S": "--without-ssl-verify",
}
WORKSPACE_ALIASES = {
    "--org": "--workspace",
    "--organization": "--workspace",
    "--oidc-org": "--workspace",
    "--owner": "--workspace",
    "-o": "-w",
}
PAGE_ALL_ALIASES = {"--show-all": "--page-all"}

_WARNED_META_KEY = "cloudsmith_cli.deprecation_warnings"


def format_warning(subject, replacement=None, *, removal=None, detail=None):
    """Return the shared deprecation warning for `subject`."""
    removal = removal or f"will be removed in version {REMOVAL_VERSION}"
    message = f"Warning: {subject} is deprecated and {removal}."
    if replacement:
        message += f" Use {replacement} instead."
    if detail:
        message += f"\n{detail}"
    return message


def _is_credential_helper_runtime(ctx):
    parent = ctx.parent
    return (
        parent is not None
        and parent.info_name == "credential-helper"
        and ctx.info_name in CREDENTIAL_HELPER_RUNTIMES
    )


def _has_output_format(ctx):
    return any(param.name == "output_format" for param in ctx.command.params)


def _given_output_format(ctx, args):
    """Return the `--output-format` given to `ctx`, or None if it was left unset.

    If Click has not parsed the option yet, the value comes from `args`, the
    arguments of the command, or else from `sys.argv`.
    """
    if "output_format" not in ctx.params:
        return output_format_in_argv(args)
    if ctx.get_parameter_source("output_format") in (ParameterSource.DEFAULT, None):
        return None
    return ctx.params["output_format"]


def _json_output_requested(ctx, args=None):
    """Return True if the command prints JSON.

    As in `decorators.common_cli_output_options`, the nearest command that
    is given `--output-format` decides; one left unset inherits it from its
    group. Only the command that Click is parsing reads `args`.
    """
    has_option = False
    pending_args = args
    while ctx is not None:
        if _has_output_format(ctx):
            has_option = True
            output_format = _given_output_format(ctx, pending_args)
            if output_format is not None:
                return output_format in JSON_OUTPUT_FORMATS
        pending_args = ()
        ctx = ctx.parent
    return False if has_option else json_output_in_argv(args)


def _suppressed(ctx, args=None):
    """Return True if deprecation warnings are turned off for this run."""
    if os.environ.get(SUPPRESS_ENVVAR, "").strip().lower() in _TRUTHY_ENV_VALUES:
        return True
    return _json_output_requested(ctx, args)


def warn_message(
    subject, replacement=None, *, removal=None, detail=None, ctx=None, args=None
):
    """Print the deprecation warning for `subject` to stderr, once per run.

    Prints nothing with JSON output or when `SUPPRESS_ENVVAR` is set. Pass
    `args` when warning while Click parses the arguments of `ctx`.
    """
    if _suppressed(ctx or click.get_current_context(silent=True), args):
        return
    warn_once(
        format_warning(subject, replacement, removal=removal, detail=detail), ctx=ctx
    )


def warn_once(message, ctx=None):
    """Print the warning `message` to stderr, once per run.

    Silent for shell completion and for the credential helpers. Unlike
    `warn_message`, it also prints with JSON output and `SUPPRESS_ENVVAR`:
    for warnings that are not deprecations, such as an ignored telemetry
    setting.
    """
    ctx = ctx or click.get_current_context(silent=True)
    if ctx is not None:
        if ctx.resilient_parsing or _is_credential_helper_runtime(ctx):
            return
        warned = ctx.find_root().meta.setdefault(_WARNED_META_KEY, set())
        if message in warned:
            return
        warned.add(message)
    click.secho(message, fg="yellow", err=True)


def warn(deprecation_id, ctx=None):
    """Print the warning for the `DEPRECATIONS` entry `deprecation_id`."""
    entry = get(deprecation_id)
    warn_message(
        entry.what,
        entry.use,
        removal=f"will be removed in version {entry.removed_in}",
        ctx=ctx,
    )


def warn_option(spelling, replacement, ctx=None):
    """Warn that the option `spelling` is deprecated."""
    warn_message(f"`{spelling}`", f"`{replacement}`", ctx=ctx)


def warn_config_key(key, ctx=None):
    """Warn that the config.ini key `key` is deprecated."""
    warn_message(
        f"The `{key}` key in config.ini",
        f"`{CONFIG_KEY_REPLACEMENTS[key]}`",
        ctx=ctx,
    )


def warn_envvar(name, replacement, ctx=None):
    """Warn that the environment variable `name` is deprecated."""
    warn_message(f"`{name}`", f"`{replacement}`", ctx=ctx)


def warn_deprecated_envvar(ctx, param_name, envvars):
    """Warn if a parameter took its value from a deprecated environment variable.

    `envvars` lists the variables in the order Click reads them, with the
    current name first; Click takes the first one that is set and not empty.
    """
    if ctx.get_parameter_source(param_name) != ParameterSource.ENVIRONMENT:
        return
    used = next((name for name in envvars if os.environ.get(name)), None)
    if used and used != envvars[0]:
        warn_envvar(used, envvars[0], ctx=ctx)


def alias_param_name(spelling):
    """Return the parameter name of the hidden option for a deprecated spelling."""
    return "deprecated_" + spelling.lstrip("-").replace("-", "_")


def alias_options(aliases, envvars=None, **attrs):
    """Add each deprecated spelling in `aliases` as its own hidden option.

    A separate option per spelling lets the CLI name the spelling that was used
    in the warning, and keeps the old spellings out of the help text. `envvars`
    maps a spelling to the deprecated environment variable that also sets it.
    Use `pop_alias_options` in the command to read the values.
    """
    envvars = envvars or {}

    def decorator(f):
        for spelling in reversed(list(aliases)):
            f = click.option(
                spelling,
                alias_param_name(spelling),
                envvar=envvars.get(spelling),
                hidden=True,
                default=None,
                **attrs,
            )(f)
        return f

    return decorator


def pop_alias_options(ctx, kwargs, aliases):
    """Pop the hidden options of `aliases`, warning for each one on the command line.

    Return the value of the deprecated spelling given last on the command line,
    else the value from a deprecated environment variable, else None. The
    caller warns about the environment variable (see `alias_envvar`) once it
    knows that the value is used.

    The options are also removed from `ctx.params`, so `ctx.forward` passes the
    resolved value of the current option instead of the alias, which would
    lose its parameter source on the way.
    """
    names = {alias_param_name(spelling): spelling for spelling in aliases}
    order = list(ctx.params)
    value = None
    from_command_line = []
    for name, spelling in names.items():
        given = kwargs.pop(name)
        ctx.params.pop(name, None)
        source = ctx.get_parameter_source(name)
        if source == ParameterSource.COMMANDLINE:
            warn_option(spelling, aliases[spelling], ctx=ctx)
            from_command_line.append((name, given))
        elif source == ParameterSource.ENVIRONMENT:
            value = given
    if from_command_line:
        # Click records parameters in command-line order, so the last one
        # given wins, as it did when the spellings were one option.
        value = max(
            from_command_line,
            key=lambda item: order.index(item[0]) if item[0] in order else -1,
        )[1]
    return value


def alias_envvar(ctx, aliases):
    """Return the deprecated environment variable that set one of `aliases`.

    Return None if no alias came from the environment, or if a deprecated
    spelling on the command line took precedence over it.
    """
    if used_on_command_line(ctx, aliases):
        return None
    for spelling in aliases:
        name = alias_param_name(spelling)
        if ctx.get_parameter_source(name) == ParameterSource.ENVIRONMENT:
            param = next(p for p in ctx.command.params if p.name == name)
            return param.envvar
    return None


def keep_alias_source(ctx: click.Context, name: str, aliases: dict[str, str]) -> None:
    """Give option `name` the source of the deprecated spelling that set its value.

    Code that reads the parameter sources, such as the launcher settings, then
    sees the value as one that the user supplied.
    """
    if used_on_command_line(ctx, aliases):
        ctx.set_parameter_source(name, ParameterSource.COMMANDLINE)
    elif alias_envvar(ctx, aliases):
        ctx.set_parameter_source(name, ParameterSource.ENVIRONMENT)


def used_on_command_line(ctx, aliases):
    """Return True if any of the deprecated spellings was given on the command line."""
    return any(
        ctx.get_parameter_source(alias_param_name(spelling))
        == ParameterSource.COMMANDLINE
        for spelling in aliases
    )
