# Copyright 2026 Cloudsmith Ltd
"""Switches and endpoints for usage telemetry.

Released builds send to the "CLI" PostHog EU project (336063). Development
builds (source checkouts, editable installs) send nothing unless a developer
sets ``CLOUDSMITH_TELEMETRY_POSTHOG_KEY``, which also replaces the key.
"""

import os

# Log mode is shared with error reporting.
from ..telemetry_common import MODE_ENV  # noqa: F401
from ..telemetry_common import log_mode as _shared_log_mode

#: Project key of the dedicated "CLI" PostHog EU project (336063). Not a
#: secret: a PostHog project key can only send events, and every client that
#: reports to PostHog ships one (like the Sentry DSN in core/telemetry.py).
POSTHOG_PROJECT_KEY = (
    "phc_p989pbFFZ98a4eDbLc4yxAjSPWF8en2fjodbrhtMc2yY"  # gitleaks:allow
)
POSTHOG_HOST = "https://eu.i.posthog.com"

KEY_ENV = "CLOUDSMITH_TELEMETRY_POSTHOG_KEY"
HOST_ENV = "CLOUDSMITH_TELEMETRY_POSTHOG_HOST"
INTERNAL_ENV = "CLOUDSMITH_TELEMETRY_INTERNAL"
INSTALL_ID_ENV = "CLOUDSMITH_TELEMETRY_INSTALL_ID"
SAMPLE_RATE_ENV = "CLOUDSMITH_TELEMETRY_CI_SAMPLE_RATE"

_TRUTHY = ("1", "true", "yes")
_FALSY = ("0", "false", "no", "off")


def _env(env):
    return os.environ if env is None else env


def _truthy(env, name):
    return _env(env).get(name, "").strip().lower() in _TRUTHY


def override_set(env=None):
    return bool(_env(env).get(KEY_ENV, "").strip())


def project_key(env=None):
    return _env(env).get(KEY_ENV, "").strip() or POSTHOG_PROJECT_KEY


def host(env=None):
    return (_env(env).get(HOST_ENV, "").strip() or POSTHOG_HOST).rstrip("/")


def log_mode(env=None):
    return _shared_log_mode(env)


def internal(env=None):
    return _truthy(env, INTERNAL_ENV)


def install_id_enabled(env=None):
    # On by default for laptops; only an explicit off value disables it.
    return _env(env).get(INSTALL_ID_ENV, "").strip().lower() not in _FALSY


def ci_sample_rate(env=None):
    try:
        rate = int(_env(env).get(SAMPLE_RATE_ENV, "100"))
    except ValueError:
        return 100
    return rate if 0 <= rate <= 100 else 100
