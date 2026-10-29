# Copyright 2026 Cloudsmith Ltd
"""Decide whether to send a usage event for this run, and send it.

Checks run cheapest-first and stop at the first "no", so excluded commands
(credential helpers on every pull) pay almost nothing. Never raises.
"""

import functools
import random
import time
from datetime import UTC, datetime

EXCLUDED_COMMANDS = frozenset({"mcp start"})
#: Machine-invoked or telemetry-managing commands. ``install``,
#: ``uninstall`` and ``list`` under credential-helper are run by people and
#: do send.
EXCLUDED_PREFIXES = (
    "credential-helper cargo",
    "credential-helper docker",
    "credential-helper generic",
    "credential-helper pnpm",
    "credential-helper terraform",
    "telemetry",
)
BACKOFF_SECONDS = 24 * 60 * 60


def _excluded(command):
    if command in EXCLUDED_COMMANDS:
        return True
    return any(command == p or command.startswith(p + " ") for p in EXCLUDED_PREFIXES)


def _load_deferred_sources(facts):
    """Merge config-file setting sources in; Click flag/env sources win."""
    if facts.deferred_sources is None:
        return
    try:
        loaded = facts.deferred_sources()
        facts.setting_sources = {**loaded, **facts.setting_sources}
    except Exception:  # pylint: disable=broad-exception-caught
        return


def _config_file_blocks(facts, read_config):
    """Apply the host and SSL gates to config.ini for a run that never loaded it.

    Root ``--help`` and root usage errors end before the root callback loads
    config, so a host or ``ssl_verify`` set only in config.ini never reached
    the facts. A host from the env var or a flag still wins over the file.
    Fails closed if the file cannot be read.
    """
    from ...cli import config
    from .. import telemetry_common

    if getattr(config.OPTIONS, "value", None) is not None:
        return False
    try:
        probe = read_config()
    except Exception:  # pylint: disable=broad-exception-caught
        return True
    if not facts.api_host and not telemetry_common.is_cloudsmith_host(probe.api_host):
        return True
    return probe.ssl_verify is False


def _config_opted_out(read_config):
    """Tell whether config.ini really says ``telemetry = false``.

    Unlike ``config_disabled``, an unreadable file is not an opt-out, so it
    must not delete the install ID.
    """
    from ...cli import config

    try:
        opts = getattr(config.OPTIONS, "value", None)
        if opts is not None and opts.telemetry is False:
            return True
        return read_config().telemetry is False
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def finish(facts):
    try:
        _finish(facts)
    except BaseException:  # pylint: disable=broad-exception-caught
        return


def _finish(facts):  # pylint: disable=too-many-return-statements,too-many-locals
    if facts.nested or facts.config_unresolved or _excluded(facts.command):
        return

    # Imported late so an excluded command pays for none of these modules.
    from .. import installation, telemetry_common, version
    from . import environment, event, identity, notice, sender, settings, state

    if telemetry_common.telemetry_disabled():
        identity.forget()
        return
    # The opt-out check and the config.ini gate share one read of the file.
    read_config = functools.cache(telemetry_common.read_config_file)
    if telemetry_common.config_disabled(read_config):
        if _config_opted_out(read_config):
            identity.forget()
        return
    if not telemetry_common.is_cloudsmith_host(facts.api_host) or not facts.ssl_verify:
        return
    if _config_file_blocks(facts, read_config):
        return
    env_name = telemetry_common.get_environment()
    if env_name == "development" and not settings.override_set():
        return
    if not settings.project_key() and not settings.log_mode():
        return

    channel = installation.detect_channel()
    provider = environment.ci_provider()
    ephemeral = environment.is_ephemeral(channel=channel, state_writable=True)
    if not ephemeral:
        # Ephemeral runs must do no file I/O, so the writability probe only
        # runs for otherwise non-ephemeral runs. An unwritable state file
        # cannot record the notice or the backoff, so treat it as ephemeral.
        ephemeral = environment.is_ephemeral(
            channel=channel, state_writable=state.writable()
        )

    if not ephemeral:
        last_failure = state.read().get("last_failure_at")
        if (
            isinstance(last_failure, (int, float))
            and time.time() - last_failure < BACKOFF_SECONDS
        ):
            return

    # Only CI runs are sampled; containers and unwritable state are ephemeral
    # too but are not CI (their events carry ci=false).
    sample_rate = settings.ci_sample_rate() if provider is not None else 100
    if sample_rate < 100 and random.uniform(0, 100) >= sample_rate:
        return

    interactive = facts.stdout_tty and facts.stdin_tty and provider is None
    if interactive and not ephemeral and notice.needs_notice():
        notice.show()
        return

    ident = identity.resolve(
        ephemeral=ephemeral, install_id_enabled=settings.install_id_enabled()
    )
    _load_deferred_sources(facts)
    payload = event.build_event(
        facts=facts,
        identity=ident,
        runtime=environment.runtime_properties(),
        channel=channel,
        environment=env_name,
        cli_version=version.get_version(),
        ci_provider=provider,
        agent=environment.agent(),
        sample_rate=sample_rate,
        internal=settings.internal(),
        timestamp=datetime.now(UTC).isoformat(),
    )

    if settings.log_mode():
        sender.log(payload)
        return
    # send() returns None when too little of the shared wait budget is left
    # (nothing was attempted); only a real failure (False) starts the backoff.
    if sender.send(payload, facts.ssl_verify_strict) is False and not ephemeral:
        state.write({"last_failure_at": time.time()})
