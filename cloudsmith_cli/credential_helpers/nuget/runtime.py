# Copyright 2026 Cloudsmith Ltd
"""
NuGet credential provider runtime.

Transport-light protocol logic for NuGet credential providers.  This module is
intentionally free of Click/sys imports so it can be unit-tested without
invoking the CLI machinery.

NuGet (``dotnet``, MSBuild and Visual Studio) runs the plugin with
``-Plugin`` and speaks the cross-platform authentication plugin protocol: a
bidirectional conversation of newline-delimited JSON messages on stdin/stdout
that opens with a symmetric handshake, where each side sends a ``Handshake``
request and answers the other's.

See:
    https://learn.microsoft.com/en-us/nuget/reference/extensibility/nuget-cross-platform-plugins
"""

import json
import logging
import uuid

from ..backends import BackendKind
from ..common import extract_hostname, is_cloudsmith_domain

logger = logging.getLogger(__name__)

#: Plugin protocol version spoken; authentication needs at least 2.0.0.
PROTOCOL_VERSION = "2.0.0"
MINIMUM_PROTOCOL_VERSION = "2.0.0"

#: The username sent with the credential; Cloudsmith authenticates the password.
USERNAME = "token"

_REFUSAL_MESSAGE = (
    "Error: Unable to retrieve credentials. "
    "Provide credentials via the CLOUDSMITH_API_KEY environment variable, "
    "credentials.ini, the system keyring, or an OIDC service. "
    "Verify current authentication with `cloudsmith whoami --verbose`."
)

_NOT_APPLICABLE_MESSAGE = "Not a Cloudsmith NuGet feed."

USAGE_MESSAGE = (
    "This is the Cloudsmith NuGet credential provider. NuGet runs it with "
    "-Plugin once it is installed with `cloudsmith credential-helper install nuget`."
)


def is_plugin_mode(args) -> bool:
    """Return True when NuGet asked for the plugin protocol (``-Plugin``)."""
    return any(arg.lstrip("-/").lower() == "plugin" for arg in args)


def is_supported_source(
    uri, credential=None, api_host=None, org=None, extra_domains=()
) -> bool:
    """Return True when *uri* is a Cloudsmith NuGet feed.

    Standard ``*.cloudsmith.io``/``*.cloudsmith.com`` hosts always match.
    Custom domains match when the Workspace has a NuGet custom domain for the
    host (looked up via the Cloudsmith API and cached), or when the host was
    explicitly trusted with ``--domain``.
    """
    hostname = extract_hostname(uri or "")
    if not hostname:
        return False

    if hostname in {extract_hostname(d) for d in extra_domains}:
        return True

    return is_cloudsmith_domain(
        hostname,
        credential=credential,
        api_host=api_host,
        backend_kind=BackendKind.NUGET,
        org=org,
    )


# ---------------------------------------------------------------------------
# Cross-platform plugin protocol
# ---------------------------------------------------------------------------


def _parse_version(value) -> tuple[int, ...] | None:
    """Parse a ``major.minor.patch`` SemVer string, ignoring any suffix."""
    if not isinstance(value, str):
        return None
    core = value.split("-", 1)[0].split("+", 1)[0]
    try:
        return tuple(int(part) for part in core.split("."))
    except ValueError:
        return None


def negotiate_version(payload) -> str | None:
    """Return the negotiated protocol version for a Handshake request, or None."""
    if not isinstance(payload, dict):
        return None
    theirs = _parse_version(payload.get("ProtocolVersion"))
    their_minimum = _parse_version(payload.get("MinimumProtocolVersion"))
    ours = _parse_version(PROTOCOL_VERSION)
    our_minimum = _parse_version(MINIMUM_PROTOCOL_VERSION)
    if theirs is None or their_minimum is None:
        return None
    if their_minimum > theirs or theirs < our_minimum or their_minimum > ours:
        return None
    return PROTOCOL_VERSION if ours <= theirs else payload["ProtocolVersion"]


class PluginSession:
    """One NuGet plugin conversation over newline-delimited JSON streams."""

    def __init__(
        self,
        stdin,
        stdout,
        credential=None,
        api_host=None,
        org=None,
        extra_domains=(),
    ):
        self.stdin = stdin
        self.stdout = stdout
        self.credential = credential
        self.api_host = api_host
        self.org = org
        self.extra_domains = tuple(extra_domains)
        self.refused = False
        self._handshake_id = str(uuid.uuid4())

    def _send(self, request_id, message_type, method, payload=None) -> None:
        """Write one message and flush it; NuGet reads line by line."""
        message = {"RequestId": request_id, "Type": message_type, "Method": method}
        if payload is not None:
            message["Payload"] = payload
        self.stdout.write(json.dumps(message) + "\n")
        self.stdout.flush()

    @staticmethod
    def _handle_handshake(payload) -> dict:
        version = negotiate_version(payload)
        if version is None:
            return {"ResponseCode": "Error"}
        return {"ResponseCode": "Success", "ProtocolVersion": version}

    @staticmethod
    def _handle_operation_claims(payload) -> dict:
        # An authentication plugin is queried with no package source; a query
        # for a specific source asks about package download, which this
        # plugin does not offer.
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("PackageSourceRepository") or payload.get("ServiceIndexJson"):
            return {"Claims": []}
        return {"Claims": ["Authentication"]}

    def _handle_get_credentials(self, payload) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        uri = payload.get("Uri")
        if not is_supported_source(
            uri,
            credential=self.credential,
            api_host=self.api_host,
            org=self.org,
            extra_domains=self.extra_domains,
        ):
            return {"ResponseCode": "NotFound", "Message": _NOT_APPLICABLE_MESSAGE}

        if not self.credential or not self.credential.api_key:
            self.refused = True
            return {"ResponseCode": "Error", "Message": _REFUSAL_MESSAGE}

        return {
            "ResponseCode": "Success",
            "Username": USERNAME,
            "Password": self.credential.api_key,
            "AuthenticationTypes": ["Basic"],
        }

    def handle_request(self, method, payload) -> dict | None:
        """Return the response payload for a request, or None for a fault."""
        if method == "Handshake":
            return self._handle_handshake(payload)
        if method == "GetOperationClaims":
            return self._handle_operation_claims(payload)
        if method == "GetAuthenticationCredentials":
            try:
                return self._handle_get_credentials(payload)
            except Exception as exc:  # pylint: disable=broad-except
                # A failed custom-domain lookup must not break the restore;
                # NotFound lets NuGet try its other credential sources.
                logger.debug("nuget credential lookup failed: %s", exc, exc_info=True)
                return {"ResponseCode": "NotFound", "Message": _NOT_APPLICABLE_MESSAGE}
        if method in (
            "Initialize",
            "SetLogLevel",
            "SetCredentials",
            "MonitorNuGetProcessExit",
        ):
            # Nothing to configure: credentials come from the CLI's own
            # provider chain and every request is answered immediately.
            return {"ResponseCode": "Success"}
        return None

    def _dispatch(self, message) -> bool:
        """Handle one decoded message; return False when the session ends."""
        if not isinstance(message, dict):
            return True

        request_id = message.get("RequestId")
        message_type = message.get("Type")
        method = message.get("Method")

        if message_type == "Response":
            if request_id == self._handshake_id:
                payload = message.get("Payload")
                code = (
                    payload.get("ResponseCode") if isinstance(payload, dict) else None
                )
                if code != "Success":
                    logger.debug("NuGet rejected the plugin handshake: %r", code)
                    return False
            return True

        if message_type != "Request" or not request_id:
            # Progress, Cancel and Fault messages need no answer.
            return True

        if method == "Close":
            return False

        response = self.handle_request(method, message.get("Payload"))
        if response is None:
            self._send(
                request_id,
                "Fault",
                method,
                {"Message": f"Unsupported request method {method!r}"},
            )
        else:
            self._send(request_id, "Response", method, response)
        return True

    def run(self) -> tuple[int, str | None]:
        """
        Run the conversation until NuGet sends Close or closes stdin.

        Returns:
            A (exit_code, stderr_text) tuple.  Outcomes are reported in-band;
            the exit code only flags a session that refused a Cloudsmith feed
            for lack of credentials, or that broke at the transport level.
        """
        try:
            # The handshake is symmetric: NuGet waits for ours as well as for
            # our answer to its own, and gives up after five seconds.
            self._send(
                self._handshake_id,
                "Request",
                "Handshake",
                {
                    "ProtocolVersion": PROTOCOL_VERSION,
                    "MinimumProtocolVersion": MINIMUM_PROTOCOL_VERSION,
                },
            )

            for line in self.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.debug("Ignoring malformed NuGet message: %s", exc)
                    continue
                if not self._dispatch(message):
                    break
        except Exception as exc:  # pylint: disable=broad-except
            # Protocol boundary: broken pipes and serialisation errors must
            # end the session cleanly rather than with a traceback.
            logger.debug("nuget plugin session failed: %s", exc, exc_info=True)
            return (1, _REFUSAL_MESSAGE)

        if self.refused:
            return (1, _REFUSAL_MESSAGE)
        return (0, None)


def execute(
    args,
    stdin,
    stdout,
    credential=None,
    api_host=None,
    org=None,
    extra_domains=(),
) -> tuple[int, str | None]:
    """
    Run the NuGet credential provider for the given NuGet arguments.

    Args:
        args: The arguments NuGet passed (``["-Plugin"]``)
        stdin: A text stream to read plugin messages from
        stdout: A text stream to write plugin messages to
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL
        org: Workspace slug whose custom domains to match against
        extra_domains: Additional hostnames to treat as Cloudsmith feeds

    Returns:
        A (exit_code, stderr_text) tuple.
    """
    if not is_plugin_mode(args):
        return (1, USAGE_MESSAGE)

    return PluginSession(
        stdin,
        stdout,
        credential=credential,
        api_host=api_host,
        org=org,
        extra_domains=extra_domains,
    ).run()
