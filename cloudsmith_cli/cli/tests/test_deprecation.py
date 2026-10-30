# Copyright 2026 Cloudsmith Ltd
"""Tests for the deprecation warnings of old option, variable and config names."""

import json
from unittest.mock import patch

import click
import click.testing
import pytest

from .. import deprecation
from ..decorators import (
    common_cli_config_options,
    common_cli_list_options,
    common_cli_output_options,
    resolve_credentials,
)

ENVVARS = (
    "CLOUDSMITH_WORKSPACE",
    "CLOUDSMITH_ORG",
    "CLOUDSMITH_PROXY",
    "CLOUDSMITH_API_PROXY",
    "CLOUDSMITH_SSL_VERIFY",
    "CLOUDSMITH_WITHOUT_API_SSL_VERIFY",
    "CLOUDSMITH_ALLOWED_PROXY_SUFFIXES",
    "CLOUDSMITH_ALLOWED_API_PROXY_SUFFIXES",
    "CLOUDSMITH_CONFIG_FILE",
    "CLOUDSMITH_PROFILE",
)


def _report_command():
    @click.command()
    @common_cli_config_options
    @common_cli_output_options
    @common_cli_list_options
    @resolve_credentials
    def report(opts, page, page_size, page_all):  # pylint: disable=unused-argument
        click.echo(
            json.dumps(
                {
                    "org": opts.org,
                    "proxy": opts.proxy,
                    "ssl_verify": opts.ssl_verify,
                    "page_all": page_all,
                }
            )
        )

    return report


@pytest.fixture(autouse=True)
def isolated(monkeypatch, telemetry_config_dir):
    for name in ENVVARS:
        monkeypatch.delenv(name, raising=False)
    with patch(
        "cloudsmith_cli.cli.decorators.CredentialProviderChain.resolve",
        return_value=None,
    ):
        yield telemetry_config_dir


def invoke(args=(), env=None, command=None):
    result = click.testing.CliRunner().invoke(
        command or _report_command(), list(args), env=env, catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    return result


def values(result):
    return json.loads(result.stdout)


def test_format_warning():
    assert deprecation.format_warning("`--org`", "`--workspace`") == (
        "Warning: `--org` is deprecated and will be removed in version "
        f"{deprecation.REMOVAL_VERSION}. Use `--workspace` instead."
    )


def test_format_warning_with_custom_removal_and_detail():
    assert deprecation.format_warning(
        "`cloudsmith login`", removal="will stop working soon", detail="More: x"
    ) == (
        "Warning: `cloudsmith login` is deprecated and will stop working soon.\nMore: x"
    )


@pytest.mark.parametrize(
    "args,env",
    [
        (["-w", "acme", "--proxy", "http://proxy:3128", "--without-ssl-verify"], {}),
        (["--workspace", "acme", "--page-all"], {}),
        (
            [],
            {
                "CLOUDSMITH_WORKSPACE": "acme",
                "CLOUDSMITH_PROXY": "http://proxy:3128",
                "CLOUDSMITH_SSL_VERIFY": "0",
                "CLOUDSMITH_ALLOWED_PROXY_SUFFIXES": "example.com",
            },
        ),
    ],
)
def test_current_names_do_not_warn(args, env):
    assert invoke(args, env=env).stderr == ""


@pytest.mark.parametrize(
    "flag,replacement",
    [
        ("--org", "--workspace"),
        ("--organization", "--workspace"),
        ("--oidc-org", "--workspace"),
        ("--owner", "--workspace"),
        ("-o", "-w"),
    ],
)
def test_workspace_flag_aliases_warn_and_still_work(flag, replacement):
    result = invoke([flag, "acme"])

    assert values(result)["org"] == "acme"
    assert (
        result.stderr
        == deprecation.format_warning(f"`{flag}`", f"`{replacement}`") + "\n"
    )


def test_proxy_flag_alias_warns_and_still_works():
    result = invoke(["--api-proxy", "http://proxy:3128"])

    assert values(result)["proxy"] == "http://proxy:3128"
    assert "Warning: `--api-proxy` is deprecated" in result.stderr
    assert "Use `--proxy` instead." in result.stderr


@pytest.mark.parametrize("flag", ["-S", "--without-api-ssl-verify"])
def test_ssl_flag_aliases_warn_and_still_work(flag):
    result = invoke([flag])

    assert values(result)["ssl_verify"] is False
    assert f"Warning: `{flag}` is deprecated" in result.stderr
    assert "Use `--without-ssl-verify` instead." in result.stderr


def test_show_all_warns_and_still_works():
    result = invoke(["--show-all"])

    assert values(result)["page_all"] is True
    assert "Warning: `--show-all` is deprecated" in result.stderr
    assert "Use `--page-all` instead." in result.stderr


def test_show_all_still_conflicts_with_page():
    result = click.testing.CliRunner().invoke(
        _report_command(), ["--show-all", "--page", "2"]
    )

    assert result.exit_code == 2
    assert "Cannot be used with --page (-p) or --page-size (-l)." in result.output


@pytest.mark.parametrize("flag", ["--page-all", "--show-all"])
def test_show_all_survives_list_repos_forwarding(flag):
    """`list repos` forwards its parameters to `repos get`."""
    from ..commands.list_ import repos

    with patch(
        "cloudsmith_cli.cli.commands.repos.paginate_results", return_value=([], None)
    ) as paginate:
        result = invoke(
            ["acme", flag, "--api-host", "https://api.example.invalid"], command=repos
        )

    assert paginate.call_args.args[1] is True
    assert result.stderr.count("is deprecated") == (flag == "--show-all")


def test_aliases_survive_forwarding():
    @click.command()
    @common_cli_config_options
    @common_cli_list_options
    @resolve_credentials
    @click.pass_context
    def outer(ctx, opts, page, page_size, page_all):  # pylint: disable=unused-argument
        ctx.forward(inner)

    inner = _report_command()

    result = invoke(
        ["--org", "acme", "--api-proxy", "http://proxy:3128", "-S", "--show-all"],
        command=outer,
    )

    assert values(result) == {
        "org": "acme",
        "proxy": "http://proxy:3128",
        "ssl_verify": False,
        "page_all": True,
    }
    assert result.stderr.count("is deprecated") == 4


def test_page_size_wildcard_is_not_a_conflict():
    result = invoke(["--page-size", "*"])

    assert values(result)["page_all"] is True
    assert result.stderr == ""


@pytest.mark.parametrize(
    "args,expected",
    [
        (["--workspace", "new", "--org", "old"], "new"),
        (["--org", "old", "--workspace", "new"], "new"),
    ],
)
def test_current_flag_wins_over_alias(args, expected):
    result = invoke(args)

    assert values(result)["org"] == expected
    assert "`--org` is deprecated" in result.stderr


@pytest.mark.parametrize(
    "args,expected",
    [
        (["--org", "first", "--owner", "last"], "last"),
        (["--owner", "first", "--org", "last"], "last"),
        (["-o", "first", "--oidc-org", "last"], "last"),
    ],
)
def test_last_deprecated_spelling_wins(args, expected):
    """The spellings were one option, where the last value given won."""
    assert values(invoke(args))["org"] == expected


def test_current_flag_still_wins_after_forwarding():
    @click.command()
    @common_cli_config_options
    @resolve_credentials
    @click.pass_context
    def outer(ctx, opts):  # pylint: disable=unused-argument
        ctx.forward(inner)

    @click.command()
    @common_cli_config_options
    @resolve_credentials
    def inner(opts):
        click.echo(json.dumps({"org": opts.org}))

    result = invoke(["--workspace", "new", "--org", "old"], command=outer)

    assert values(result)["org"] == "new"


def test_alias_flag_wins_over_environment():
    result = invoke(["--org", "flag"], env={"CLOUDSMITH_WORKSPACE": "env"})

    assert values(result)["org"] == "flag"


@pytest.mark.parametrize(
    "env,key,expected,warning",
    [
        (
            {"CLOUDSMITH_ORG": "acme"},
            "org",
            "acme",
            "`CLOUDSMITH_ORG` is deprecated",
        ),
        (
            {"CLOUDSMITH_API_PROXY": "http://proxy:3128"},
            "proxy",
            "http://proxy:3128",
            "`CLOUDSMITH_API_PROXY` is deprecated",
        ),
        (
            {"CLOUDSMITH_WITHOUT_API_SSL_VERIFY": "1"},
            "ssl_verify",
            False,
            "`CLOUDSMITH_WITHOUT_API_SSL_VERIFY` is deprecated",
        ),
    ],
)
def test_environment_aliases_warn_and_still_work(env, key, expected, warning):
    result = invoke(env=env)

    assert values(result)[key] == expected
    assert warning in result.stderr


def test_ssl_environment_alias_names_its_replacement():
    result = invoke(env={"CLOUDSMITH_WITHOUT_API_SSL_VERIFY": "1"})

    assert "Use `CLOUDSMITH_SSL_VERIFY=0` instead." in result.stderr


@pytest.mark.parametrize(
    "args,env",
    [
        ([], {"CLOUDSMITH_SSL_VERIFY": "1"}),
        (["--ssl-verify"], {}),
    ],
)
def test_overridden_ssl_environment_alias_does_not_warn(args, env):
    result = invoke(args, env={"CLOUDSMITH_WITHOUT_API_SSL_VERIFY": "1", **env})

    assert values(result)["ssl_verify"] is True
    assert result.stderr == ""


def test_proxy_suffixes_environment_alias_warns():
    result = invoke(env={"CLOUDSMITH_ALLOWED_API_PROXY_SUFFIXES": "example.com"})

    assert "`CLOUDSMITH_ALLOWED_API_PROXY_SUFFIXES` is deprecated" in result.stderr
    assert "Use `CLOUDSMITH_ALLOWED_PROXY_SUFFIXES` instead." in result.stderr


def test_unused_environment_alias_does_not_warn():
    result = invoke(env={"CLOUDSMITH_ORG": "old", "CLOUDSMITH_WORKSPACE": "new"})

    assert values(result)["org"] == "new"
    assert result.stderr == ""


@pytest.mark.parametrize(
    "body,replacement",
    [
        ("org = acme", "workspace"),
        ("organization = acme", "workspace"),
        ("oidc_org = acme", "workspace"),
        ("api_proxy = http://proxy:3128", "proxy"),
        ("api_ssl_verify = false", "ssl_verify"),
    ],
)
def test_config_key_aliases_warn(isolated, body, replacement):
    (isolated / "config.ini").write_text(f"[default]\n{body}\n")
    key = body.split(" ", 1)[0]

    result = invoke()

    assert (
        result.stderr
        == deprecation.format_warning(
            f"The `{key}` key in config.ini", f"`{replacement}`"
        )
        + "\n"
    )


@pytest.mark.parametrize(
    "body",
    [
        "workspace = acme",
        "api_ssl_verify = true",
        "org =",
        "workspace = new\norg = old",
        "proxy = http://new:3128\napi_proxy = http://old:3128",
    ],
)
def test_config_keys_that_change_nothing_do_not_warn(isolated, body):
    (isolated / "config.ini").write_text(f"[default]\n{body}\n")

    assert invoke().stderr == ""


def test_profile_config_key_alias_warns(isolated):
    (isolated / "config.ini").write_text("[profile:ci]\norg = acme\n")

    result = invoke(["-P", "ci"])

    assert values(result)["org"] == "acme"
    assert "The `org` key in config.ini is deprecated" in result.stderr


@pytest.mark.parametrize(
    "body,key,expected",
    [
        ("[default]\norg = old\n[profile:ci]\nworkspace = new\n", "org", "new"),
        (
            "[default]\napi_proxy = http://old:3128\n"
            "[profile:ci]\nproxy = http://new:3128\n",
            "proxy",
            "http://new:3128",
        ),
        ("[default]\napi_ssl_verify = false\n[profile:ci]\n", "ssl_verify", True),
    ],
)
def test_profile_override_clears_default_alias_warning(isolated, body, key, expected):
    (isolated / "config.ini").write_text(body)

    result = invoke(["-P", "ci"])

    assert values(result)[key] == expected
    assert result.stderr == ""


def test_subcommand_inheriting_config_still_warns(isolated):
    """Like `mcp start`, which takes its config options from the `mcp` group."""
    (isolated / "config.ini").write_text("[default]\norg = acme\n")

    @click.group()
    @common_cli_config_options
    def group(opts):  # pylint: disable=unused-argument
        pass

    @group.command()
    @resolve_credentials
    def start(opts):
        click.echo(json.dumps({"org": opts.org}))

    result = invoke(["start"], command=group)

    assert values(result)["org"] == "acme"
    assert "The `org` key in config.ini is deprecated" in result.stderr


def test_each_warning_prints_once_per_run(isolated):
    (isolated / "config.ini").write_text("[default]\norg = acme\n")

    @click.group(invoke_without_command=True)
    @common_cli_config_options
    def group(opts):  # pylint: disable=unused-argument
        pass

    group.add_command(_report_command(), name="report")

    result = invoke(["report", "--org", "acme", "--org", "acme"], command=group)

    assert result.stderr.count("`--org` is deprecated") == 1
    assert result.stderr.count("The `org` key in config.ini is deprecated") == 1


def test_json_output_keeps_warnings_off_stdout():
    result = invoke(["--org", "acme", "-F", "json"])

    assert values(result)["org"] == "acme"
    assert "`--org` is deprecated" in result.stderr


@pytest.mark.parametrize("helper", sorted(deprecation.CREDENTIAL_HELPER_RUNTIMES))
def test_credential_helper_runtimes_do_not_warn(isolated, helper):
    (isolated / "config.ini").write_text("[default]\norg = acme\n")

    @click.group(name="credential-helper")
    def credential_helper():
        pass

    credential_helper.add_command(_report_command(), name=helper)
    command = click.Group(commands={"credential-helper": credential_helper})

    result = invoke(
        ["credential-helper", helper, "--org", "acme"],
        env={"CLOUDSMITH_API_PROXY": "http://proxy:3128"},
        command=command,
    )

    assert values(result)["org"] == "acme"
    assert result.stderr == ""


def test_credential_helper_management_commands_warn():
    @click.group(name="credential-helper")
    def credential_helper():
        pass

    credential_helper.add_command(_report_command(), name="install")
    command = click.Group(commands={"credential-helper": credential_helper})

    result = invoke(["credential-helper", "install", "--org", "acme"], command=command)

    assert "`--org` is deprecated" in result.stderr


def test_help_hides_the_deprecated_spellings():
    result = invoke(["--help"])

    for spelling in (
        "--org",
        "--organization",
        "--oidc-org",
        "--owner",
        "-o,",
        "--api-proxy",
        "--without-api-ssl-verify",
        "-S,",
        "--show-all",
    ):
        assert spelling not in result.stdout
    assert "--workspace" in result.stdout
