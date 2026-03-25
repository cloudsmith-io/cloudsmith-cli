"""HTTP session factory with networking configuration and retry support."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

#: Default retry policy: retry on connection errors, 429, and 5xx responses
#: with exponential back-off (1s, 2s, 4s).
DEFAULT_RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"),
    raise_on_status=False,
)


def create_session(
    proxy: str | None = None,
    ssl_verify: bool = True,
    user_agent: str | None = None,
    headers: dict | None = None,
    api_key: str | None = None,
    retry: Retry | None = DEFAULT_RETRY,
) -> requests.Session:
    """Create a requests session with networking, auth, and retry configuration.

    Args:
        proxy: HTTP/HTTPS proxy URL.
        ssl_verify: Whether to verify SSL certificates.
        user_agent: Custom User-Agent header value.
        headers: Additional headers to include in every request.
        api_key: If provided, set as a Bearer token in the Authorization header.
        retry: urllib3 Retry configuration.  Defaults to :data:`DEFAULT_RETRY`.
            Pass ``None`` to disable automatic retries.

    Returns:
        A configured :class:`requests.Session`.
    """
    session = requests.Session()

    if retry is not None:
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    session.verify = ssl_verify

    if user_agent:
        session.headers["User-Agent"] = user_agent

    if headers:
        session.headers.update(headers)

    if api_key:
        session.headers["Authorization"] = f"Bearer {api_key}"

    return session
