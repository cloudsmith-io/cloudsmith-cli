# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith credential-helper nuget` command and installer."""

from __future__ import annotations

import collections
import io
import json
import os
import sys
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import click.testing
import cloudsmith_api
import pytest

from ...core import keyring as core_keyring
from ...core.api.exceptions import ApiException
from ...core.credentials.models import CredentialResult
from ...credential_helpers.common import REFUSAL_MESSAGE
from ...credential_helpers.nuget.installer import NuGetInstaller
from ...credential_helpers.nuget.runtime import (
    PluginSession,
    is_plugin_mode,
    is_supported_source,
    negotiate_version,
    parse_timespan,
)
from ..commands.credential_helper.manage import install_cmd, list_cmd
from ..commands.credential_helper.nuget import nuget
from ..commands.main import main
from ..config import OPTIONS

CLOUDSMITH_FEED = "https://nuget.cloudsmith.io/acme/repo/v3/index.json"
CUSTOM_FEED = "https://nuget.acme.com/repo/v3/index.json"
NUGET_ORG = "https://api.nuget.org/v3/index.json"
FORMAT_DOMAINS = "cloudsmith_cli.credential_helpers.common.get_format_domains"
LAUNCHER = "nuget-plugin-cloudsmith"


@pytest.fixture()
def runner():
    """Return a CliRunner."""
    return click.testing.CliRunner()


@pytest.fixture()
def credential():
    """Return a resolved credential."""
    return CredentialResult(api_key="k_abc", source_name="test")


def _message(request_id, method, payload=None, message_type="Request") -> dict:
    message = {"RequestId": request_id, "Type": message_type, "Method": method}
    if payload is not None:
        message["Payload"] = payload
    return message


HANDSHAKE = _message(
    "h", "Handshake", {"ProtocolVersion": "2.0.0", "MinimumProtocolVersion": "1.0.0"}
)


def _credentials_request(uri=CLOUDSMITH_FEED) -> dict:
    return _message(
        "c",
        "GetAuthenticationCredentials",
        {"Uri": uri, "IsRetry": False, "IsNonInteractive": True},
    )


class _NuGetFeed:
    """NuGet's end of stdin: it sends Close or ends the input only after each answer.

    A message can be a raw line, which needs no answer.
    """

    def __init__(self, messages):
        self.messages = messages
        self.requests = collections.Counter()
        self.answers = collections.Counter()
        self.answered = threading.Condition()

    def record(self, send):
        """Wrap ``PluginSession._send`` so that the feed sees each answer."""

        def send_and_record(session, request_id, message_type, method, payload=None):
            send(session, request_id, message_type, method, payload)
            if message_type not in ("Request", "Progress"):
                with self.answered:
                    self.answers[request_id] += 1
                    self.answered.notify_all()

        return send_and_record

    def _wait_for_answers(self):
        with self.answered:
            self.answered.wait_for(lambda: self.answers >= self.requests, timeout=2)

    def lines(self):
        """Yield each message as the line that NuGet writes."""
        for message in self.messages:
            if isinstance(message, str):
                yield message + "\n"
                continue
            if message.get("Method") == "Close":
                self._wait_for_answers()
            elif message.get("Type") == "Request":
                self.requests[message["RequestId"]] += 1
            yield json.dumps(message, ensure_ascii=False) + "\n"
        self._wait_for_answers()


def _session(*messages, credential=None, workspace=None, stdout=None):
    """Run a plugin session over *messages*; return (code, stderr, responses)."""
    feed = _NuGetFeed(messages)
    stdout = io.StringIO() if stdout is None else stdout
    with patch.object(PluginSession, "_send", feed.record(PluginSession._send)):
        code, stderr = PluginSession(
            feed.lines(), stdout, credential=credential, workspace=workspace
        ).run()
    sent = [json.loads(line) for line in stdout.getvalue().splitlines()]
    return code, stderr, sent


def _run_cli(runner, args, *messages, command=nuget, encoding="utf-8") -> list[dict]:
    """Run the CLI over *messages* and return the messages on stdout."""
    feed = _NuGetFeed(messages)
    read_fd, write_fd = os.pipe()

    def write_feed():
        with open(write_fd, "w", encoding=encoding) as pipe:
            for line in feed.lines():
                pipe.write(line)
                pipe.flush()

    threading.Thread(target=write_feed, daemon=True).start()
    with (
        open(read_fd, "rb") as stdin,
        patch.object(PluginSession, "_send", feed.record(PluginSession._send)),
    ):
        result = runner.invoke(command, args=args, input=stdin, catch_exceptions=False)
    return [json.loads(line) for line in result.stdout.splitlines()]


def _responses(sent) -> dict:
    """Map RequestId -> message for everything the plugin answered."""
    return {m["RequestId"]: m for m in sent if m["Type"] != "Request"}


@pytest.mark.parametrize(
    "args,expected",
    [(["-Plugin"], True), (["/plugin"], True), (["-Uri", CLOUDSMITH_FEED], False)],
)
def test_is_plugin_mode(args, expected):
    assert is_plugin_mode(args) is expected


@pytest.mark.parametrize(
    "uri,workspace,expected",
    [
        (CLOUDSMITH_FEED, None, True),
        (NUGET_ORG, "acme", False),
        (CUSTOM_FEED, None, False),
        (CUSTOM_FEED, "acme", True),
        ("http://nuget.cloudsmith.io/acme/repo/v3/index.json", None, False),
        ("https://attacker.example?x=.cloudsmith.io", None, False),
        (123, None, False),
        ("https://attacker.example\\@nuget.cloudsmith.io/v3/index.json", None, False),
    ],
)
def test_is_supported_source(credential, uri, workspace, expected):
    """Only https Cloudsmith feeds, and NuGet domains of a Workspace, match."""
    with patch(FORMAT_DOMAINS, return_value=["nuget.acme.com"]):
        assert (
            is_supported_source(uri, credential=credential, workspace=workspace)
            is expected
        )


@pytest.mark.parametrize(
    "uri,expected",
    [
        (CUSTOM_FEED, True),
        (CLOUDSMITH_FEED, True),
        ("https://nuget.other.com/v3/index.json", False),
    ],
)
def test_is_supported_source_without_discovery(credential, uri, expected):
    """Explicit domains and Cloudsmith hosts match with no API lookup."""
    with patch(FORMAT_DOMAINS, side_effect=AssertionError("looked up")):
        assert (
            is_supported_source(
                uri,
                credential=credential,
                workspace="acme",
                domains={"nuget.acme.com"},
                discover=False,
            )
            is expected
        )


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"ProtocolVersion": "3.0.0", "MinimumProtocolVersion": "1.0.0"}, "2.0.0"),
        ({"ProtocolVersion": "1.0.0", "MinimumProtocolVersion": "1.0.0"}, None),
        ({"ProtocolVersion": "x"}, None),
    ],
)
def test_negotiate_version(payload, expected):
    assert negotiate_version(payload) == expected


def test_plugin_full_conversation(credential):
    code, stderr, sent = _session(
        HANDSHAKE,
        _message("i", "Initialize", {"RequestTimeout": "00:00:05"}),
        _message("o", "GetOperationClaims", {}),
        _credentials_request(),
        _message("x", "Close"),
        credential=credential,
    )
    responses = _responses(sent)

    assert (code, stderr) == (0, None)
    assert responses["h"]["Payload"] == {
        "ResponseCode": "Success",
        "ProtocolVersion": "2.0.0",
    }
    assert responses["i"]["Payload"] == {"ResponseCode": "Success"}
    assert responses["o"]["Payload"] == {"Claims": ["Authentication"]}
    assert responses["c"]["Payload"] == {
        "ResponseCode": "Success",
        "Username": "token",
        "Password": "k_abc",
        "AuthenticationTypes": ["Basic"],
    }
    assert "x" not in responses


def test_plugin_claims_no_download_operations(credential):
    claims = _message(
        "o",
        "GetOperationClaims",
        {"PackageSourceRepository": CLOUDSMITH_FEED, "ServiceIndex": "{}"},
    )
    _, _, sent = _session(claims, credential=credential)
    assert _responses(sent)["o"]["Payload"] == {"Claims": []}


def test_plugin_lookup_failure_is_not_found(credential, tmp_path):
    """A failed domain lookup declines the feed, so NuGet tries other sources."""
    with (
        patch(
            "cloudsmith_cli.credential_helpers.domains.get_cache_path",
            return_value=tmp_path / "acme.json",
        ),
        patch(
            "cloudsmith_cli.core.api.workspaces.list_domains",
            side_effect=ApiException(0, detail="Connection refused"),
        ),
    ):
        code, _, sent = _session(
            _credentials_request(CUSTOM_FEED), credential=credential, workspace="acme"
        )
    assert code == 0
    assert _responses(sent)["c"]["Payload"]["ResponseCode"] == "NotFound"


def test_plugin_reports_missing_credentials_for_a_cloudsmith_feed():
    code, stderr, sent = _session(_credentials_request())

    payload = _responses(sent)["c"]["Payload"]
    assert payload == {"ResponseCode": "Error", "Message": REFUSAL_MESSAGE}
    assert (code, stderr) == (1, REFUSAL_MESSAGE)


@pytest.mark.parametrize(
    "first_line,answered",
    [
        ("not json", {"c": "Response"}),
        (json.dumps(_message("u", "Unknown")), {"u": "Fault", "c": "Response"}),
        (
            json.dumps(
                _message("ours", "Handshake", {"ResponseCode": "Error"}, "Response")
            ),
            {},
        ),
    ],
    ids=["malformed-line", "unknown-method", "handshake-rejected"],
)
def test_plugin_session_handles_unexpected_messages(credential, first_line, answered):
    with patch(
        "cloudsmith_cli.credential_helpers.nuget.runtime.uuid.uuid4",
        return_value="ours",
    ):
        _, _, sent = _session(first_line, _credentials_request(), credential=credential)

    assert {m["RequestId"]: m["Type"] for m in sent[1:]} == answered


class _MessageWatcher(io.StringIO):
    """A stdout that sets ``seen`` when the plugin sends a message of one type."""

    def __init__(self, message_type):
        super().__init__()
        self.message_type = message_type
        self.seen = threading.Event()

    def write(self, text):
        if json.loads(text)["Type"] == self.message_type:
            self.seen.set()
        return super().write(text)


def test_plugin_sends_progress_while_a_request_runs(credential):
    """Progress before each Initialize deadline keeps NuGet waiting."""
    stdout = _MessageWatcher("Progress")
    initialize = _message("i", "Initialize", {"RequestTimeout": "00:00:00.0200000"})
    with patch(
        "cloudsmith_cli.credential_helpers.nuget.runtime.is_cloudsmith_domain",
        lambda *args, **kwargs: stdout.seen.wait(timeout=1),
    ):
        _, _, sent = _session(
            initialize,
            _credentials_request(CUSTOM_FEED),
            credential=credential,
            workspace="acme",
            stdout=stdout,
        )

    answers = [m for m in sent if m["RequestId"] == "c"]
    assert answers[0] == {
        "RequestId": "c",
        "Type": "Progress",
        "Method": "GetAuthenticationCredentials",
        "Payload": {},
    }
    assert {m["Type"] for m in answers[:-1]} == {"Progress"}
    assert answers[-1]["Type"] == "Response"
    assert answers[-1]["Payload"]["ResponseCode"] == "Success"


def test_plugin_answers_a_cancel_while_a_request_runs(credential):
    """A Cancel gets a Cancel at once, and the late result is not sent."""
    stdout = _MessageWatcher("Cancel")
    cancel = _message("c", "GetAuthenticationCredentials", message_type="Cancel")
    with patch(
        "cloudsmith_cli.credential_helpers.nuget.runtime.is_cloudsmith_domain",
        lambda *args, **kwargs: stdout.seen.wait(timeout=1),
    ):
        _, _, sent = _session(
            _credentials_request(CUSTOM_FEED),
            cancel,
            credential=credential,
            workspace="acme",
            stdout=stdout,
        )

    assert [(m["RequestId"], m["Type"]) for m in sent[1:]] == [("c", "Cancel")]


def _lines_then(lines, error):
    """Yield *lines* as NuGet's stdin, then raise *error* if it is given."""
    yield from lines
    if error is not None:
        raise error


@pytest.mark.parametrize(
    "after,error,code",
    [
        ([json.dumps(_message("x", "Close"))], None, 0),
        ([], None, 0),
        ([], OSError("stdin closed"), 1),
    ],
    ids=["close", "end-of-input", "stdin-error"],
)
def test_plugin_ends_the_session_while_a_request_runs(credential, after, error, code):
    """NuGet has gone, so the plugin drops the late answer and does not wait for it."""
    entered, release = threading.Event(), threading.Event()
    daemon = []

    def slow_lookup(*args, **kwargs):
        daemon.append(threading.current_thread().daemon)
        entered.set()
        return release.wait(timeout=1)

    lines = [json.dumps(_credentials_request(CUSTOM_FEED)), *after]
    stdout = io.StringIO()
    with patch(
        "cloudsmith_cli.credential_helpers.nuget.runtime.is_cloudsmith_domain",
        slow_lookup,
    ):
        result = PluginSession(
            _lines_then(lines, error), stdout, credential=credential, workspace="acme"
        ).run()
        assert entered.wait(timeout=1)
        release.set()

    sent = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert result == (code, None)
    assert [m["Method"] for m in sent] == ["Handshake"]
    assert daemon == [True]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_plugin_resolves_again_after_a_failed_resolution(credential):
    """A first failure does not stay, so a later request can get the credential."""
    resolve = Mock(side_effect=[None, credential])
    session = PluginSession(io.StringIO(), io.StringIO(), refresh_credential=resolve)
    payload = _credentials_request()["Payload"]

    first = session.handle_request("GetAuthenticationCredentials", payload)
    second = session.handle_request("GetAuthenticationCredentials", payload)

    assert first["ResponseCode"] == "Error"
    assert second["Password"] == "k_abc"


def test_plugin_without_discovery_declines_a_feed_before_it_resolves(credential):
    """The feed of another provider does not wait for a credential."""
    resolve = Mock(return_value=credential)
    session = PluginSession(
        io.StringIO(), io.StringIO(), refresh_credential=resolve, discover=False
    )
    payload = _credentials_request(CUSTOM_FEED)["Payload"]

    response = session.handle_request("GetAuthenticationCredentials", payload)

    assert response["ResponseCode"] == "NotFound"
    assert not resolve.called


def test_plugin_faults_a_request_that_fails(credential):
    """A request that raises gets a Fault, so NuGet does not wait for it."""
    with patch(
        "cloudsmith_cli.credential_helpers.nuget.runtime.is_cloudsmith_domain",
        side_effect=RuntimeError("lookup failed"),
    ):
        _, _, sent = _session(
            _credentials_request(CUSTOM_FEED), credential=credential, workspace="acme"
        )

    assert _responses(sent)["c"]["Type"] == "Fault"


@pytest.mark.parametrize(
    "value,expected",
    [("00:00:05", 5.0), ("1.02:03:04.5", 93784.5), ("5", None), (None, None)],
)
def test_parse_timespan(value, expected):
    assert parse_timespan(value) == expected


class _BrokenPipe(io.StringIO):
    def write(self, _):
        raise BrokenPipeError("gone")


def test_plugin_transport_failure_exits_without_a_message(credential):
    """NuGet can close the pipes before the handshake; that is not a credential error."""
    code, stderr = PluginSession(
        io.StringIO(), _BrokenPipe(), credential=credential
    ).run()
    assert (code, stderr) == (1, None)


def test_cli_speaks_the_plugin_protocol(runner):
    sent = _run_cli(
        runner, ["-k", "k_abc", "-Plugin"], HANDSHAKE, _credentials_request()
    )

    assert sent[0]["Method"] == "Handshake"
    assert _responses(sent)["c"]["Payload"]["Password"] == "k_abc"


def test_cli_reads_input_that_is_not_utf8(runner):
    """On Windows, NuGet writes to the plugin in the console code page."""
    proxy_login = _message("p", "SetCredentials", {"ProxyPassword": "\u00e9t\u00e9"})
    sent = _run_cli(
        runner,
        ["-k", "k_abc", "-Plugin"],
        proxy_login,
        _credentials_request(),
        encoding="cp1252",
    )

    assert _responses(sent)["c"]["Payload"]["Password"] == "k_abc"


def test_cli_looks_up_domains_with_the_proxy_and_tls_settings(runner, tmp_path):
    """A domain-cache miss reaches the API through the configured proxy."""
    seen = {}

    def list_domains(workspace, credential=None):
        config = cloudsmith_api.Configuration()
        seen.update(proxy=config.proxy, verify_ssl=config.verify_ssl)
        record = {"domain_name": "nuget.acme.com", "domain_scope": "WORKSPACE"}
        return [{**record, "domain_type": "NATIVE_NUGET"}]

    with (
        patch(
            "cloudsmith_cli.credential_helpers.domains.get_cache_path",
            return_value=tmp_path / "acme.json",
        ),
        patch("cloudsmith_cli.core.api.workspaces.list_domains", list_domains),
    ):
        args = ["-k", "k_abc", "-w", "acme", "--api-proxy", "http://proxy:3128", "-S"]
        sent = _run_cli(
            runner, [*args, "--", "-Plugin"], _credentials_request(CUSTOM_FEED)
        )

    assert seen == {"proxy": "http://proxy:3128", "verify_ssl": False}
    assert _responses(sent)["c"]["Payload"]["ResponseCode"] == "Success"


@pytest.mark.parametrize(
    "extra_args", [[], ["--api-headers", "Authorization=user:pass"]]
)
def test_cli_writes_only_protocol_messages_to_stdout_with_debug(runner, extra_args):
    """Debug output goes to stderr, so it cannot break the protocol stream.

    With --debug, http.client prints each API request with print().
    """

    def lookup_with_http_debug(*args, **kwargs):
        print("send: b'GET /v2/workspaces/acme/domains/ HTTP/1.1'")
        return True

    args = ["--debug", "credential-helper", "nuget", "-k", "k_abc", *extra_args]
    with patch(
        "cloudsmith_cli.credential_helpers.nuget.runtime.is_cloudsmith_domain",
        lookup_with_http_debug,
    ):
        sent = _run_cli(
            runner, [*args, "--", "-Plugin"], _credentials_request(), command=main
        )
    assert _responses(sent)["c"]["Payload"]["Password"] == "k_abc"


def test_cli_retries_with_a_freshly_resolved_credential(runner, credential):
    retry = _credentials_request()
    retry["RequestId"] = "r"
    retry["Payload"]["IsRetry"] = True
    renewed = CredentialResult(api_key="k_renewed", source_name="test")
    with patch(
        "cloudsmith_cli.cli.commands.credential_helper.nuget.CredentialProviderChain"
    ) as chain:
        chain.return_value.resolve.side_effect = [credential, renewed]
        sent = _run_cli(
            runner, ["-k", "k_abc", "--", "-Plugin"], _credentials_request(), retry
        )

    assert _responses(sent)["c"]["Payload"]["Password"] == "k_abc"
    assert _responses(sent)["r"]["Payload"]["Password"] == "k_renewed"


def test_cli_resolves_the_credential_at_the_first_credentials_request(runner):
    """The handshake does not wait for a slow credential, such as an OIDC exchange."""
    oidc = CredentialResult(api_key="k_oidc", source_name="test")
    with (
        patch("cloudsmith_cli.cli.decorators.CredentialProviderChain") as chain,
        patch(
            "cloudsmith_cli.cli.commands.credential_helper.nuget.CredentialProviderChain",
            chain,
        ),
    ):
        chain.return_value.resolve.return_value = oidc
        _run_cli(runner, ["--", "-Plugin"], HANDSHAKE)
        assert not chain.return_value.resolve.called

        requests = (_credentials_request(), _credentials_request())
        sent = _run_cli(runner, ["--", "-Plugin"], *requests)

    assert chain.return_value.resolve.call_count == 1
    assert _responses(sent)["c"]["Payload"]["Password"] == "k_oidc"


@pytest.mark.parametrize("non_interactive", [True, False])
def test_cli_passes_the_interaction_policy_to_the_keyring(runner, non_interactive):
    """When NuGet forbids prompts, the keyring does not ask for its password."""
    request = _credentials_request()
    request["Payload"]["IsNonInteractive"] = non_interactive
    no_prompt = []
    with patch(
        "cloudsmith_cli.cli.commands.credential_helper.nuget.CredentialProviderChain"
    ) as chain:
        chain.return_value.resolve.side_effect = lambda context: no_prompt.append(
            core_keyring.current_settings().no_prompt
        )
        _run_cli(runner, ["--", "-Plugin"], request)

    assert no_prompt == [non_interactive]


def test_cli_keeps_the_resolved_credential_on_the_options(runner):
    """Telemetry redacts ``opts.credential``, so the late credential goes there."""
    _run_cli(runner, ["-k", "k_abc", "--", "-Plugin"], _credentials_request())
    assert OPTIONS.value.credential.api_key == "k_abc"


def test_cli_matches_explicit_domains(runner):
    args = ["-k", "k_abc", "-w", "acme", "--domain", "NuGet.Acme.com", "--no-discover"]
    with patch(FORMAT_DOMAINS, side_effect=AssertionError("looked up")):
        sent = _run_cli(
            runner, [*args, "--", "-Plugin"], _credentials_request(CUSTOM_FEED)
        )

    assert _responses(sent)["c"]["Payload"]["Password"] == "k_abc"


def test_cli_without_nuget_args_prints_usage(runner):
    result = runner.invoke(nuget, args=["-k", "k_abc"], catch_exceptions=False)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "credential-helper install nuget" in result.stderr


@pytest.fixture()
def bin_dir(tmp_path, monkeypatch):
    """Return a launcher directory that is on PATH."""
    path = tmp_path / "bin"
    monkeypatch.setenv("PATH", str(path))
    for name in [name for name in os.environ if name.startswith("CLOUDSMITH_")]:
        monkeypatch.delenv(name)
    monkeypatch.delattr(sys, "frozen", raising=False)
    return path


def test_installer_writes_the_launcher(bin_dir):
    actions = NuGetInstaller().install(bin_dir=str(bin_dir))

    assert (bin_dir / LAUNCHER).read_text() == (
        '#!/bin/sh\nexec cloudsmith credential-helper nuget -- "$@"\n'
    )
    assert actions == [f"wrote launcher {bin_dir / LAUNCHER}"]


def test_installer_dry_run_and_uninstall_of_a_missing_launcher(bin_dir):
    installer = NuGetInstaller()

    assert installer.install(bin_dir=str(bin_dir), dry_run=True) == [
        f"would write launcher {bin_dir / LAUNCHER}"
    ]
    assert installer.uninstall(bin_dir=str(bin_dir)) == [
        f"launcher not found at {bin_dir / LAUNCHER} (nothing to remove)"
    ]


@pytest.fixture()
def on_windows():
    with (
        patch(
            "cloudsmith_cli.credential_helpers.launchers.is_windows", return_value=True
        ),
        patch(
            "cloudsmith_cli.credential_helpers.nuget.installer.is_windows",
            return_value=True,
        ),
    ):
        yield


@pytest.mark.usefixtures("on_windows")
def test_installer_uses_a_bat_launcher_on_windows(bin_dir):
    """NuGet only discovers .exe and .bat plugins on Windows, not .cmd."""
    installer = NuGetInstaller()
    installer.install(
        bin_dir=str(bin_dir),
        domains=("nuget.acme.com",),
        launcher_env={"CLOUDSMITH_WORKSPACE": "acme"},
    )
    assert (bin_dir / f"{LAUNCHER}.bat").read_bytes() == (
        b"@echo off\r\n"
        b"setlocal DisableDelayedExpansion\r\n"
        b'set "CLOUDSMITH_WORKSPACE=acme"\r\n'
        b'cloudsmith credential-helper nuget --domain "nuget.acme.com" -- %*\r\n'
    )
    installer.uninstall(bin_dir=str(bin_dir))
    assert not (bin_dir / f"{LAUNCHER}.bat").exists()


def test_installer_passes_explicit_domains_to_the_plugin(bin_dir):
    """NuGet sends every feed to the plugin, so the launcher names the hosts."""
    NuGetInstaller().install(
        bin_dir=str(bin_dir), domains=("nuget.acme.com", "a b"), discover=False
    )
    assert (
        "exec cloudsmith credential-helper nuget --domain nuget.acme.com "
        "--domain 'a b' --no-discover -- \"$@\""
    ) in (bin_dir / LAUNCHER).read_text()


def test_list_command_reports_the_launcher(runner, bin_dir, monkeypatch):
    """`list` finds the launcher where `install` puts it by default."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: bin_dir.parent))
    before = runner.invoke(list_cmd, args=["-F", "json"], catch_exceptions=False)
    runner.invoke(install_cmd, args=["nuget"], catch_exceptions=False)
    after = runner.invoke(list_cmd, args=["-F", "json"], catch_exceptions=False)

    def nuget_entry(result):
        data = json.loads(result.stdout)["data"]
        return next(entry for entry in data if entry["helper"] == "nuget")

    default_dir = bin_dir.parent / ".cloudsmith" / "bin"
    assert nuget_entry(before)["launcher"] is None
    assert nuget_entry(after)["launcher"] == str(default_dir / LAUNCHER)
    assert nuget_entry(after)["hosts"] == ["all Cloudsmith NuGet feeds (nuget-plugin)"]


def test_install_command_keeps_install_time_settings(runner, bin_dir):
    result = runner.invoke(
        install_cmd,
        args=["nuget", "--bin-dir", str(bin_dir), "-w", "acme"],
        env={"CLOUDSMITH_API_KEY": "k_secret"},
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert (bin_dir / LAUNCHER).read_text() == (
        "#!/bin/sh\nexport CLOUDSMITH_WORKSPACE=acme\n"
        'exec cloudsmith credential-helper nuget -- "$@"\n'
    )
