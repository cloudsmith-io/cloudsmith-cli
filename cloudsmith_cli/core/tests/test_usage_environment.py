import pytest

from cloudsmith_cli.core.usage import environment


@pytest.mark.parametrize(
    "env,expected",
    [
        ({"GITHUB_ACTIONS": "true"}, "github_actions"),
        ({"GITLAB_CI": "true"}, "gitlab"),
        ({"JENKINS_URL": "http://j"}, "jenkins"),
        ({"CIRCLECI": "true"}, "circleci"),
        ({"BUILDKITE": "true"}, "buildkite"),
        ({"TF_BUILD": "True"}, "azure_pipelines"),
        ({"BITBUCKET_BUILD_NUMBER": "1"}, "bitbucket"),
        ({"TEAMCITY_VERSION": "2024"}, "teamcity"),
        ({"CODEBUILD_BUILD_ID": "x"}, "codebuild"),
        ({"CI": "1"}, "other"),
        ({}, None),
    ],
)
def test_ci_provider_by_presence(env, expected):
    assert environment.ci_provider(env) == expected


def test_ephemeral_rule(monkeypatch):
    monkeypatch.setattr(environment, "is_container", lambda: False)
    assert environment.is_ephemeral(env={"CI": "x"}, channel="pip", state_writable=True)
    assert environment.is_ephemeral(env={}, channel="docker", state_writable=True)
    assert environment.is_ephemeral(env={}, channel="pip", state_writable=False)
    assert not environment.is_ephemeral(env={}, channel="pip", state_writable=True)


def test_non_tty_alone_is_not_ci():
    assert environment.persona(ci=False) == "human"
    assert environment.persona(ci=True) == "ci"


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, None),
        ({"CLAUDE_CODE_CHILD_SESSION": "1"}, "claude_code"),
        ({"CODEX_THREAD_ID": "t-1"}, "codex"),
        ({"GEMINI_CLI": "1"}, "gemini_cli"),
        ({"COPILOT_AGENT": "1"}, "copilot"),
        ({"COPILOT_CLI": "1"}, "copilot"),
        ({"COPILOT_AGENT_SESSION_ID": "s-1"}, "copilot"),
        ({"AI_AGENT": "claude-code_2-1-308_agent"}, "claude_code"),
        ({"AI_AGENT": "github_copilot_vscode_agent"}, "copilot"),
        ({"AI_AGENT": "opencode"}, "opencode"),
        ({"AI_AGENT": "acme-internal-bot_9"}, "unidentified_agent"),
        ({"AI_AGENT": ""}, None),
        ({"CLAUDE_CODE_CHILD_SESSION": ""}, None),
    ],
)
def test_agent_detection(env, expected):
    assert environment.agent(env) == expected


def test_markers_that_ides_set_for_people_are_ignored():
    # These are also set in a person's own IDE terminal.
    env = {
        "CLAUDECODE": "1",
        "CURSOR_TRACE_ID": "x",
        "REPL_ID": "x",
        "TERM_PROGRAM": "vscode",
        "COPILOT_MODEL": "x",
    }
    assert environment.agent(env) is None


def test_vendor_marker_beats_ai_agent():
    env = {"CODEX_THREAD_ID": "t-1", "AI_AGENT": "claude-code_1_agent"}
    assert environment.agent(env) == "codex"


def test_agent_wins_persona_even_in_ci():
    assert environment.persona(ci=True, agent="copilot") == "agent"
    assert environment.persona(ci=False, agent="claude_code") == "agent"
    assert environment.persona(ci=True, agent=None) == "ci"


def test_runtime_properties_truncate_versions(monkeypatch):
    monkeypatch.setattr(environment.platform, "system", lambda: "Linux")
    monkeypatch.setattr(environment.platform, "release", lambda: "6.8.0-1070-azure")
    monkeypatch.setattr(environment.platform, "python_version", lambda: "3.12.7")
    monkeypatch.setattr(environment.platform, "machine", lambda: "X86_64")
    props = environment.runtime_properties()
    assert props == {
        "os": "Linux",
        "os_version": "6.8",
        "python_version": "3.12",
        "arch": "x86_64",
    }
