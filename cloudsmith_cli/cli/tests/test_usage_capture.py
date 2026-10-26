from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

from cloudsmith_cli.cli import usage_capture
from cloudsmith_cli.cli.command import AliasGroup

CAPTURED = {}


@click.group(cls=AliasGroup)
def app():
    pass


@app.command(aliases=["ls"])
@click.option("-w", "--workspace", "--org", "workspace", envvar="CLOUDSMITH_WORKSPACE")
@click.option("-F", "--output-format", "output")
@click.argument("name", required=False)
@click.pass_context
def listing(ctx, workspace, output, name):
    # Collect inside the run: env vars and contexts are live here.
    CAPTURED["facts"] = usage_capture.collect_facts(
        ctx.meta, outcome="success", exit_code=0, duration_ms=5, nested=False
    )


@pytest.fixture(autouse=True)
def isolated_config(telemetry_config_dir):  # pylint: disable=unused-argument
    CAPTURED.clear()


def _run(args, env=None):
    CliRunner().invoke(app, args, env=env or {}, catch_exceptions=False)
    return CAPTURED["facts"]


def test_typed_spellings_not_values():
    tokens = ["-w", "acme", "-Fjson", "--org=x", "--", "-w"]
    assert usage_capture.match_typed_flags(listing.params, tokens) == [
        "--org",
        "-F",
        "-w",
    ]


@click.command()
@click.option("-v", "--verbose", is_flag=True)
@click.option("-c", "--count", count=True)
@click.option("-S", "--without-api-ssl-verify", is_flag=True)
@click.option("-P", "--profile")
def clustered(verbose, count, without_api_ssl_verify, profile):
    pass


@pytest.mark.parametrize(
    "token, expected",
    [
        # Flags in a cluster are all seen, as Click applies them all.
        ("-vS", ["-S", "-v"]),
        ("-cvc", ["-c", "-v"]),
        # An option that takes a value consumes the rest of the token.
        ("-vPprivate", ["-P", "-v"]),
        ("-PvS", ["-P"]),
        # An undeclared character stops the expansion (Click rejects it).
        ("-vxS", ["-v"]),
    ],
)
def test_short_option_clusters_are_expanded(token, expected):
    assert usage_capture.match_typed_flags(clustered.params, [token]) == expected


def test_clustered_profile_and_ssl_off_reach_the_gates():
    typed = usage_capture.match_typed_flags(clustered.params, ["-vPprivate", "-vS"])
    assert usage_capture.CONFIG_SPELLINGS & set(typed)
    assert usage_capture.resolve_ssl_verify(None, typed) is False


def test_facts_from_a_run():
    facts = _run(["ls", "-w", "secret-ws", "-F", "json", "pkg-name"])
    assert facts.command == "listing"
    assert facts.aliases_used == ["ls"]
    assert set(facts.flags) == {"workspace", "output"}
    assert facts.flags_typed == ["-F", "-w"]
    assert "name" not in facts.setting_sources  # arguments are not settings
    assert "secret-ws" not in repr(facts) and "pkg-name" not in repr(facts)


def test_env_sources_report_names_only():
    facts = _run(["listing"], env={"CLOUDSMITH_WORKSPACE": "secret-ws"})
    assert facts.envvars == ["CLOUDSMITH_WORKSPACE"]
    assert facts.setting_sources.get("workspace") == "env"
    assert "secret-ws" not in repr(facts)


@app.command()
@click.option("--proxy", envvar=["CLOUDSMITH_PROXY", "CLOUDSMITH_API_PROXY"])
@click.pass_context
def proxied(ctx, proxy):
    CAPTURED["facts"] = usage_capture.collect_facts(
        ctx.meta, outcome="success", exit_code=0, duration_ms=5, nested=False
    )


def test_an_empty_env_var_is_not_reported_as_the_source():
    # Click skips the empty CLOUDSMITH_PROXY and uses CLOUDSMITH_API_PROXY.
    facts = _run(
        ["proxied"], env={"CLOUDSMITH_PROXY": "", "CLOUDSMITH_API_PROXY": "secret"}
    )
    assert facts.envvars == ["CLOUDSMITH_API_PROXY"]
    assert "secret" not in repr(facts)


def _facts_with_typed(typed, outcome, exit_code):
    meta = {usage_capture.META_KEY: {"contexts": [], "typed": typed, "aliases": []}}
    return usage_capture.collect_facts(
        meta, outcome=outcome, exit_code=exit_code, duration_ms=1, nested=False
    )


def test_typed_help_after_a_successful_exit_is_help():
    assert _facts_with_typed(["--help"], "success", 0).outcome == "help"


@pytest.mark.parametrize("outcome", ["usage_error", "click_error", "api_error"])
def test_typed_help_never_hides_a_failure(outcome):
    # e.g. `whoami --no-such-flag --help` fails parsing before help is shown.
    assert _facts_with_typed(["--help"], outcome, 2).outcome == outcome


def test_help_spelling_is_seen():
    tokens = ["--help"]
    params = listing.get_params(click.Context(listing))
    assert usage_capture.match_typed_flags(params, tokens) == ["--help"]


def test_every_command_in_the_cli_is_tracked():
    import importlib
    import pkgutil

    from cloudsmith_cli.cli import commands
    from cloudsmith_cli.cli.commands.main import main

    for info in pkgutil.walk_packages(
        commands.__path__, prefix=commands.__name__ + "."
    ):
        importlib.import_module(info.name)

    def walk(cmd, path):
        assert isinstance(cmd, usage_capture.TrackingMixin), " ".join(path)
        for name, sub in getattr(cmd, "commands", {}).items():
            walk(sub, path + [name])

    walk(main, [])


def test_collect_facts_does_not_read_config_files(monkeypatch):
    from cloudsmith_cli.cli import config_sources

    def explode(**_):
        raise AssertionError("config files read before the telemetry gates")

    monkeypatch.setattr(config_sources, "detect", explode)
    facts = _run(["listing"], env={"CLOUDSMITH_WORKSPACE": "x"})
    assert facts.setting_sources == {"workspace": "env"}


def test_deferred_sources_return_the_config_file_sources(monkeypatch):
    from cloudsmith_cli.cli import config_sources

    monkeypatch.setattr(
        config_sources, "detect", lambda **_: {"workspace": "config_file"}
    )
    facts = _run(["listing"])
    assert facts.deferred_sources() == {"workspace": "config_file"}


def test_a_parse_outside_a_run_pins_nothing():
    assert usage_capture._RUN["depth"] == 0  # pylint: disable=protected-access
    CliRunner().invoke(app, ["listing"], catch_exceptions=False)
    assert usage_capture.current_root_meta() is None


def test_session_env_names_match_the_option_declarations():
    from cloudsmith_cli.cli.commands import list_

    envvars = {p.name: p.envvar for p in list_.repos.params}
    assert envvars["api_host"] == usage_capture.API_HOST_ENV
    assert envvars["ssl_verify"] == usage_capture.SSL_VERIFY_ENV
    assert envvars["without_api_ssl_verify"] == usage_capture.WITHOUT_SSL_VERIFY_ENV
    spellings = {s for p in list_.repos.params for s in p.opts + p.secondary_opts}
    assert usage_capture.API_HOST_SPELLINGS <= spellings
    assert usage_capture.SSL_OFF_SPELLINGS <= spellings


def test_session_resolved_only_for_the_leaf_or_its_descendants():
    root = click.Context(click.Group("root"))
    group = click.Context(click.Group("list"), parent=root)
    leaf = click.Context(click.Command("repos"), parent=group)
    forwarded = click.Context(click.Command("get"), parent=leaf)
    unrelated = click.Context(click.Command("other"), parent=root)
    contexts = [root, group, leaf]

    def resolved(session):
        store = {"contexts": contexts, "session": session}
        return usage_capture._session_resolved(store)  # pylint: disable=protected-access

    assert resolved(leaf) is True
    assert resolved(forwarded) is True  # ctx.forward / ctx.invoke sub-context
    assert resolved(group) is False  # set up before the leaf parsed its flags
    assert resolved(root) is False
    assert resolved(unrelated) is False
    assert resolved(None) is False
    assert usage_capture._session_resolved({"session": leaf}) is False  # pylint: disable=protected-access


def test_config_resolved_only_for_the_leaf_or_its_descendants():
    root = click.Context(click.Group("root"))
    group = click.Context(click.Group("list"), parent=root)
    leaf = click.Context(click.Command("repos"), parent=group)
    forwarded = click.Context(click.Command("get"), parent=leaf)
    contexts = [root, group, leaf]

    def resolved(config_ctx):
        store = {"contexts": contexts, "config": config_ctx}
        return usage_capture._config_resolved(store)  # pylint: disable=protected-access

    assert resolved(leaf) is True
    assert resolved(forwarded) is True
    assert resolved(group) is False  # loaded before the leaf parsed its flags
    assert resolved(root) is False
    assert resolved(None) is False


def test_config_spellings_match_the_option_declarations():
    from cloudsmith_cli.cli.commands import list_

    spellings = {
        s
        for p in list_.repos.params
        if p.name in ("config_file", "profile")
        for s in p.opts + p.secondary_opts
    }
    assert usage_capture.CONFIG_SPELLINGS == spellings


#: Options of the shared decorators that are not settings, so they have no
#: ``source_<setting>``. Every other option must alias onto ALLOWED_SETTINGS.
NOT_SETTINGS = frozenset(
    {
        "debug",  # per-run output switches
        "verbose",
        "no_color_env",  # env plumbing for colour; the names land in envvars
        "force_color_env",
        "term_env",
        "allowed_api_host_suffixes",  # hidden, internal trust lists
        "allowed_proxy_suffixes",
        "oidc_discovery_disabled",  # no config.ini key
        "without_rate_limit",  # API client tuning, no config.ini key
        "rate_limit_warning",
        "error_retry_max",
        "error_retry_backoff",
        "error_retry_codes",
    }
)


@pytest.mark.parametrize(
    "name",
    [
        "common_cli_config_options",
        "common_cli_output_options",
        "common_api_auth_options",
        "initialise_session",
        "resolve_credentials",  # holds -w/--workspace (``org``)
        "initialise_api",
    ],
)
def test_every_shared_option_is_a_setting_or_explicitly_not(name):
    from cloudsmith_cli.cli import decorators
    from cloudsmith_cli.core.usage import event

    decorator = getattr(decorators, name)
    command = click.command()(decorator(lambda **kwargs: None))
    for param in command.params:
        setting = event.SETTING_ALIASES.get(param.name, param.name)
        assert setting in event.ALLOWED_SETTINGS or param.name in NOT_SETTINGS, (
            param.name
        )


def test_record_credential_keeps_the_last_resolved_source():
    store_ctx = click.Context(click.Command("x"))
    usage_capture.record_credential(store_ctx, SimpleNamespace(source_name="env_var"))
    usage_capture.record_credential(store_ctx, None)
    assert store_ctx.meta[usage_capture.META_KEY]["auth_source"] == "env_var"
    usage_capture.record_credential(
        store_ctx, SimpleNamespace(source_name="credentials_file")
    )
    assert store_ctx.meta[usage_capture.META_KEY]["auth_source"] == "credentials_file"
