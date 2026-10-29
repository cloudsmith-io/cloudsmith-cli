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
