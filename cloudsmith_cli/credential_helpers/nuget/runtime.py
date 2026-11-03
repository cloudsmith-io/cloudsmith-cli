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

import collections
import json
import logging
import queue
import re
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from urllib.parse import urlsplit

from ..backends import BackendKind
from ..common import (
    REFUSAL_MESSAGE,
    extract_hostname,
    is_cloudsmith_domain,
    is_standard_cloudsmith_domain,
)

logger = logging.getLogger(__name__)

#: Plugin protocol version spoken; authentication needs at least 2.0.0.
PROTOCOL_VERSION = "2.0.0"
MINIMUM_PROTOCOL_VERSION = "2.0.0"

#: The request timeout in seconds until NuGet sends ``Initialize``.
DEFAULT_REQUEST_TIMEOUT = 5.0

#: A .NET TimeSpan in the constant format, ``[d.]hh:mm:ss[.fffffff]``.
_TIMESPAN = re.compile(r"(?:(\d+)\.)?(\d+):(\d+):(\d+(?:\.\d+)?)")

_END_OF_INPUT = object()

_NOT_APPLICABLE_MESSAGE = "Not a Cloudsmith NuGet feed."

USAGE_MESSAGE = (
    "This is the Cloudsmith NuGet credential provider. NuGet runs it with "
    "-Plugin once it is installed with `cloudsmith credential-helper install nuget`."
)


def is_plugin_mode(args) -> bool:
    """Return True when NuGet asked for the plugin protocol (``-Plugin``)."""
    return any(arg.lstrip("-/").lower() == "plugin" for arg in args)


def is_supported_source(
    uri,
    credential=None,
    api_host=None,
    workspace=None,
    domains=frozenset(),
    discover=True,
) -> bool:
    """Return True when *uri* is a Cloudsmith NuGet feed.

    Standard ``*.cloudsmith.io``/``*.cloudsmith.com`` hosts always match.
    Other hosts match when the Workspace lists them as NuGet domains (looked
    up via the Cloudsmith API and cached, with the SDK as the caller configured
    it).  Only ``https`` feeds match, so the API key is never sent in clear
    text.  The host comes from the URI's authority, so a query or fragment
    cannot name a Cloudsmith host.  A backslash is refused because .NET reads
    it as a path separator.  The hosts in *domains* always match.  When
    *discover* is False, no other custom domain matches and the API is not
    called.
    """
    if not isinstance(uri, str) or "\\" in uri:
        return False
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if parts.scheme.lower() != "https" or not parts.hostname:
        return False
    if parts.hostname in domains:
        return True
    if not discover:
        return is_standard_cloudsmith_domain(parts.hostname)

    return is_cloudsmith_domain(
        parts.hostname,
        credential=credential,
        api_host=api_host,
        backend_kind=BackendKind.NUGET,
        org=workspace,
        configure_api=False,
    )


def _parse_version(value) -> tuple[int, ...] | None:
    """Parse a ``major.minor.patch`` SemVer string, ignoring any suffix."""
    if not isinstance(value, str):
        return None
    core = value.split("-", 1)[0].split("+", 1)[0]
    try:
        return tuple(int(part) for part in core.split("."))
    except ValueError:
        return None


def parse_timespan(value) -> float | None:
    """Return the seconds in a .NET TimeSpan string such as ``00:00:05``, or None."""
    match = _TIMESPAN.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    days, hours, minutes, seconds = match.groups()
    return ((int(days or 0) * 24 + int(hours)) * 60 + int(minutes)) * 60 + float(
        seconds
    )


def negotiate_version(payload) -> str | None:
    """Return the protocol version for a Handshake request, or None if incompatible."""
    if not isinstance(payload, dict):
        return None
    theirs = _parse_version(payload.get("ProtocolVersion"))
    their_minimum = _parse_version(payload.get("MinimumProtocolVersion"))
    if theirs is None or their_minimum is None:
        return None
    ours = tuple(int(part) for part in PROTOCOL_VERSION.split("."))
    if not their_minimum <= ours <= theirs:
        return None
    return PROTOCOL_VERSION


def _is_cancel(message, request_id) -> bool:
    """Return True when *message* cancels the request *request_id*."""
    return (
        isinstance(message, dict)
        and message.get("Type") == "Cancel"
        and message.get("RequestId") == request_id
    )


class PluginSession:
    """One NuGet plugin conversation over newline-delimited JSON streams."""

    def __init__(
        self,
        stdin,
        stdout,
        credential=None,
        api_host=None,
        workspace=None,
        refresh_credential=None,
        domains=(),
        discover=True,
    ):
        self.stdin = stdin
        self.stdout = stdout
        self.credential = credential
        self.api_host = api_host
        self.workspace = workspace
        self.refresh_credential = refresh_credential
        self.domains = frozenset(extract_hostname(domain) for domain in domains)
        self.discover = discover
        self.refused = False
        self.request_timeout = DEFAULT_REQUEST_TIMEOUT
        self._handshake_id = str(uuid.uuid4())
        self._inbox = queue.Queue()
        self._backlog = collections.deque()
        # One worker thread runs one request at a time, also after a Cancel.
        self._worker = ThreadPoolExecutor(max_workers=1)

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
        if payload.get("PackageSourceRepository") or payload.get("ServiceIndex"):
            return {"Claims": []}
        return {"Claims": ["Authentication"]}

    def _handle_initialize(self, payload) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        request_timeout = parse_timespan(payload.get("RequestTimeout"))
        if request_timeout:
            self.request_timeout = request_timeout
        return {"ResponseCode": "Success"}

    def _handle_get_credentials(self, payload) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("IsRetry") and self.refresh_credential:
            # NuGet retries after the feed rejected the last credential, which
            # can have expired since the plugin started.
            self.credential = self.refresh_credential()
        uri = payload.get("Uri")
        # A failed custom-domain lookup matches no host, so NuGet gets
        # NotFound and tries its other credential sources.
        if not is_supported_source(
            uri,
            credential=self.credential,
            api_host=self.api_host,
            workspace=self.workspace,
            domains=self.domains,
            discover=self.discover,
        ):
            return {"ResponseCode": "NotFound", "Message": _NOT_APPLICABLE_MESSAGE}

        if not self.credential or not self.credential.api_key:
            self.refused = True
            return {"ResponseCode": "Error", "Message": REFUSAL_MESSAGE}

        return {
            "ResponseCode": "Success",
            "Username": "token",
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
            return self._handle_get_credentials(payload)
        if method == "Initialize":
            return self._handle_initialize(payload)
        if method in (
            "SetLogLevel",
            "SetCredentials",
            "MonitorNuGetProcessExit",
        ):
            # Nothing to configure: credentials come from the CLI's own
            # provider chain.
            return {"ResponseCode": "Success"}
        return None

    def _answer_with_progress(self, request_id, method, payload) -> None:
        """Answer a request from the worker, with Progress before each deadline.

        A Cancel for the request ends the wait. Other messages wait in the backlog.
        """
        future = self._worker.submit(self.handle_request, method, payload)
        future.add_done_callback(self._inbox.put)
        interval = self.request_timeout / 2
        progress_due = time.monotonic() + interval
        while True:
            try:
                item = self._inbox.get(
                    timeout=max(0.0, progress_due - time.monotonic())
                )
            except queue.Empty:
                self._send(request_id, "Progress", method, {})
                progress_due = time.monotonic() + interval
                continue
            if item is future:
                self._send(request_id, "Response", method, future.result())
                return
            if _is_cancel(item, request_id):
                self._send(request_id, "Cancel", method)
                return
            if not isinstance(item, Future):
                self._backlog.append(item)

    def _read_messages(self) -> None:
        """Queue each stdin message, then the end of input, for the main thread."""
        try:
            for line in self.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._inbox.put(json.loads(line))
                except ValueError as exc:
                    logger.debug("Ignoring malformed NuGet message: %s", exc)
        except (OSError, ValueError) as exc:
            self._inbox.put(exc)
        self._inbox.put(_END_OF_INPUT)

    def _next_message(self):
        """Return the next message, or raise the error that ended stdin."""
        message = self._backlog.popleft() if self._backlog else self._inbox.get()
        if isinstance(message, Exception):
            raise message
        return message

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

        if method == "GetAuthenticationCredentials":
            # A domain lookup or a credential renewal can take longer than
            # NuGet's request timeout.
            self._answer_with_progress(request_id, method, message.get("Payload"))
        elif (response := self.handle_request(method, message.get("Payload"))) is None:
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
            # our answer to its own.
            self._send(
                self._handshake_id,
                "Request",
                "Handshake",
                {
                    "ProtocolVersion": PROTOCOL_VERSION,
                    "MinimumProtocolVersion": MINIMUM_PROTOCOL_VERSION,
                },
            )

            threading.Thread(target=self._read_messages, daemon=True).start()
            while (message := self._next_message()) is not _END_OF_INPUT:
                if not self._dispatch(message):
                    break
        except (OSError, ValueError) as exc:
            # Protocol boundary: a broken pipe, a closed stream or undecodable
            # input ends the session cleanly rather than with a traceback.
            # NuGet has gone away, so a credential message would mislead.
            logger.debug("nuget plugin session failed: %s", exc, exc_info=True)
            return (1, None)

        if self.refused:
            return (1, REFUSAL_MESSAGE)
        return (0, None)


def execute(
    args,
    stdin,
    stdout,
    credential=None,
    api_host=None,
    workspace=None,
    refresh_credential=None,
    domains=(),
    discover=True,
) -> tuple[int, str | None]:
    """
    Run the NuGet credential provider for the given NuGet arguments.

    Args:
        args: The arguments NuGet passed (``["-Plugin"]``)
        stdin: A text stream to read plugin messages from
        stdout: A text stream to write plugin messages to
        credential: Pre-resolved CredentialResult from the provider chain
        api_host: Cloudsmith API host URL
        workspace: Workspace slug whose custom domains to match against
        refresh_credential: Callable that resolves the credential again when
            NuGet retries a request
        domains: Feed hosts that always match
        discover: When False, do not look up the Workspace's NuGet domains

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
        workspace=workspace,
        refresh_credential=refresh_credential,
        domains=domains,
        discover=discover,
    ).run()
