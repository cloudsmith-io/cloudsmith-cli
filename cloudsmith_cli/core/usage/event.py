# Copyright 2026 Cloudsmith Ltd
"""The usage event: one declaration per property.

To add a property: add a ``Property`` here with the question it answers,
fill it in ``_values``, and extend the tests.
Only names declared here can leave the machine, and only with their type.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

EVENT_NAME = "cli command executed"
SCHEMA_VERSION = 1

#: Settings whose *source* (never value) may be reported as ``source_<name>``.
ALLOWED_SETTINGS = frozenset(
    {
        "api_headers",
        "api_host",
        "proxy",
        "ssl_verify",
        "ssl_verify_strict",
        "api_user_agent",
        "mcp_allowed_tools",
        "mcp_allowed_tool_groups",
        "oidc_audience",
        "workspace",
        "oidc_service_slug",
        "oidc_detector_order",
        "oidc_disabled_detectors",
        "metadata_failure_mode",
        "check_for_update",
        "telemetry",
        "api_key",
        "profile",
        "config_file_path",
        "credentials_file_path",
        "output_format",
        "color",
    }
)
#: Names that map onto a setting in ``ALLOWED_SETTINGS``: config.ini keys
#: (``config_sources``) and Click parameter names (``usage_capture``).
SETTING_ALIASES = {
    "api_proxy": "proxy",
    "api_ssl_verify": "ssl_verify",
    "org": "workspace",
    "organization": "workspace",
    "oidc_org": "workspace",
    "config_file": "config_file_path",
    "credentials_file": "credentials_file_path",
    "without_api_ssl_verify": "ssl_verify",
}
SOURCE_VALUES = frozenset(
    {
        "flag",
        "env",
        "config_file",
        "config_profile",
        "credentials_file",
        "credentials_profile",
    }
)


@dataclass
class RunFacts:
    command: str
    flags: list[str] = field(default_factory=list)
    flags_typed: list[str] = field(default_factory=list)
    envvars: list[str] = field(default_factory=list)
    aliases_used: list[str] = field(default_factory=list)
    output_format: str | None = None
    outcome: str = "success"
    exit_code: int = 0
    api_status: int | None = None
    duration_ms: int = 0
    setting_sources: dict[str, str] = field(default_factory=dict)
    auth_source: str | None = None
    api_host: str | None = None
    ssl_verify: bool = True
    stdout_tty: bool = False
    stdin_tty: bool = False
    nested: bool = False
    #: A typed ``--config-file``/``--profile`` the command never loaded; the
    #: run sends nothing. Not an event property.
    config_unresolved: bool = False
    #: Loads config-file setting sources after the telemetry gates, so a run
    #: that sends nothing does no file I/O. Not an event property.
    deferred_sources: Callable[[], dict[str, str]] | None = None


@dataclass(frozen=True)
class Property:
    name: str
    kind: type
    #: The question the property answers.
    purpose: str


PROPERTIES = (
    Property("command", str, "command and flag use; persona; reliability and speed"),
    Property("flags", list, "command and flag use; configuration habits"),
    Property("flags_typed", list, "command and flag use"),
    Property("envvars", list, "configuration habits; login methods"),
    Property("aliases_used", list, "command and flag use"),
    Property("output_format", str, "command and flag use; persona"),
    Property("outcome", str, "reliability and speed"),
    Property("exit_code", int, "reliability and speed"),
    Property("api_status", int, "reliability and speed"),
    Property("duration_ms", int, "reliability and speed"),
    Property("auth_source", str, "configuration habits; login methods"),
    Property("cli_version", str, "version adoption"),
    Property("channel", str, "dimension"),
    Property("environment", str, "data quality"),
    Property("os", str, "dimension"),
    Property("os_version", str, "dimension"),
    Property("python_version", str, "support policy"),
    Property("arch", str, "dimension"),
    Property("persona", str, "persona"),
    Property("ci", bool, "persona"),
    Property("ci_provider", str, "persona"),
    Property("stdout_tty", bool, "persona"),
    Property("first_run", bool, "onboarding and retention"),
    Property("install_id_persisted", bool, "data quality"),
    Property("sample_rate", int, "cost"),
    Property("internal", bool, "data quality"),
    Property("schema_version", int, "maintenance"),
    Property("$geoip_disable", bool, "privacy"),
    Property("$process_person_profile", bool, "privacy; cost"),
)


def _names(value, *, ordered=False):
    """Normalise a collection of names, or return None so it is left out.

    Anything but a list, tuple or set of strings is malformed: a bare string
    would otherwise be sent one character at a time.
    """
    if not isinstance(value, (list, tuple, set, frozenset)):
        return None
    if not all(isinstance(item, str) for item in value):
        return None
    return list(value) if ordered else sorted(set(value))


def _values(
    facts,
    identity,
    runtime,
    channel,
    environment,
    cli_version,
    ci_provider,
    sample_rate,
    internal,
):
    return {
        "command": facts.command,
        "flags": _names(facts.flags),
        "flags_typed": _names(facts.flags_typed),
        "envvars": _names(facts.envvars),
        "aliases_used": _names(facts.aliases_used, ordered=True),
        "output_format": facts.output_format,
        "outcome": facts.outcome,
        "exit_code": facts.exit_code,
        "api_status": facts.api_status,
        "duration_ms": facts.duration_ms,
        "auth_source": facts.auth_source,
        "cli_version": cli_version,
        "channel": channel,
        "environment": environment,
        "persona": "ci" if ci_provider else "human",
        "ci": ci_provider is not None,
        "ci_provider": ci_provider,
        "stdout_tty": facts.stdout_tty,
        "first_run": identity.first_run,
        "install_id_persisted": identity.persisted,
        "sample_rate": sample_rate,
        "internal": internal or None,
        "schema_version": SCHEMA_VERSION,
        "$geoip_disable": True,
        # Never a person profile, install ID or not.
        "$process_person_profile": False,
        **runtime,
    }


def build_event(
    *,
    facts,
    identity,
    runtime,
    channel,
    environment,
    cli_version,
    ci_provider,
    sample_rate,
    internal,
    timestamp,
):
    values = _values(
        facts,
        identity,
        runtime,
        channel,
        environment,
        cli_version,
        ci_provider,
        sample_rate,
        internal,
    )
    properties = {}
    for prop in PROPERTIES:
        value = values.get(prop.name)
        if value is None:
            continue
        if not isinstance(value, prop.kind) or (
            prop.kind is int and isinstance(value, bool)
        ):
            continue
        properties[prop.name] = value
    for setting, source in sorted(facts.setting_sources.items()):
        if setting in ALLOWED_SETTINGS and source in SOURCE_VALUES:
            properties[f"source_{setting}"] = source
    return {
        "event": EVENT_NAME,
        "distinct_id": identity.distinct_id,
        "timestamp": timestamp,
        "properties": properties,
    }
