"""HTTP session creation with retry support."""

import functools
import socket
import ssl
import sys
import time
from types import TracebackType
from typing import Self

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.connectionpool import ConnectionPool
from urllib3.exceptions import MaxRetryError
from urllib3.response import BaseHTTPResponse
from urllib3.util.retry import Retry
from urllib3.util.ssl_ import create_urllib3_context

from .certificate_errors import find_certificate_error

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#: getaddrinfo() error codes for a host name that does not exist. Windows
#: reports WSAHOST_NOT_FOUND (11001).
UNKNOWN_HOST_ERRNOS = frozenset(
    {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME), 11001}
)

_default_proxy = {"url": None}


def set_default_proxy(proxy):
    """Set the proxy for every HTTP client that is not given one."""
    _default_proxy["url"] = proxy


def get_default_proxy():
    """Get the proxy that set_default_proxy() set, or None."""
    return _default_proxy["url"]


_default_tls = {}


def set_default_tls(
    ssl_verify=None, ssl_verify_strict=None, ssl_system_trust_store=None
):
    """Set the TLS settings for every SDK configuration that is not given them."""
    settings = {
        "ssl_verify": ssl_verify,
        "ssl_verify_strict": ssl_verify_strict,
        "ssl_system_trust_store": ssl_system_trust_store,
    }
    _default_tls.clear()
    _default_tls.update(
        {name: value for name, value in settings.items() if value is not None}
    )


def get_default_tls():
    """Get the TLS settings that set_default_tls() set, else the CLI defaults."""
    return {
        "ssl_verify": True,
        "ssl_verify_strict": True,
        "ssl_system_trust_store": False,
        **_default_tls,
    }


class ApiKeySafeSession(requests.Session):
    """A session that drops the API key on a redirect to another host."""

    def rebuild_auth(self, prepared_request, response):
        super().rebuild_auth(prepared_request, response)
        if self.should_strip_auth(response.request.url, prepared_request.url):
            prepared_request.headers.pop("X-Api-Key", None)

    def merge_environment_settings(self, url, proxies, stream, verify, cert):
        # requests lets HTTPS_PROXY and HTTP_PROXY override session.proxies.
        request_proxies = dict(proxies or {})
        settings = super().merge_environment_settings(
            url, proxies, stream, verify, cert
        )
        settings["proxies"].update({**self.proxies, **request_proxies})
        return settings


def _is_unknown_host_error(error: BaseException | None) -> bool:
    """Return True when DNS reports that the host name does not exist."""
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, socket.gaierror):
            return error.errno in UNKNOWN_HOST_ERRNOS
        seen.add(id(error))
        error = error.__cause__
    return False


class RetryWithCallback(Retry):
    """A urllib3 Retry with a callback on retries."""

    def __init__(self, *args, **kwargs):
        self.error_retry_cb = kwargs.pop("error_retry_cb", None)
        super().__init__(*args, **kwargs)

    def new(self, **kw):
        kw["error_retry_cb"] = self.error_retry_cb
        return super().new(**kw)

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: BaseHTTPResponse | None = None,
        error: Exception | None = None,
        _pool: ConnectionPool | None = None,
        _stacktrace: TracebackType | None = None,
    ) -> Self:
        # A failed certificate check or an unknown host fails the same way on
        # every attempt.
        if error is not None and (
            find_certificate_error(error) is not None or _is_unknown_host_error(error)
        ):
            raise MaxRetryError(_pool, url, error) from error
        return super().increment(method, url, response, error, _pool, _stacktrace)

    def sleep_for_retry(self, response=None):
        retry_after = self.get_retry_after(response)
        if retry_after:
            self._sleep_with_callback(retry_after, context="retry-after")
            return True

        return False

    def _sleep_backoff(self):
        backoff = self.get_backoff_time()
        if backoff <= 0:
            return
        self._sleep_with_callback(backoff, context="backoff")

    def _sleep_with_callback(self, seconds, context=None):
        """Sleep, but generate a callback before it."""
        if self.error_retry_cb and callable(self.error_retry_cb):
            self.error_retry_cb(seconds, context=context)
        return time.sleep(seconds)


def disable_x509_strict(context):
    """Clear ``VERIFY_X509_STRICT`` on the SSL context and return it.

    Python 3.13+ (and urllib3 on those versions) enables strict X.509
    verification by default, which rejects certificates that lack extensions
    such as Authority Key Identifier. Such certificates are common when
    corporate proxies intercept TLS traffic, so this allows opting out.
    """
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


class SSLContextAdapter(HTTPAdapter):
    """An HTTPAdapter that verifies certificates using custom SSL contexts."""

    def __init__(self, *args, ssl_context_factory=None, **kwargs):
        self.ssl_context_factory = ssl_context_factory
        self.ssl_contexts = {}
        super().__init__(*args, **kwargs)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(
            request, verify, cert
        )
        # The custom context requires verification, so skip it when disabled
        if self.ssl_context_factory is not None and verify is not False:
            # urllib3 adds each CA bundle to the context it gets, so one shared
            # context would trust every bundle that the session ever used
            key = (verify, cert)
            if key not in self.ssl_contexts:
                self.ssl_contexts[key] = self.ssl_context_factory()
            pool_kwargs["ssl_context"] = self.ssl_contexts[key]
        return host_params, pool_kwargs


def _create_non_strict_ssl_context():
    return disable_x509_strict(create_urllib3_context())


def create_system_trust_store_context(verify_strict=True):
    """Return an SSL context that verifies against the operating system trust store.

    The context also trusts the CA certificates that are loaded into it, for
    example the certifi bundle or REQUESTS_CA_BUNDLE.
    """
    import truststore

    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_flags = create_urllib3_context().verify_flags
    if not verify_strict:
        disable_x509_strict(context)
    return context


def _ssl_context_factory(ssl_verify_strict, ssl_system_trust_store):
    """Return the factory for custom SSL contexts, or None for the default context."""
    if ssl_system_trust_store:
        return functools.partial(
            create_system_trust_store_context, verify_strict=ssl_verify_strict
        )
    if not ssl_verify_strict:
        return _create_non_strict_ssl_context
    return None


def _sdk_configuration():
    """Return the SDK configuration defaults, or None when the SDK is not loaded.

    initialise_api() stores the CLI retry/SSL/proxy settings on
    cloudsmith_api.Configuration via set_default(). When the SDK is not in
    sys.modules, set_default() cannot have run, so the defaults equal the
    fallback values in create_requests_session(). Skipping the import in
    that case keeps the SDK out of commands that never call the API.
    """
    if "cloudsmith_api" not in sys.modules:
        return None
    from cloudsmith_api.configuration import Configuration

    return Configuration()


def create_requests_session(
    retries=None,
    backoff_factor=None,
    status_forcelist=None,
    pools_size=4,
    maxsize=4,
    ssl_verify=None,
    ssl_verify_strict=None,
    ssl_system_trust_store=None,
    ssl_cert=None,
    proxy=None,
    session=None,
    error_retry_cb=None,
    respect_retry_after_header=True,
    user_agent=None,
    headers=None,
):
    """Create a requests session that retries some errors."""
    # pylint: disable=too-many-branches
    config = _sdk_configuration()

    if retries is None:
        retry_max = getattr(config, "error_retry_max", None)
        retries = retry_max if retry_max is not None else 5

    if backoff_factor is None:
        retry_backoff = getattr(config, "error_retry_backoff", None)
        backoff_factor = retry_backoff if retry_backoff is not None else 0.23

    if status_forcelist is None:
        retry_codes = getattr(config, "error_retry_codes", None)
        status_forcelist = (
            retry_codes if retry_codes is not None else [500, 502, 503, 504]
        )

    if ssl_verify is None:
        ssl_verify = config.verify_ssl if config is not None else True

    if ssl_verify_strict is None:
        verify_strict = getattr(config, "ssl_verify_strict", None)
        ssl_verify_strict = verify_strict if verify_strict is not None else True

    if ssl_system_trust_store is None:
        ssl_system_trust_store = bool(getattr(config, "ssl_system_trust_store", False))

    if ssl_cert is None and config is not None:
        if config.cert_file and config.key_file:
            ssl_cert = (config.cert_file, config.key_file)
        elif config.cert_file:
            ssl_cert = config.cert_file

    if proxy is None and config is not None:
        proxy = config.proxy

    if proxy is None:
        proxy = get_default_proxy()

    session = session or ApiKeySafeSession()
    session.verify = ssl_verify
    session.cert = ssl_cert

    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    retry = RetryWithCallback(
        backoff_factor=backoff_factor,
        connect=retries,
        allowed_methods=False,
        read=retries,
        status_forcelist=tuple(status_forcelist),
        status=retries,
        total=retries,
        error_retry_cb=error_retry_cb,
        respect_retry_after_header=respect_retry_after_header,
    )

    adapter = SSLContextAdapter(
        max_retries=retry,
        pool_connections=pools_size,
        pool_maxsize=maxsize,
        pool_block=True,
        ssl_context_factory=_ssl_context_factory(
            ssl_verify_strict, ssl_system_trust_store
        ),
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    if user_agent:
        session.headers["User-Agent"] = user_agent

    if headers:
        session.headers.update(headers)

    return session
