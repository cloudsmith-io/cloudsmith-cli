"""HTTP session creation with retry support."""

import sys
import time

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class RetryWithCallback(Retry):
    """A urllib3 Retry with a callback on retries."""

    def __init__(self, *args, **kwargs):
        self.error_retry_cb = kwargs.pop("error_retry_cb", None)
        super().__init__(*args, **kwargs)

    def new(self, **kw):
        kw["error_retry_cb"] = self.error_retry_cb
        return super().new(**kw)

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

    if ssl_cert is None and config is not None:
        if config.cert_file and config.key_file:
            ssl_cert = (config.cert_file, config.key_file)
        elif config.cert_file:
            ssl_cert = config.cert_file

    if proxy is None and config is not None:
        proxy = config.proxy

    session = session or requests.Session()
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

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=pools_size,
        pool_maxsize=maxsize,
        pool_block=True,
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    if user_agent:
        session.headers["User-Agent"] = user_agent

    if headers:
        session.headers.update(headers)

    return session
