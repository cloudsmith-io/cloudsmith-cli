# Copyright 2026 Cloudsmith Ltd
"""Tests for the `cloudsmith credential-helper cargo` command and installer."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import click.testing
import pytest
import toml

from ...core.credentials.models import CredentialResult
from ...credential_helpers.backends import BackendKind
from ...credential_helpers.cargo.installer import CargoInstaller
from ...credential_helpers.cargo.runtime import (
    _REFUSAL_MESSAGE,
    SUPPORTED_VERSIONS,
    execute,
    get_credentials,
    handle_request,
    hello,
)
from ..commands.credential_helper.cargo import cargo

CLOUDSMITH_INDEX = "sparse+https://cargo.cloudsmith.io/acme/repo/"
CRATES_IO_INDEX = "sparse+https://index.crates.io/"
PROVIDER = CargoInstaller.PROVIDER_VALUE
TOKEN_PROVIDER = CargoInstaller.TOKEN_PROVIDER


@pytest.fixture()
def runner():
    """Return a CliRunner."""
    return click.testing.CliRunner()


@pytest.fixture()
def credential():
    """Return a resolved credential."""
    return CredentialResult(api_key="k_abc", source_name="test")


def _request(**overrides) -> dict:
    """Build a protocol-valid `get`/`read` request, overridden as needed."""
    request = {
        "v": 1,
        "kind": "get",
        "operation": "read",
        "registry": {"index-url": CLOUDSMITH_INDEX, "name": "acme"},
        "args": [],
    }
    request.update(overrides)
    return request


def _session(*requests, credential=None, org=None):
    """Run execute() over *requests* and return (code, stderr, messages)."""
    stdin = io.StringIO("".join(json.dumps(r) + "\n" for r in requests))
    stdout = io.StringIO()
    code, stderr = execute(stdin, stdout, credential=credential, org=org)
    messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
    return code, stderr, messages


# ---------------------------------------------------------------------------
# 1. Handshake
# ---------------------------------------------------------------------------


def test_hello_announces_protocol_version_1():
    """The hello message lists the supported protocol versions as a JSON array."""
    assert hello() == {"v": [1]}
    assert SUPPORTED_VERSIONS == (1,)


def test_hello_is_written_before_any_request_is_read(credential):
    """Cargo blocks on the hello line, so it must be flushed before reading stdin."""

    class AssertHelloFirst(io.StringIO):
        """A stdin that asserts the hello line is already on stdout."""

        def __iter__(self):
            assert stdout.getvalue() == json.dumps(hello()) + "\n"
            return iter([])

    stdout = io.StringIO()
    code, stderr = execute(AssertHelloFirst(""), stdout, credential=credential)

    assert (code, stderr) == (0, None)
    assert stdout.getvalue() == json.dumps(hello()) + "\n"


def test_empty_session_is_not_an_error(credential):
    """Cargo closing stdin without sending a request exits cleanly."""
    code, stderr, messages = _session(credential=credential)

    assert (code, stderr) == (0, None)
    assert messages == [hello()]


# ---------------------------------------------------------------------------
# 2. get — the credential path
# ---------------------------------------------------------------------------


def test_get_returns_token_for_cloudsmith_registry(credential):
    """A Cloudsmith index URL yields an Ok/get response carrying the token."""
    code, stderr, messages = _session(_request(), credential=credential)

    assert (code, stderr) == (0, None)
    assert messages[0] == hello()
    assert messages[1] == {
        "Ok": {
            "kind": "get",
            "token": "k_abc",
            "cache": "session",
            "operation_independent": True,
        }
    }


@pytest.mark.parametrize("operation", ["read", "publish", "yank", "owners"])
def test_get_serves_every_operation(operation, credential):
    """The token is operation-independent, so every `get` operation is served."""
    request = _request(operation=operation, name="sample", vers="0.1.0")
    _, _, messages = _session(request, credential=credential)

    assert messages[1]["Ok"]["token"] == "k_abc"


def test_get_uses_the_cargo_backend_kind_for_custom_domains(credential):
    """Custom-domain matching is scoped to Cargo-backed domains."""
    with patch(
        "cloudsmith_cli.credential_helpers.cargo.runtime.is_cloudsmith_domain",
        return_value=True,
    ) as mock_check:
        _session(
            _request(registry={"index-url": "sparse+https://crates.acme.com/"}),
            credential=credential,
            org="acme",
        )

    assert mock_check.call_args.kwargs["backend_kind"] is BackendKind.CARGO
    assert mock_check.call_args.kwargs["org"] == "acme"


def test_index_url_keeps_its_sparse_prefix_out_of_the_host_match(credential):
    """Cargo's `sparse+` prefix and the repo path don't defeat the host check."""
    assert (
        get_credentials(CLOUDSMITH_INDEX, credential=credential, org="acme") == "k_abc"
    )


# ---------------------------------------------------------------------------
# 3. get — the refusal paths, which Cargo distinguishes
# ---------------------------------------------------------------------------


def test_get_defers_to_the_next_provider_for_a_foreign_registry(credential):
    """crates.io is answered url-not-supported so Cargo falls through, exit 0."""
    code, stderr, messages = _session(
        _request(registry={"index-url": CRATES_IO_INDEX}), credential=credential
    )

    assert messages[1] == {"Err": {"kind": "url-not-supported"}}
    # Not our registry is not an error: installing globally must not break
    # authentication to crates.io.
    assert (code, stderr) == (0, None)


def test_get_reports_not_found_when_no_credential_resolves():
    """A Cloudsmith registry with no token is not-found, exit 1 with a hint."""
    code, stderr, messages = _session(_request(), credential=None)

    assert messages[1] == {"Err": {"kind": "not-found"}}
    assert code == 1
    assert stderr == _REFUSAL_MESSAGE


def test_get_reports_not_found_for_a_credential_without_an_api_key():
    """An empty api_key is treated as no credential at all."""
    empty = CredentialResult(api_key="", source_name="test")
    code, _, messages = _session(_request(), credential=empty)

    assert messages[1] == {"Err": {"kind": "not-found"}}
    assert code == 1


@pytest.mark.parametrize(
    "registry",
    [
        None,
        "cargo.cloudsmith.io",
        {},
        {"name": "acme"},
        {"index-url": ""},
    ],
)
def test_get_without_a_usable_index_url_is_an_other_error(registry, credential):
    """A request we cannot interpret is reported as `other`, with a message."""
    _, _, messages = _session(_request(registry=registry), credential=credential)

    assert messages[1]["Err"]["kind"] == "other"
    assert messages[1]["Err"]["message"]


# ---------------------------------------------------------------------------
# 4. login / logout / unknown kinds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["login", "logout", "frobnicate", None])
def test_unsupported_kinds_are_reported_as_operation_not_supported(kind, credential):
    """Credentials come from the CLI's chain: there is nothing to store or clear."""
    request = _request(kind=kind, token="k_new", **{"login-url": "https://example.com"})
    code, stderr, messages = _session(request, credential=credential)

    assert messages[1] == {"Err": {"kind": "operation-not-supported"}}
    assert (code, stderr) == (0, None)


# ---------------------------------------------------------------------------
# 5. Malformed input and version negotiation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", [None, 0, 2, "1"])
def test_unsupported_protocol_version_is_rejected(version, credential):
    """Only the versions announced in the hello message are answered."""
    _, _, messages = _session(_request(v=version), credential=credential)

    assert messages[1]["Err"]["kind"] == "other"
    assert "Unsupported protocol version" in messages[1]["Err"]["message"]


@pytest.mark.parametrize("line", ["{not json", "[]", '"a string"', "null", "3"])
def test_malformed_request_lines_are_answered_not_crashed(line, credential):
    """A line that isn't a JSON object gets an `other` error, and the loop lives on."""
    stdin = io.StringIO(line + "\n" + json.dumps(_request()) + "\n")
    stdout = io.StringIO()

    code, stderr = execute(stdin, stdout, credential=credential)
    messages = [json.loads(m) for m in stdout.getvalue().splitlines()]

    assert (code, stderr) == (0, None)
    assert messages[1]["Err"]["kind"] == "other"
    # The following well-formed request is still served.
    assert messages[2]["Ok"]["token"] == "k_abc"


def test_blank_lines_are_skipped(credential):
    """Blank lines produce no response message."""
    stdin = io.StringIO("\n\n" + json.dumps(_request()) + "\n\n")
    stdout = io.StringIO()

    execute(stdin, stdout, credential=credential)

    assert len(stdout.getvalue().splitlines()) == 2


def test_multiple_requests_are_answered_in_one_session(credential):
    """One response per request, in order, on a single long-lived session."""
    code, _, messages = _session(
        _request(),
        _request(registry={"index-url": CRATES_IO_INDEX}),
        _request(kind="login"),
        credential=credential,
    )

    assert code == 0
    assert "Ok" in messages[1]
    assert messages[2]["Err"]["kind"] == "url-not-supported"
    assert messages[3]["Err"]["kind"] == "operation-not-supported"


def test_transport_failure_degrades_to_a_clean_exit(credential):
    """A broken pipe on stdout must not surface as a traceback."""

    class BrokenPipe(io.StringIO):
        def write(self, _s):
            raise OSError("broken pipe")

    code, stderr = execute(io.StringIO(""), BrokenPipe(), credential=credential)

    assert code == 1
    assert stderr == _REFUSAL_MESSAGE


def test_domain_lookup_failure_degrades_to_a_clean_exit(credential):
    """A network error during custom-domain discovery must not crash Cargo."""
    with patch(
        "cloudsmith_cli.credential_helpers.cargo.runtime.is_cloudsmith_domain",
        side_effect=RuntimeError("boom"),
    ):
        code, stderr, messages = _session(_request(), credential=credential)

    assert (code, stderr) == (1, _REFUSAL_MESSAGE)
    assert messages == [hello()]


def test_handle_request_never_raises_on_a_non_dict():
    """handle_request is total over decoded JSON values."""
    assert handle_request(["not", "a", "dict"])["Err"]["kind"] == "other"


# ---------------------------------------------------------------------------
# 6. CLI wiring
# ---------------------------------------------------------------------------


def test_cli_speaks_the_protocol_on_stdin_and_stdout(runner):
    """The click shim wires stdin/stdout through to a full protocol exchange."""
    result = runner.invoke(
        cargo,
        args=["-k", "k_abc"],
        input=json.dumps(_request()) + "\n",
        catch_exceptions=False,
    )

    messages = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 0
    assert messages[0] == hello()
    assert messages[1]["Ok"]["token"] == "k_abc"


def test_cli_accepts_the_cargo_plugin_flag_and_extra_provider_args(runner):
    """Cargo passes --cargo-plugin plus any config args; neither may be an error."""
    result = runner.invoke(
        cargo,
        args=["-k", "k_abc", "--cargo-plugin", "--some-config-arg", "value"],
        input=json.dumps(_request()) + "\n",
        catch_exceptions=False,
    )

    messages = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.exit_code == 0
    assert messages[1]["Ok"]["token"] == "k_abc"


def test_cli_exits_non_zero_with_a_hint_when_no_credential_resolves(runner):
    """A refused `get` still answers Cargo in-band, then exits 1 with a hint."""
    with patch(
        "cloudsmith_cli.credential_helpers.cargo.runtime.is_cloudsmith_domain",
        return_value=True,
    ):
        result = runner.invoke(
            cargo,
            args=[],
            input=json.dumps(_request()) + "\n",
            env={"CLOUDSMITH_API_KEY": ""},
            catch_exceptions=False,
        )

    assert result.exit_code == 1
    assert '{"Err": {"kind": "not-found"}}' in result.stdout


# ---------------------------------------------------------------------------
# 7. Installer
# ---------------------------------------------------------------------------


@pytest.fixture()
def cargo_home(tmp_path, monkeypatch):
    """Point CARGO_HOME at a temporary directory and return its config.toml."""
    home = tmp_path / ".cargo"
    monkeypatch.setenv("CARGO_HOME", str(home))
    return home / "config.toml"


@pytest.fixture()
def bin_dir(tmp_path, monkeypatch):
    """Return a launcher directory that is on PATH."""
    path = tmp_path / "bin"
    monkeypatch.setenv("PATH", str(path))
    return path


def test_installer_registers_the_provider_globally(cargo_home, bin_dir):
    """install appends the provider to global-credential-providers, cargo:token kept."""
    installer = CargoInstaller()
    actions = installer.install(bin_dir=str(bin_dir), discover=False)

    config = toml.loads(cargo_home.read_text())
    # Cargo tries providers last-to-first, so ours must come last to be tried first.
    assert config["registry"]["global-credential-providers"] == [
        TOKEN_PROVIDER,
        PROVIDER,
    ]
    assert (bin_dir / "cargo-credential-cloudsmith").exists()
    assert not any(a.startswith("WARNING") for a in actions)


def test_installer_writes_a_launcher_cargo_can_discover(cargo_home, bin_dir):
    """The launcher name carries Cargo's required prefix and execs the CLI."""
    CargoInstaller().install(bin_dir=str(bin_dir), discover=False)

    launcher = bin_dir / "cargo-credential-cloudsmith"
    assert launcher.name.startswith("cargo-credential-")
    assert launcher.read_text() == (
        '#!/bin/sh\nexec cloudsmith credential-helper cargo "$@"\n'
    )


def test_installer_preserves_foreign_config_and_provider_order(cargo_home, bin_dir):
    """Existing config, including other providers, survives the merge."""
    cargo_home.parent.mkdir(parents=True)
    cargo_home.write_text(
        toml.dumps(
            {
                "build": {"jobs": 4},
                "registry": {
                    "global-credential-providers": [
                        TOKEN_PROVIDER,
                        "cargo:macos-keychain",
                    ]
                },
            }
        )
    )

    CargoInstaller().install(bin_dir=str(bin_dir), discover=False)

    config = toml.loads(cargo_home.read_text())
    assert config["build"] == {"jobs": 4}
    assert config["registry"]["global-credential-providers"] == [
        TOKEN_PROVIDER,
        "cargo:macos-keychain",
        PROVIDER,
    ]


def test_installer_adds_the_token_provider_when_the_key_is_absent(cargo_home, bin_dir):
    """Setting the key overrides Cargo's default, so cargo:token is carried over."""
    cargo_home.parent.mkdir(parents=True)
    cargo_home.write_text(toml.dumps({"registry": {"default": "acme"}}))

    CargoInstaller().install(bin_dir=str(bin_dir), discover=False)

    config = toml.loads(cargo_home.read_text())
    assert config["registry"]["default"] == "acme"
    assert TOKEN_PROVIDER in config["registry"]["global-credential-providers"]


def test_installer_is_idempotent(cargo_home, bin_dir):
    """A second install neither duplicates the provider nor rewrites the file."""
    installer = CargoInstaller()
    installer.install(bin_dir=str(bin_dir), discover=False)
    mtime_before = cargo_home.stat().st_mtime

    actions = installer.install(bin_dir=str(bin_dir), discover=False)

    assert cargo_home.stat().st_mtime == mtime_before
    assert toml.loads(cargo_home.read_text())["registry"][
        "global-credential-providers"
    ] == [TOKEN_PROVIDER, PROVIDER]
    assert any("already up to date" in a for a in actions)


def test_installer_pins_the_provider_on_matching_named_registries(cargo_home, bin_dir):
    """A per-registry credential-provider shadows the global list, so pin it too."""
    cargo_home.parent.mkdir(parents=True)
    cargo_home.write_text(
        toml.dumps(
            {
                "registries": {
                    "acme": {"index": CLOUDSMITH_INDEX},
                    "custom": {"index": "sparse+https://crates.acme.com/index/"},
                    "crates-io-mirror": {"index": CRATES_IO_INDEX},
                }
            }
        )
    )

    actions = CargoInstaller().install(
        bin_dir=str(bin_dir),
        domains=("crates.acme.com",),
        discover=False,
    )

    registries = toml.loads(cargo_home.read_text())["registries"]
    assert registries["acme"]["credential-provider"] == PROVIDER
    # Reached via --domain
    assert registries["custom"]["credential-provider"] == PROVIDER
    # A foreign registry is left for its own provider
    assert "credential-provider" not in registries["crates-io-mirror"]
    assert any("registries.acme.credential-provider" in a for a in actions)


def test_installer_dry_run_writes_nothing(cargo_home, bin_dir):
    """--dry-run reports the plan and touches neither the config nor PATH."""
    actions = CargoInstaller().install(bin_dir=str(bin_dir), dry_run=True)

    assert not cargo_home.exists()
    assert not (bin_dir / "cargo-credential-cloudsmith").exists()
    assert any("would write launcher" in a for a in actions)
    assert any("global-credential-providers" in a for a in actions)
    assert any("skipped custom-domain auto-discovery" in a for a in actions)


def test_installer_discovers_custom_domains(cargo_home, bin_dir, credential):
    """Discovered Cargo domains widen which named registries get pinned."""
    cargo_home.parent.mkdir(parents=True)
    cargo_home.write_text(
        toml.dumps(
            {"registries": {"acme": {"index": "sparse+https://crates.acme.com/"}}}
        )
    )

    with patch(
        "cloudsmith_cli.credential_helpers.cargo.installer.get_format_domains",
        return_value=["crates.acme.com"],
    ) as mock_discover:
        CargoInstaller().install(
            bin_dir=str(bin_dir), org="acme", credential=credential
        )

    assert mock_discover.call_args.args[1] is BackendKind.CARGO
    registries = toml.loads(cargo_home.read_text())["registries"]
    assert registries["acme"]["credential-provider"] == PROVIDER


def test_installer_survives_discovery_failure(cargo_home, bin_dir, credential):
    """Discovery is best-effort: the global registration still happens."""
    with patch(
        "cloudsmith_cli.credential_helpers.cargo.installer.get_format_domains",
        side_effect=RuntimeError("boom"),
    ):
        actions = CargoInstaller().install(
            bin_dir=str(bin_dir), org="acme", credential=credential
        )

    config = toml.loads(cargo_home.read_text())
    assert PROVIDER in config["registry"]["global-credential-providers"]
    assert any("auto-discovery failed" in a for a in actions)


def test_installer_warns_when_the_launcher_is_not_on_path(
    cargo_home, tmp_path, monkeypatch
):
    """Cargo resolves a bare provider name through PATH, so warn when it can't."""
    monkeypatch.setenv("PATH", "")

    actions = CargoInstaller().install(bin_dir=str(tmp_path / "bin"), discover=False)

    assert any("is not on PATH" in a for a in actions)


def test_installer_uninstall_restores_the_previous_config(cargo_home, bin_dir):
    """uninstall removes the launcher, the global entry and the pinned entries."""
    cargo_home.parent.mkdir(parents=True)
    cargo_home.write_text(
        toml.dumps(
            {
                "build": {"jobs": 4},
                "registries": {"acme": {"index": CLOUDSMITH_INDEX}},
            }
        )
    )
    installer = CargoInstaller()
    installer.install(bin_dir=str(bin_dir), discover=False)

    actions = installer.uninstall(bin_dir=str(bin_dir))

    config = toml.loads(cargo_home.read_text())
    assert not (bin_dir / "cargo-credential-cloudsmith").exists()
    # Only cargo:token would be left, which is Cargo's default — so the key goes.
    assert "registry" not in config
    assert "credential-provider" not in config["registries"]["acme"]
    assert config["registries"]["acme"]["index"] == CLOUDSMITH_INDEX
    assert config["build"] == {"jobs": 4}
    assert any("removed launcher" in a for a in actions)


def test_installer_uninstall_keeps_other_providers(cargo_home, bin_dir):
    """Only our entry is removed from a list the user has customised."""
    cargo_home.parent.mkdir(parents=True)
    cargo_home.write_text(
        toml.dumps(
            {
                "registry": {
                    "global-credential-providers": [
                        TOKEN_PROVIDER,
                        "cargo:libsecret",
                        PROVIDER,
                    ]
                }
            }
        )
    )

    CargoInstaller().uninstall(bin_dir=str(bin_dir))

    config = toml.loads(cargo_home.read_text())
    assert config["registry"]["global-credential-providers"] == [
        TOKEN_PROVIDER,
        "cargo:libsecret",
    ]


def test_installer_uninstall_is_a_no_op_when_not_installed(cargo_home, bin_dir):
    """Uninstalling a helper that was never installed reports nothing to do."""
    actions = CargoInstaller().uninstall(bin_dir=str(bin_dir))

    # Merging into an absent config would leave an empty config.toml behind.
    assert not cargo_home.exists()
    assert any("nothing to remove" in a for a in actions)
    assert any("entries to remove" in a for a in actions)


def test_installer_uninstall_dry_run_writes_nothing(cargo_home, bin_dir):
    """--dry-run on uninstall leaves the install in place."""
    installer = CargoInstaller()
    installer.install(bin_dir=str(bin_dir), discover=False)

    actions = installer.uninstall(bin_dir=str(bin_dir), dry_run=True)

    config = toml.loads(cargo_home.read_text())
    assert PROVIDER in config["registry"]["global-credential-providers"]
    assert (bin_dir / "cargo-credential-cloudsmith").exists()
    assert any("would remove launcher" in a for a in actions)


def test_installer_status_type_contract(cargo_home, bin_dir):
    """status reports the launcher path and where the provider is registered."""
    installer = CargoInstaller()

    with patch(
        "cloudsmith_cli.credential_helpers.cargo.installer.resolve_bin_dir",
        return_value=bin_dir,
    ):
        assert installer.status() == {"launcher": None, "hosts": []}

        installer.install(bin_dir=str(bin_dir), discover=False)
        status = installer.status()

    assert status["launcher"].endswith("cargo-credential-cloudsmith")
    assert status["hosts"] == ["all registries (global-credential-providers)"]


def test_installer_status_lists_pinned_registry_hosts(cargo_home, bin_dir):
    """A registry pinned to the provider is reported by its index hostname."""
    cargo_home.parent.mkdir(parents=True)
    cargo_home.write_text(
        toml.dumps(
            {
                "registries": {
                    "acme": {
                        "index": CLOUDSMITH_INDEX,
                        "credential-provider": PROVIDER,
                    }
                }
            }
        )
    )

    assert CargoInstaller().status()["hosts"] == ["cargo.cloudsmith.io"]


def test_installer_status_survives_a_malformed_config(cargo_home):
    """A config.toml Cargo itself would reject must not crash `list`."""
    cargo_home.parent.mkdir(parents=True)
    cargo_home.write_text("this is [not valid toml")

    assert CargoInstaller().status()["hosts"] == []
