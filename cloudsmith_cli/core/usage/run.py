# Copyright 2026 Cloudsmith Ltd
"""Decide whether to send a usage event for this run, and send it.

Checks run cheapest-first and stop at the first "no", so commands that send
no usage event (``@telemetry.send`` without USAGE, e.g. credential helpers
on every pull) pay almost nothing. Never raises.
"""

import functools
import random
import time
from datetime import UTC, datetime

BACKOFF_SECONDS = 24 * 60 * 60


def _load_deferred_sources(facts):
    """Merge config-file setting sources in; Click flag/env sources win.

    Also loads the config key names set. Each part fails on its own.
    """
    _merge_config_sources(facts)
    _load_config_keys(facts)


def _merge_config_sources(facts):
    if facts.deferred_sources is None:
        return
    try:
        loaded = facts.deferred_sources()
        facts.setting_sources = {**loaded, **facts.setting_sources}
    except Exception:  # pylint: disable=broad-exception-caught
        return


def _load_config_keys(facts):
    if facts.deferred_config_keys is None:
        return
    try:
        facts.config_keys = facts.deferred_config_keys()
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


def finish(facts):
    try:
        _finish(facts)
    except BaseException:  # pylint: disable=broad-exception-caught
        return


def _finish(facts):  # pylint: disable=too-many-return-statements,too-many-locals
    if facts.nested or facts.config_unresolved or not facts.usage_allowed:
        return

    # Imported late so a command that sends no usage event pays for none of
    # these modules.
    from .. import installation, telemetry_common, version
    from . import environment, event, identity, notice, sender, settings, state

    # The opt-out check and the config.ini gate share one read of the file.
    read_config = functools.cache(telemetry_common.read_config_file)
    mode, source = telemetry_common.resolve_mode(
        telemetry_common.Kind.USAGE, read_config
    )
    if mode is telemetry_common.Mode.DISABLED:
        # An unreadable file sends nothing but is not an opt-out, so it must
        # not delete the install ID.
        if source != telemetry_common.CONFIG_UNREADABLE:
            identity.forget()
        return
    log = mode is telemetry_common.Mode.LOG
    if not telemetry_common.is_cloudsmith_host(facts.api_host) or not facts.ssl_verify:
        return
    if _config_file_blocks(facts, read_config):
        return
    env_name = telemetry_common.get_environment()
    if env_name == "development" and not settings.override_set():
        return
    if not settings.project_key() and not log:
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

    if log:
        sender.log(payload)
        return
    # send() returns None when too little of the shared wait budget is left
    # (nothing was attempted); only a real failure (False) starts the backoff.
    if sender.send(payload, facts.ssl_verify_strict) is False and not ephemeral:
        state.write({"last_failure_at": time.time()})
