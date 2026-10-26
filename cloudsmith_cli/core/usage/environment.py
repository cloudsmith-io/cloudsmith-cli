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


#: (agent, variables any of which marks it), checked in order. Only markers
#: an agent sets for the commands it runs: variables that IDEs also set in a
#: person's own terminal (``CLAUDECODE``, ``CURSOR_TRACE_ID``, ``REPL_ID``,
#: ``TERM_PROGRAM``) would label people as agents.
_AGENT_MARKERS = (
    ("claude_code", ("CLAUDE_CODE_CHILD_SESSION",)),
    ("codex", ("CODEX_THREAD_ID",)),
    ("gemini_cli", ("GEMINI_CLI",)),
    ("copilot", ("COPILOT_AGENT", "COPILOT_CLI", "COPILOT_AGENT_SESSION_ID")),
)
#: The cross-vendor convention, read after the vendor markers.
AI_AGENT_ENV = "AI_AGENT"
#: Known ``AI_AGENT`` value prefixes; any other value is counted as
#: ``UNIDENTIFIED_AGENT`` and never sent.
_AI_AGENT_PREFIXES = (
    ("claude-code", "claude_code"),
    ("github_copilot", "copilot"),
    ("codex", "codex"),
    ("gemini", "gemini_cli"),
    ("opencode", "opencode"),
)
UNIDENTIFIED_AGENT = "unidentified_agent"


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


def agent(env=None):
    """Name the AI agent that ran this command, from code-defined names only."""
    env = os.environ if env is None else env
    for name, markers in _AGENT_MARKERS:
        if any(env.get(marker) for marker in markers):
            return name
    declared = env.get(AI_AGENT_ENV, "").strip().lower()
    if not declared:
        return None
    for prefix, name in _AI_AGENT_PREFIXES:
        if declared.startswith(prefix):
            return name
    return UNIDENTIFIED_AGENT


def persona(*, ci, agent=None):  # pylint: disable=redefined-outer-name
    if agent:
        return "agent"
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
