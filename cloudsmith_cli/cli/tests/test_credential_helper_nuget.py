# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith credential-helper nuget` command and installer."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import click.testing
import pytest

from ...core.credentials.models import CredentialResult
from ...credential_helpers.backends import BackendKind
from ...credential_helpers.custom_domains import CustomDomain
from ...credential_helpers.default_domains import DomainType
from ...credential_helpers.launchers import _launcher_filename
from ...credential_helpers.nuget.installer import NuGetInstaller, NuGetInstallError
from ...credential_helpers.nuget.runtime import (
    _REFUSAL_MESSAGE,
    EXIT_FAILURE,
    EXIT_NOT_APPLICABLE,
    EXIT_SUCCESS,
    PROTOCOL_VERSION,
    USAGE_MESSAGE,
    PluginSession,
    execute,
    execute_v1,
    get_credentials,
    negotiate_version,
    parse_args,
)
from ..commands.credential_helper.manage import install_cmd
from ..commands.credential_helper.nuget import nuget

CLOUDSMITH_FEED = "https://nuget.cloudsmith.io/acme/repo/v3/index.json"
CUSTOM_FEED = "https://nuget.acme.com/v3/index.json"
NUGET_ORG = "https://api.nuget.org/v3/index.json"
FORMAT_DOMAINS = "cloudsmith_cli.credential_helpers.common.get_format_domains"


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


def _credentials_request(uri=CLOUDSMITH_FEED, request_id="c") -> dict:
    return _message(
        request_id,
        "GetAuthenticationCredentials",
        {
            "Uri": uri,
            "IsRetry": False,
            "IsNonInteractive": True,
            "CanShowDialog": False,
        },
    )


def _session(*messages, credential=None, org=None, extra_domains=()):
    """Run a plugin session over *messages*; return (code, stderr, responses)."""
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    stdout = io.StringIO()
    code, stderr = PluginSession(
        stdin, stdout, credential=credential, org=org, extra_domains=extra_domains
    ).run()
    sent = [json.loads(line) for line in stdout.getvalue().splitlines()]
    return code, stderr, sent


def _responses(sent) -> dict:
    """Map RequestId -> message for everything the plugin answered."""
    return {m["RequestId"]: m for m in sent if m["Type"] != "Request"}


# ---------------------------------------------------------------------------
# 1. Argument parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args,expected",
    [
        (["-Plugin"], {"plugin": True}),
        (["--plugin"], {"plugin": True}),
        (
            ["-Uri", CLOUDSMITH_FEED, "-NonInteractive", "-IsRetry"],
            {"uri": CLOUDSMITH_FEED, "noninteractive": True, "isretry": True},
        ),
        (
            ["/uri", CLOUDSMITH_FEED, "-verbosity", "detailed"],
            {"uri": CLOUDSMITH_FEED, "verbosity": "detailed"},
        ),
        ([f"-Uri={CLOUDSMITH_FEED}"], {"uri": CLOUDSMITH_FEED}),
        ([f"-Uri:{CLOUDSMITH_FEED}"], {"uri": CLOUDSMITH_FEED}),
        (["stray", "-", "-FutureSwitch"], {"futureswitch": True}),
        (["-Uri"], {}),
    ],
)
def test_parse_args(args, expected):
    """NuGet's switches parse case-insensitively; unknown ones are kept, not fatal."""
    assert parse_args(args) == expected


# ---------------------------------------------------------------------------
# 2. Domain matching
# ---------------------------------------------------------------------------


def test_get_credentials_for_a_cloudsmith_feed(credential):
    assert get_credentials(CLOUDSMITH_FEED, credential=credential) == {
        "Username": "token",
        "Password": "k_abc",
    }


def test_get_credentials_declines_a_foreign_feed(credential):
    assert get_credentials(NUGET_ORG, credential=credential) is None


def test_get_credentials_needs_a_credential():
    assert get_credentials(CLOUDSMITH_FEED, credential=None) is None


def test_custom_domains_are_matched_with_the_nuget_backend_kind(credential):
    with patch(FORMAT_DOMAINS, return_value=["nuget.acme.com"]) as mock_domains:
        creds = get_credentials(CUSTOM_FEED, credential=credential, org="acme")

    assert creds["Password"] == "k_abc"
    assert mock_domains.call_args.args == ("acme", BackendKind.NUGET)


def test_custom_domains_need_a_workspace(credential):
    with patch(FORMAT_DOMAINS, return_value=["nuget.acme.com"]) as mock_domains:
        assert get_credentials(CUSTOM_FEED, credential=credential) is None
    mock_domains.assert_not_called()


def test_extra_domains_are_trusted_without_a_lookup(credential):
    with patch(FORMAT_DOMAINS) as mock_domains:
        creds = get_credentials(
            CUSTOM_FEED, credential=credential, extra_domains=("NuGet.Acme.com",)
        )
    assert creds["Password"] == "k_abc"
    mock_domains.assert_not_called()


# ---------------------------------------------------------------------------
# 3. nuget.exe (v1) protocol
# ---------------------------------------------------------------------------


def test_v1_success(credential):
    code, stdout, stderr = execute_v1(CLOUDSMITH_FEED, credential=credential)

    assert code == EXIT_SUCCESS
    assert json.loads(stdout) == {
        "Username": "token",
        "Password": "k_abc",
        "Message": "",
    }
    assert stderr is None


def test_v1_foreign_feed_is_not_applicable(credential):
    assert execute_v1(NUGET_ORG, credential=credential) == (
        EXIT_NOT_APPLICABLE,
        None,
        None,
    )


def test_v1_cloudsmith_feed_without_credentials_fails():
    code, stdout, stderr = execute_v1(CLOUDSMITH_FEED, credential=None)

    assert code == EXIT_FAILURE
    assert json.loads(stdout) == {"Message": _REFUSAL_MESSAGE}
    assert stderr == _REFUSAL_MESSAGE


def test_v1_lookup_failure_is_not_applicable(credential):
    with patch(FORMAT_DOMAINS, side_effect=RuntimeError("boom")):
        code, stdout, _ = execute_v1(CUSTOM_FEED, credential=credential, org="acme")
    assert (code, stdout) == (EXIT_NOT_APPLICABLE, None)


def test_execute_dispatches_uri_to_v1(credential):
    stdout = io.StringIO()
    code, stderr = execute(
        ["-Uri", CLOUDSMITH_FEED, "-NonInteractive"],
        io.StringIO(),
        stdout,
        credential=credential,
    )
    assert code == EXIT_SUCCESS
    assert stderr is None
    assert json.loads(stdout.getvalue())["Password"] == "k_abc"


def test_execute_without_a_mode_prints_usage(credential):
    stdout = io.StringIO()
    assert execute([], io.StringIO(), stdout, credential=credential) == (
        EXIT_NOT_APPLICABLE,
        USAGE_MESSAGE,
    )
    assert stdout.getvalue() == ""


# ---------------------------------------------------------------------------
# 4. Cross-platform plugin (v2) protocol
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"ProtocolVersion": "2.0.0", "MinimumProtocolVersion": "1.0.0"}, "2.0.0"),
        ({"ProtocolVersion": "3.0.0", "MinimumProtocolVersion": "1.0.0"}, "2.0.0"),
        ({"ProtocolVersion": "1.0.0", "MinimumProtocolVersion": "1.0.0"}, None),
        ({"ProtocolVersion": "4.0.0", "MinimumProtocolVersion": "3.0.0"}, None),
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
            assert sent["Type"] == "Request"
            assert sent["Method"] == "Handshake"
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
        _message(
            "i",
            "Initialize",
            {
                "ClientVersion": "7.0.0",
                "Culture": "en-US",
                "RequestTimeout": "00:00:05",
            },
        ),
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
    assert responses["c"] == {
        "RequestId": "c",
        "Type": "Response",
        "Method": "GetAuthenticationCredentials",
        "Payload": {
            "ResponseCode": "Success",
            "Username": "token",
            "Password": "k_abc",
            "AuthenticationTypes": ["Basic"],
        },
    }
    assert "x" not in responses


def test_plugin_claims_nothing_for_a_download_source(credential):
    _, _, sent = _session(
        _message(
            "o",
            "GetOperationClaims",
            {"PackageSourceRepository": CLOUDSMITH_FEED, "ServiceIndexJson": "{}"},
        ),
        credential=credential,
    )
    assert _responses(sent)["o"]["Payload"] == {"Claims": []}


def test_plugin_rejects_an_incompatible_handshake(credential):
    _, _, sent = _session(
        _message(
            "h",
            "Handshake",
            {"ProtocolVersion": "1.0.0", "MinimumProtocolVersion": "1.0.0"},
        ),
        credential=credential,
    )
    assert _responses(sent)["h"]["Payload"] == {"ResponseCode": "Error"}


def test_plugin_declines_a_foreign_feed(credential):
    code, _, sent = _session(_credentials_request(NUGET_ORG), credential=credential)

    assert code == 0
    assert _responses(sent)["c"]["Payload"]["ResponseCode"] == "NotFound"


def test_plugin_reports_missing_credentials_for_a_cloudsmith_feed():
    code, stderr, sent = _session(_credentials_request())

    payload = _responses(sent)["c"]["Payload"]
    assert payload == {"ResponseCode": "Error", "Message": _REFUSAL_MESSAGE}
    assert (code, stderr) == (1, _REFUSAL_MESSAGE)


def test_plugin_matches_custom_domains_for_the_workspace(credential):
    with patch(FORMAT_DOMAINS, return_value=["nuget.acme.com"]):
        _, _, sent = _session(
            _credentials_request(CUSTOM_FEED), credential=credential, org="acme"
        )
    assert _responses(sent)["c"]["Payload"]["Password"] == "k_abc"


def test_plugin_lookup_failure_is_not_found(credential):
    with patch(FORMAT_DOMAINS, side_effect=RuntimeError("boom")):
        code, _, sent = _session(
            _credentials_request(CUSTOM_FEED), credential=credential, org="acme"
        )
    assert code == 0
    assert _responses(sent)["c"]["Payload"]["ResponseCode"] == "NotFound"


def test_plugin_faults_unknown_requests(credential):
    _, _, sent = _session(_message("u", "CopyNupkgFile", {}), credential=credential)

    fault = _responses(sent)["u"]
    assert fault["Type"] == "Fault"
    assert "CopyNupkgFile" in fault["Payload"]["Message"]


def test_plugin_ignores_noise(credential):
    """Blank and malformed lines, progress and cancel messages need no answer."""
    stdin = io.StringIO(
        "\n"
        "not json\n"
        "[1, 2]\n"
        + json.dumps(
            _message("p", "GetAuthenticationCredentials", {}, message_type="Progress")
        )
        + "\n"
        + json.dumps(_message("q", "Handshake", message_type="Cancel"))
        + "\n"
        + json.dumps(_credentials_request())
        + "\n"
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


def test_plugin_transport_failure_degrades_to_a_clean_exit(credential):
    class BrokenPipe(io.StringIO):
        def write(self, _):
            raise BrokenPipeError("gone")

    code, stderr = PluginSession(
        io.StringIO(), BrokenPipe(), credential=credential
    ).run()
    assert (code, stderr) == (1, _REFUSAL_MESSAGE)


# ---------------------------------------------------------------------------
# 5. CLI wiring
# ---------------------------------------------------------------------------


def test_cli_speaks_the_plugin_protocol(runner):
    stdin = "".join(json.dumps(m) + "\n" for m in (HANDSHAKE, _credentials_request()))
    result = runner.invoke(
        nuget,
        args=["-k", "k_abc", "--", "-Plugin"],
        input=stdin,
        catch_exceptions=False,
    )

    sent = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 0
    assert sent[0]["Method"] == "Handshake"
    assert _responses(sent)["c"]["Payload"]["Password"] == "k_abc"


def test_cli_accepts_plugin_switch_without_separator(runner):
    result = runner.invoke(
        nuget, args=["-k", "k_abc", "-Plugin"], input="", catch_exceptions=False
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout.splitlines()[0])["Method"] == "Handshake"


def test_cli_speaks_the_v1_protocol_with_baked_args(runner):
    result = runner.invoke(
        nuget,
        args=[
            "-k",
            "k_abc",
            "--workspace",
            "acme",
            "--domain",
            "nuget.acme.com",
            "--",
            "-Uri",
            CUSTOM_FEED,
            "-NonInteractive",
            "-Verbosity",
            "detailed",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["Password"] == "k_abc"


def test_cli_v1_declines_a_foreign_feed(runner):
    result = runner.invoke(
        nuget, args=["-k", "k_abc", "--", "-Uri", NUGET_ORG], catch_exceptions=False
    )
    assert result.exit_code == 1
    assert result.stdout == ""


def test_cli_without_nuget_args_prints_usage(runner):
    result = runner.invoke(nuget, args=["-k", "k_abc"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "nuget-plugin" not in result.stdout
    assert "credential-helper install nuget" in result.stderr


# ---------------------------------------------------------------------------
# 6. Installer
# ---------------------------------------------------------------------------


@pytest.fixture()
def bin_dir(tmp_path, monkeypatch):
    """Return a launcher directory that is on PATH."""
    path = tmp_path / "bin"
    monkeypatch.setenv("PATH", str(path))
    return path


LAUNCHER = "nuget-plugin-cloudsmith"


def test_launcher_uses_a_bat_suffix_on_windows():
    """NuGet only discovers .exe and .bat plugins on Windows, not .cmd."""
    assert (
        _launcher_filename(
            LAUNCHER, windows=True, windows_suffix=NuGetInstaller.WINDOWS_SUFFIX
        )
        == "nuget-plugin-cloudsmith.bat"
    )
    assert (
        _launcher_filename(LAUNCHER, windows=False, windows_suffix=".bat") == LAUNCHER
    )


def test_installer_writes_a_launcher_nuget_can_discover(bin_dir):
    actions = NuGetInstaller().install(bin_dir=str(bin_dir), discover=False)

    launcher = bin_dir / LAUNCHER
    assert launcher.name.startswith("nuget-plugin-")
    assert launcher.read_text() == (
        '#!/bin/sh\nexec cloudsmith credential-helper nuget -- "$@"\n'
    )
    assert not any(a.startswith("WARNING") for a in actions)


def test_installer_bakes_the_workspace_and_domains(bin_dir):
    NuGetInstaller().install(
        bin_dir=str(bin_dir),
        discover=False,
        org="acme",
        domains=("NuGet.Acme.com", "nuget.acme.com", "feed.acme.dev"),
    )

    assert (bin_dir / LAUNCHER).read_text() == (
        "#!/bin/sh\nexec cloudsmith credential-helper nuget --workspace acme "
        '--domain nuget.acme.com --domain feed.acme.dev -- "$@"\n'
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"org": "acme; rm -rf /"},
        {"org": "-x"},
        {"domains": ("nuget.acme.com && evil",)},
        {"domains": ('"%PATH%"',)},
    ],
)
def test_installer_rejects_unsafe_baked_values(bin_dir, kwargs):
    with pytest.raises(NuGetInstallError):
        NuGetInstaller().install(bin_dir=str(bin_dir), discover=False, **kwargs)
    assert not (bin_dir / LAUNCHER).exists()


def test_installer_discovers_custom_domains(bin_dir, credential):
    with patch(
        "cloudsmith_cli.credential_helpers.nuget.installer.get_format_domains",
        return_value=["nuget.acme.com"],
    ) as mock_discover:
        actions = NuGetInstaller().install(
            bin_dir=str(bin_dir), org="acme", credential=credential, refresh=True
        )

    assert mock_discover.call_args.args == ("acme", BackendKind.NUGET)
    assert mock_discover.call_args.kwargs["refresh"] is True
    assert "discovered 1 NuGet custom domain(s): nuget.acme.com" in actions


def test_installer_skips_discovery_without_a_workspace(bin_dir, credential):
    with patch(
        "cloudsmith_cli.credential_helpers.nuget.installer.get_format_domains"
    ) as mock_discover:
        NuGetInstaller().install(bin_dir=str(bin_dir), credential=credential)
    mock_discover.assert_not_called()


def test_installer_survives_discovery_failure(bin_dir, credential):
    with patch(
        "cloudsmith_cli.credential_helpers.nuget.installer.get_format_domains",
        side_effect=RuntimeError("boom"),
    ):
        actions = NuGetInstaller().install(
            bin_dir=str(bin_dir), org="acme", credential=credential
        )

    assert (bin_dir / LAUNCHER).exists()
    assert any("auto-discovery failed" in a for a in actions)


def test_installer_dry_run_writes_nothing(bin_dir, credential):
    with patch(
        "cloudsmith_cli.credential_helpers.nuget.installer.get_format_domains"
    ) as mock_discover:
        actions = NuGetInstaller().install(
            bin_dir=str(bin_dir), org="acme", credential=credential, dry_run=True
        )

    mock_discover.assert_not_called()
    assert not (bin_dir / LAUNCHER).exists()
    assert any("would write launcher" in a for a in actions)
    assert any("skipped custom-domain auto-discovery" in a for a in actions)


def test_installer_warns_when_the_launcher_is_not_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    actions = NuGetInstaller().install(bin_dir=str(tmp_path / "bin"), discover=False)
    assert any(a.startswith("WARNING") and "not on PATH" in a for a in actions)


def test_installer_uninstall(bin_dir):
    installer = NuGetInstaller()
    installer.install(bin_dir=str(bin_dir), discover=False)

    dry = installer.uninstall(bin_dir=str(bin_dir), dry_run=True)
    assert (bin_dir / LAUNCHER).exists()
    assert dry[0].startswith("would remove launcher")

    actions = installer.uninstall(bin_dir=str(bin_dir))
    assert not (bin_dir / LAUNCHER).exists()
    assert actions[0].startswith("removed launcher")

    again = installer.uninstall(bin_dir=str(bin_dir))
    assert "nothing to remove" in again[0]


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


def test_install_command_reports_unsafe_values(runner, bin_dir):
    result = runner.invoke(
        install_cmd,
        args=["nuget", "--bin-dir", str(bin_dir), "--no-discover", "--domain", "a b"],
        env={"CLOUDSMITH_API_KEY": ""},
    )
    assert result.exit_code == 1
    assert "Invalid domain" in result.output


def test_install_command_installs_nuget(runner, bin_dir):
    result = runner.invoke(
        install_cmd,
        args=[
            "nuget",
            "--bin-dir",
            str(bin_dir),
            "--no-discover",
            "--workspace",
            "acme",
        ],
        env={"CLOUDSMITH_API_KEY": ""},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "--workspace acme --" in (bin_dir / LAUNCHER).read_text()
