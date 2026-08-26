"""Tests for CLI error hints."""

import json
from unittest.mock import Mock, patch

from cloudsmith_cli.cli.commands.main import main
from cloudsmith_cli.cli.exceptions import get_401_error_hint, handle_api_exceptions
from cloudsmith_cli.core.api.exceptions import ApiException
from cloudsmith_cli.core.credentials.models import CredentialResult

API_KEY_HINT = (
    "This usually means your API key is invalid, expired, or lacks access to this "
    "resource - check your credentials and try again."
)


def hint_for(credential, info_name="push"):
    """Return the 401 hint for a session holding the given credential.

    opts.api_key is left as an auto-Mock, so a hint that reads it rather than
    the resolved credential fails these tests.
    """
    return get_401_error_hint(
        Mock(info_name=info_name), Mock(credential=credential), Mock()
    )


class TestGet401ErrorHint:
    """The hint has to describe the credential the chain actually resolved.
    Branching on opts.api_key told OIDC sessions -- which never populate it --
    that they had no credentials at all.
    """

    def test_bearer_credential_suggests_reauthenticating(self):
        credential = CredentialResult(
            api_key="sso-token", source_name="keyring", auth_type="bearer"
        )

        assert "cloudsmith auth" in hint_for(credential)

    def test_api_key_credential_does_not_assert_a_permissions_problem(self):
        """A 401 alone cannot establish a specific permissions problem."""
        credential = CredentialResult(api_key="csa_abc123", source_name="oidc")

        assert hint_for(credential) == API_KEY_HINT

    def test_no_credential_suggests_authenticating(self):
        assert "cloudsmith token" in hint_for(None)

    def test_no_credential_on_token_command_reports_a_failed_login(self):
        assert "login failed" in hint_for(None, info_name="token")


def invoke_credentialed_401(runner, config_dir, output_format="pretty"):
    """Raise a translated 401 through the registered command tree.

    The config and credentials paths point at an empty directory so a real
    config.ini or credentials.ini on the machine cannot change the hint.
    """
    args = [
        "whoami",
        "--config-file",
        str(config_dir),
        "--credentials-file",
        str(config_dir),
        "--api-host",
        "https://api.example.invalid",
        "--api-key",
        "fake-api-key",
        "--output-format",
        output_format,
    ]
    with patch(
        "cloudsmith_cli.cli.commands.whoami.get_user_brief",
        side_effect=ApiException(status=401, detail="Invalid API key"),
    ):
        return runner.invoke(main, args)


class TestCredentialed401Rendering:
    """The hint has to survive the renderers, not just the hint function."""

    def test_text_output_renders_the_hint(self, runner, tmp_path):
        result = invoke_credentialed_401(runner, tmp_path)

        assert "status: 401 - Unauthorized" in result.output
        assert f"Hint: {API_KEY_HINT}" in result.output

    def test_json_output_renders_the_hint(self, runner, tmp_path):
        result = invoke_credentialed_401(runner, tmp_path, output_format="json")

        error = json.loads(result.stdout)
        assert error["meta"] == {"code": 401, "description": "Unauthorized"}
        assert error["help"]["hint"] == API_KEY_HINT


class Opts:
    """The handful of attributes the renderer reads off opts."""

    def __init__(self, output="pretty"):
        self.output = output
        self.verbose = False
        self.debug = False
        self.push_metadata_info = None


class TestSummariseError:
    """The opt-in one-sentence rendering, in isolation from its callers."""

    @staticmethod
    def run(summarise, opts, status=422):
        ctx = Mock()
        ctx.exit.side_effect = SystemExit
        exc = ApiException(status=status, detail="Invalid input.")
        exc.fields = {"privileges": "Nope."}

        try:
            with handle_api_exceptions(
                ctx, opts=opts, context_msg="Boom!", summarise_error=summarise
            ):
                raise exc
        except SystemExit:
            pass

    def test_a_summary_replaces_the_context_and_field_block(self, capsys):
        self.run(lambda exc, detail, fields: "Could not do the thing: nope", Opts())

        out = capsys.readouterr().out
        assert "Could not do the thing: nope" in out
        assert "status: 422" not in out
        assert "Privileges Field:" not in out

    def test_declining_keeps_the_default_rendering(self, capsys):
        self.run(lambda exc, detail, fields: None, Opts())

        out = capsys.readouterr().out
        assert "Boom! (status: 422" in out
        assert "Privileges Field: Nope." in out

    def test_the_summary_becomes_the_json_detail(self, capsys):
        self.run(
            lambda exc, detail, fields: "Could not do the thing: nope",
            Opts("json"),
        )

        error = json.loads(capsys.readouterr().out)
        assert error["detail"] == "Could not do the thing: nope"
        assert error["meta"]["code"] == 422

    def test_the_callable_sees_the_exception(self):
        seen = []
        self.run(
            lambda exc, detail, fields: seen.append((exc.status, detail, fields)),
            Opts(),
        )

        assert seen == [(422, "Invalid input.", {"privileges": "Nope."})]
