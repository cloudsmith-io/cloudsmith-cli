"""CLI - Deprecation warnings for old command, option and setting names."""

import os

import click
from click.core import ParameterSource

#: The release that removes the deprecated aliases.
REMOVAL_VERSION = "2.0.0"

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


def warn(subject, replacement=None, *, removal=None, detail=None, ctx=None):
    """Print the deprecation warning for `subject` to stderr, once per run."""
    message = format_warning(subject, replacement, removal=removal, detail=detail)
    ctx = ctx or click.get_current_context(silent=True)
    if ctx is not None:
        if ctx.resilient_parsing or _is_credential_helper_runtime(ctx):
            return
        warned = ctx.find_root().meta.setdefault(_WARNED_META_KEY, set())
        if message in warned:
            return
        warned.add(message)
    click.secho(message, fg="yellow", err=True)


def warn_option(spelling, replacement, ctx=None):
    """Warn that the option `spelling` is deprecated."""
    warn(f"`{spelling}`", f"`{replacement}`", ctx=ctx)


def warn_config_key(key, ctx=None):
    """Warn that the config.ini key `key` is deprecated."""
    warn(
        f"The `{key}` key in config.ini",
        f"`{CONFIG_KEY_REPLACEMENTS[key]}`",
        ctx=ctx,
    )


def warn_envvar(name, replacement, ctx=None):
    """Warn that the environment variable `name` is deprecated."""
    warn(f"`{name}`", f"`{replacement}`", ctx=ctx)


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


def pop_alias_options(ctx, kwargs, aliases, envvar_replacements=None):
    """Pop the hidden options of `aliases` and warn for each one that was used.

    Return the value of a used spelling, preferring the command line over the
    environment, or None if none was used. `envvar_replacements` maps a
    deprecated environment variable to the setting that replaces it.
    """
    envvar_replacements = envvar_replacements or {}
    value = None
    from_command_line = False
    for spelling, replacement in aliases.items():
        name = alias_param_name(spelling)
        given = kwargs.pop(name)
        source = ctx.get_parameter_source(name)
        if source == ParameterSource.COMMANDLINE:
            warn_option(spelling, replacement, ctx=ctx)
            if not from_command_line:
                value, from_command_line = given, True
        elif source == ParameterSource.ENVIRONMENT:
            param = next(p for p in ctx.command.params if p.name == name)
            envvar = param.envvar
            warn_envvar(envvar, envvar_replacements.get(envvar), ctx=ctx)
            if value is None:
                value = given
    return value


def used_on_command_line(ctx, aliases):
    """Return True if any of the deprecated spellings was given on the command line."""
    return any(
        ctx.get_parameter_source(alias_param_name(spelling))
        == ParameterSource.COMMANDLINE
        for spelling in aliases
    )
