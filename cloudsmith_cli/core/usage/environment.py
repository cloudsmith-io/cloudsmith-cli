# Copyright 2026 Cloudsmith Ltd
"""Where the CLI is running: CI, containers, persona and runtime facts.

CI providers are detected by the presence of their well-known variables;
their values are never read or sent.
"""

import os
import platform
import re

#: (provider, variables any of which marks it), checked in order.
_CI_PROVIDERS = (
    ("github_actions", ("GITHUB_ACTIONS",)),
    ("gitlab", ("GITLAB_CI",)),
    ("jenkins", ("JENKINS_URL", "JENKINS_HOME")),
    ("circleci", ("CIRCLECI",)),
    ("buildkite", ("BUILDKITE",)),
    ("azure_pipelines", ("TF_BUILD",)),
    ("bitbucket", ("BITBUCKET_BUILD_NUMBER",)),
    ("teamcity", ("TEAMCITY_VERSION",)),
    ("codebuild", ("CODEBUILD_BUILD_ID",)),
    ("other", ("CI",)),
)


def ci_provider(env=None):
    env = os.environ if env is None else env
    for provider, names in _CI_PROVIDERS:
        if any(name in env for name in names):
            return provider
    return None


def is_container():
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return True
    return "KUBERNETES_SERVICE_HOST" in os.environ


def is_ephemeral(*, env=None, channel, state_writable):
    """Runs whose disk does not survive: no saved ID, no person profile."""
    if ci_provider(env) is not None:
        return True
    if channel == "docker" or not state_writable:
        return True
    return is_container()


def persona(*, ci):
    return "ci" if ci else "human"


def _major_minor(version):
    match = re.match(r"(\d+)\.(\d+)", version or "")
    return f"{match.group(1)}.{match.group(2)}" if match else "unknown"


def runtime_properties():
    return {
        "os": platform.system() or "unknown",
        "os_version": _major_minor(platform.release()),
        "python_version": _major_minor(platform.python_version()),
        "arch": (platform.machine() or "unknown").lower(),
    }
