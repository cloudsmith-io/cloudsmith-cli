# Copyright 2026 Cloudsmith Ltd
"""Switches and endpoints for usage telemetry.

There is no production project key yet: only the developer override
(``CLOUDSMITH_TELEMETRY_POSTHOG_KEY``) can make the CLI send.
"""

import os

POSTHOG_PROJECT_KEY = ""
POSTHOG_HOST = "https://eu.i.posthog.com"

KEY_ENV = "CLOUDSMITH_TELEMETRY_POSTHOG_KEY"
HOST_ENV = "CLOUDSMITH_TELEMETRY_POSTHOG_HOST"
MODE_ENV = "CLOUDSMITH_TELEMETRY"
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
    return _env(env).get(MODE_ENV, "").strip().lower() == "log"


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
