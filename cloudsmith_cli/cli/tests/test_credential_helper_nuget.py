# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith credential-helper nuget` command and installer."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import click.testing
import pytest

from ...core.api.exceptions import ApiException
from ...core.credentials.models import CredentialResult
from ...credential_helpers.backends import BackendKind
from ...credential_helpers.custom_domains import CustomDomain
from ...credential_helpers.default_domains import DomainType
from ...credential_helpers.nuget.installer import NuGetInstaller, NuGetInstallError
from ...credential_helpers.nuget.runtime import (
    _REFUSAL_MESSAGE,
    PROTOCOL_VERSION,
    PluginSession,
    is_plugin_mode,
    is_supported_source,
    negotiate_version,
)
from ..commands.credential_helper.manage import install_cmd
from ..commands.credential_helper.nuget import nuget

CLOUDSMITH_FEED = "https://nuget.cloudsmith.io/acme/repo/v3/index.json"
CUSTOM_FEED = "https://nuget.acme.com/v3/index.json"
NUGET_ORG = "https://api.nuget.org/v3/index.json"
FORMAT_DOMAINS = "cloudsmith_cli.credential_helpers.common.get_format_domains"
INSTALLER_DOMAINS = (
    "cloudsmith_cli.credential_helpers.nuget.installer.get_format_domains"
)
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


def _session(*messages, credential=None, workspace=None):
    """Run a plugin session over *messages*; return (code, stderr, responses)."""
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    stdout = io.StringIO()
    code, stderr = PluginSession(
        stdin, stdout, credential=credential, workspace=workspace
    ).run()
    sent = [json.loads(line) for line in stdout.getvalue().splitlines()]
    return code, stderr, sent


def _responses(sent) -> dict:
    """Map RequestId -> message for everything the plugin answered."""
    return {m["RequestId"]: m for m in sent if m["Type"] != "Request"}


@pytest.fixture()
def failing_lookup(tmp_path):
    """Make the custom-domain API call fail as the CLI's REST client does."""
    with (
        patch(
            "cloudsmith_cli.credential_helpers.custom_domains.get_cache_path",
            return_value=tmp_path / "acme.json",
        ),
        patch("cloudsmith_cli.core.api.init.initialise_api"),
        patch(
            "cloudsmith_cli.core.api.orgs.list_custom_domains",
            side_effect=ApiException(0, detail="Connection refused"),
        ),
    ):
        yield


@pytest.mark.parametrize(
    "args,expected",
    [(["-Plugin"], True), (["/plugin"], True), (["-Uri", CLOUDSMITH_FEED], False)],
)
def test_is_plugin_mode(args, expected):
    assert is_plugin_mode(args) is expected


@pytest.mark.parametrize(
    "uri,kwargs,expected",
    [
        (CLOUDSMITH_FEED, {}, True),
        (NUGET_ORG, {}, False),
        (None, {}, False),
        (CUSTOM_FEED, {}, False),
        (
            "http://nuget.cloudsmith.io/acme/repo/v3/index.json",
            {"workspace": "acme", "extra_domains": ("nuget.acme.com",)},
            False,
        ),
        (
            "http://nuget.acme.com/v3/index.json",
            {"workspace": "acme", "extra_domains": ("nuget.acme.com",)},
            False,
        ),
    ],
)
def test_is_supported_source(credential, uri, kwargs, expected):
    """Only https Cloudsmith feeds, and custom domains of a Workspace, match."""
    with patch(FORMAT_DOMAINS, return_value=["nuget.acme.com"]):
        assert is_supported_source(uri, credential=credential, **kwargs) is expected


def test_custom_domains_are_matched_with_the_nuget_backend_kind(credential):
    with patch(FORMAT_DOMAINS, return_value=["nuget.acme.com"]) as mock_domains:
        assert is_supported_source(CUSTOM_FEED, credential=credential, workspace="acme")
    assert mock_domains.call_args.args == ("acme", BackendKind.NUGET)


@pytest.mark.parametrize(
    "extra_domains,default_hosts",
    [(("NuGet.Acme.com",), []), ((), ["nuget.acme.com"])],
    ids=["domain-option", "configured-default-host"],
)
def test_trusted_hosts_need_no_lookup(credential, extra_domains, default_hosts):
    with (
        patch(
            "cloudsmith_cli.credential_helpers.nuget.runtime.default_hosts",
            return_value=default_hosts,
        ),
        patch(FORMAT_DOMAINS) as mock_domains,
    ):
        assert is_supported_source(
            CUSTOM_FEED, credential=credential, extra_domains=extra_domains
        )
    mock_domains.assert_not_called()


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"ProtocolVersion": "2.0.0", "MinimumProtocolVersion": "1.0.0"}, "2.0.0"),
        ({"ProtocolVersion": "3.0.0", "MinimumProtocolVersion": "1.0.0"}, "2.0.0"),
        ({"ProtocolVersion": "1.0.0", "MinimumProtocolVersion": "1.0.0"}, None),
        ({"ProtocolVersion": "2.0.0", "MinimumProtocolVersion": "3.0.0"}, None),
        ({"ProtocolVersion": "x"}, None),
        (None, None),
    ],
)
def test_negotiate_version(payload, expected):
    assert negotiate_version(payload) == expected


def test_plugin_sends_its_handshake_before_reading(credential):
    """The handshake is symmetric: NuGet waits for the plugin's own request."""

    class AssertHandshakeFirst(io.StringIO):
        def __iter__(self):
            sent = json.loads(stdout.getvalue().splitlines()[0])
            assert (sent["Type"], sent["Method"]) == ("Request", "Handshake")
            assert sent["Payload"]["ProtocolVersion"] == PROTOCOL_VERSION
            return super().__iter__()

    stdout = io.StringIO()
    code, _ = PluginSession(
        AssertHandshakeFirst(""), stdout, credential=credential
    ).run()
    assert code == 0


def test_plugin_full_conversation(credential):
    code, stderr, sent = _session(
        HANDSHAKE,
        _message("i", "Initialize", {"RequestTimeout": "00:00:05"}),
        _message("l", "SetLogLevel", {"LogLevel": "Minimal"}),
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
    assert responses["l"]["Payload"] == {"ResponseCode": "Success"}
    assert responses["o"]["Payload"] == {"Claims": ["Authentication"]}
    assert responses["c"]["Payload"] == {
        "ResponseCode": "Success",
        "Username": "token",
        "Password": "k_abc",
        "AuthenticationTypes": ["Basic"],
    }
    assert "x" not in responses


@pytest.mark.parametrize(
    "message,expected",
    [
        (
            _message(
                "o",
                "GetOperationClaims",
                {"PackageSourceRepository": CLOUDSMITH_FEED, "ServiceIndexJson": "{}"},
            ),
            {"Claims": []},
        ),
        (
            _message(
                "o",
                "Handshake",
                {"ProtocolVersion": "1.0.0", "MinimumProtocolVersion": "1.0.0"},
            ),
            {"ResponseCode": "Error"},
        ),
    ],
    ids=["no-claims-for-download-source", "incompatible-handshake"],
)
def test_plugin_answers(credential, message, expected):
    _, _, sent = _session(message, credential=credential)
    assert _responses(sent)["o"]["Payload"] == expected


def test_plugin_declines_a_foreign_feed(credential):
    code, _, sent = _session(_credentials_request(NUGET_ORG), credential=credential)

    assert code == 0
    assert _responses(sent)["c"]["Payload"]["ResponseCode"] == "NotFound"


@pytest.mark.usefixtures("failing_lookup")
def test_plugin_lookup_failure_is_not_found(credential):
    code, _, sent = _session(
        _credentials_request(CUSTOM_FEED), credential=credential, workspace="acme"
    )
    assert code == 0
    assert _responses(sent)["c"]["Payload"]["ResponseCode"] == "NotFound"


def test_plugin_reports_missing_credentials_for_a_cloudsmith_feed():
    code, stderr, sent = _session(_credentials_request())

    payload = _responses(sent)["c"]["Payload"]
    assert payload == {"ResponseCode": "Error", "Message": _REFUSAL_MESSAGE}
    assert (code, stderr) == (1, _REFUSAL_MESSAGE)


def test_plugin_faults_unknown_requests(credential):
    _, _, sent = _session(_message("u", "CopyNupkgFile", {}), credential=credential)

    fault = _responses(sent)["u"]
    assert fault["Type"] == "Fault"
    assert "CopyNupkgFile" in fault["Payload"]["Message"]


def test_plugin_ignores_noise(credential):
    """Blank and malformed lines, progress and cancel messages need no answer."""
    noise = [
        _message("p", "GetAuthenticationCredentials", {}, message_type="Progress"),
        _message("q", "Handshake", message_type="Cancel"),
        _credentials_request(),
    ]
    stdin = io.StringIO(
        "\nnot json\n[1, 2]\n" + "".join(json.dumps(m) + "\n" for m in noise)
    )
    stdout = io.StringIO()
    code, _ = PluginSession(stdin, stdout, credential=credential).run()

    sent = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert code == 0
    assert set(_responses(sent)) == {"c"}


def test_plugin_stops_when_nuget_rejects_its_handshake(credential):
    stdin = io.StringIO()
    stdout = io.StringIO()
    session = PluginSession(stdin, stdout, credential=credential)
    rejected = _message(
        session._handshake_id, "Handshake", {"ResponseCode": "Error"}, "Response"
    )
    stdin.write("\n".join(json.dumps(m) for m in (rejected, _credentials_request())))
    stdin.seek(0)

    code, _ = session.run()

    sent = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert code == 0
    assert _responses(sent) == {}


class _BrokenPipe(io.StringIO):
    def write(self, _):
        raise BrokenPipeError("gone")


def _closed_stream():
    stream = io.StringIO()
    stream.close()
    return stream


@pytest.mark.parametrize(
    "make_stdout", [_BrokenPipe, _closed_stream], ids=["broken-pipe", "closed"]
)
def test_plugin_transport_failure_degrades_to_a_clean_exit(credential, make_stdout):
    code, stderr = PluginSession(
        io.StringIO(), make_stdout(), credential=credential
    ).run()
    assert (code, stderr) == (1, _REFUSAL_MESSAGE)


@pytest.mark.parametrize(
    "args",
    [["-k", "k_abc", "--", "-Plugin"], ["-k", "k_abc", "-Plugin"]],
    ids=["after-separator", "without-separator"],
)
def test_cli_speaks_the_plugin_protocol(runner, args):
    stdin = "".join(json.dumps(m) + "\n" for m in (HANDSHAKE, _credentials_request()))
    result = runner.invoke(nuget, args=args, input=stdin, catch_exceptions=False)

    sent = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 0
    assert sent[0]["Method"] == "Handshake"
    assert _responses(sent)["c"]["Payload"]["Password"] == "k_abc"


def test_cli_trusts_baked_domains(runner):
    stdin = json.dumps(_credentials_request(CUSTOM_FEED)) + "\n"
    result = runner.invoke(
        nuget,
        args=["-k", "k_abc", "--domain", "nuget.acme.com", "--", "-Plugin"],
        input=stdin,
        catch_exceptions=False,
    )

    sent = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 0
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
    return path


@pytest.mark.parametrize(
    "kwargs,baked",
    [
        ({}, ""),
        (
            {
                "org": "acme",
                "domains": ("NuGet.Acme.com", "nuget.acme.com", "feed.acme.dev"),
            },
            "--workspace acme --domain nuget.acme.com --domain feed.acme.dev ",
        ),
    ],
    ids=["plain", "workspace-and-domains"],
)
def test_installer_writes_the_launcher(bin_dir, kwargs, baked):
    actions = NuGetInstaller().install(bin_dir=str(bin_dir), discover=False, **kwargs)

    assert (bin_dir / LAUNCHER).read_text() == (
        f'#!/bin/sh\nexec cloudsmith credential-helper nuget {baked}-- "$@"\n'
    )
    assert not any(a.startswith("WARNING") for a in actions)


def test_installer_uses_a_bat_launcher_on_windows(bin_dir):
    """NuGet only discovers .exe and .bat plugins on Windows, not .cmd."""
    installer = NuGetInstaller()
    with (
        patch(
            "cloudsmith_cli.credential_helpers.launchers._is_windows", return_value=True
        ),
        patch(
            "cloudsmith_cli.credential_helpers.nuget.installer._is_windows",
            return_value=True,
        ),
    ):
        installer.install(bin_dir=str(bin_dir), discover=False)
        assert (bin_dir / f"{LAUNCHER}.bat").exists()
        installer.uninstall(bin_dir=str(bin_dir))
    assert not (bin_dir / f"{LAUNCHER}.bat").exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"org": "acme; rm -rf /"},
        {"org": "-x"},
        {"org": "acme\n"},
        {"domains": ('"%PATH%"',)},
    ],
)
def test_installer_rejects_unsafe_baked_values(bin_dir, kwargs):
    with pytest.raises(NuGetInstallError):
        NuGetInstaller().install(bin_dir=str(bin_dir), discover=False, **kwargs)
    assert not (bin_dir / LAUNCHER).exists()


def test_installer_discovers_custom_domains(bin_dir, credential):
    with patch(INSTALLER_DOMAINS, return_value=["nuget.acme.com"]) as mock_discover:
        actions = NuGetInstaller().install(
            bin_dir=str(bin_dir), org="acme", credential=credential, refresh=True
        )

    assert mock_discover.call_args.args == ("acme", BackendKind.NUGET)
    assert mock_discover.call_args.kwargs["refresh"] is True
    assert mock_discover.call_args.kwargs["strict"] is True
    assert "discovered 1 NuGet custom domain(s): nuget.acme.com" in actions


@pytest.mark.usefixtures("failing_lookup")
def test_installer_survives_discovery_failure(bin_dir, credential):
    actions = NuGetInstaller().install(
        bin_dir=str(bin_dir), org="acme", credential=credential
    )

    assert (bin_dir / LAUNCHER).exists()
    assert any("auto-discovery failed" in a for a in actions)


@pytest.mark.parametrize(
    "kwargs",
    [{"org": None}, {"org": "acme", "dry_run": True}],
    ids=["no-workspace", "dry-run"],
)
def test_installer_skips_discovery(bin_dir, credential, kwargs):
    with patch(INSTALLER_DOMAINS) as mock_discover:
        actions = NuGetInstaller().install(
            bin_dir=str(bin_dir), credential=credential, **kwargs
        )
    mock_discover.assert_not_called()
    if kwargs.get("dry_run"):
        assert not (bin_dir / LAUNCHER).exists()
        assert any("would write launcher" in a for a in actions)


def test_installer_warns_when_the_launcher_is_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    actions = NuGetInstaller().install(bin_dir=str(tmp_path / "bin"), discover=False)
    assert any(a.startswith("WARNING") and "not on PATH" in a for a in actions)


def test_installer_uninstall(bin_dir):
    installer = NuGetInstaller()
    installer.install(bin_dir=str(bin_dir), discover=False)

    assert installer.uninstall(bin_dir=str(bin_dir), dry_run=True)[0].startswith(
        "would remove launcher"
    )
    assert (bin_dir / LAUNCHER).exists()
    assert installer.uninstall(bin_dir=str(bin_dir))[0].startswith("removed launcher")
    assert not (bin_dir / LAUNCHER).exists()
    assert "nothing to remove" in installer.uninstall(bin_dir=str(bin_dir))[0]


def test_installer_status(bin_dir):
    installer = NuGetInstaller()
    cached = [
        CustomDomain("nuget.acme.com", 10, True, True, "acme", DomainType.NATIVE_API),
        CustomDomain("docker.acme.com", 6, True, True, "acme", DomainType.NATIVE_API),
        CustomDomain("off.acme.com", 10, False, True, "acme", DomainType.NATIVE_API),
    ]
    with (
        patch(
            "cloudsmith_cli.credential_helpers.nuget.installer.resolve_bin_dir",
            return_value=bin_dir,
        ),
        patch(
            "cloudsmith_cli.credential_helpers.nuget.installer.read_cache",
            return_value=cached,
        ) as mock_cache,
    ):
        assert installer.status() == {"launcher": None, "hosts": []}

        installer.install(
            bin_dir=str(bin_dir), discover=False, org="acme", domains=("feed.acme.dev",)
        )
        status = installer.status()

    assert status["launcher"] == str(bin_dir / LAUNCHER)
    assert status["hosts"] == ["nuget.cloudsmith.io", "feed.acme.dev", "nuget.acme.com"]
    assert mock_cache.call_args.args[0].name == "acme.json"


def test_install_command_bakes_the_workspace(runner, bin_dir):
    result = runner.invoke(
        install_cmd,
        args=["nuget", "--bin-dir", str(bin_dir), "--no-discover", "-w", "acme"],
        env={"CLOUDSMITH_API_KEY": ""},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "--workspace acme --" in (bin_dir / LAUNCHER).read_text()


def test_install_command_reports_unsafe_values(runner, bin_dir):
    result = runner.invoke(
        install_cmd,
        args=["nuget", "--bin-dir", str(bin_dir), "--no-discover", "--domain", "a b"],
        env={"CLOUDSMITH_API_KEY": ""},
    )
    assert result.exit_code == 1
    assert "Invalid domain" in result.output
