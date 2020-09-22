# -*- coding: utf-8 -*-
"""A RESTful API client with retry builtin."""
from __future__ import absolute_import, print_function, unicode_literals

import io
import json
import logging
import re
import time

import requests
import requests.exceptions
from cloudsmith_api.configuration import Configuration
from cloudsmith_api.rest import ApiException, RESTClientObject
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry  # pylint: disable=import-error
from six.moves.urllib.parse import urlencode

logger = logging.getLogger(__name__)


class RetryWithCallback(Retry):
    """A urllib3 Retry with a callback on retries."""

    def __init__(self, *args, **kwargs):
        self.error_retry_cb = kwargs.pop("error_retry_cb", None)
        super(RetryWithCallback, self).__init__(*args, **kwargs)

    def new(self, **kw):
        kw["error_retry_cb"] = self.error_retry_cb
        return super(RetryWithCallback, self).new(**kw)

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
):
    """Create a requests session that retries some errors."""
    # pylint: disable=too-many-branches
    config = Configuration()

    if retries is None:
        if config.error_retry_max is None:
            retries = 5
        else:
            retries = config.error_retry_max

    if backoff_factor is None:
        if config.error_retry_backoff is None:
            backoff_factor = 0.23
        else:
            backoff_factor = config.error_retry_backoff

    if status_forcelist is None:
        if config.error_retry_codes is None:
            status_forcelist = [500, 502, 503, 504]
        else:
            status_forcelist = config.error_retry_codes

    if ssl_verify is None:
        ssl_verify = config.verify_ssl

    if ssl_cert is None:
        if config.cert_file and config.key_file:
            ssl_cert = (config.cert_file, config.key_file)
        elif config.cert_file:
            ssl_cert = config.cert_file

    if proxy is None:
        proxy = Configuration().proxy

    session = session or requests.Session()
    session.verify = ssl_verify
    session.cert = ssl_cert

    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    retry = RetryWithCallback(
        backoff_factor=backoff_factor,
        connect=retries,
        method_whitelist=False,
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

    return session


class RestResponse(io.IOBase):
    """A urllib3 adapter for a requests response."""

    def __init__(self, response):
        super(RestResponse, self).__init__()
        self.response = response
        self.status = response.status_code
        self.reason = response.reason
        self._data = None

    @property
    def data(self):
        """
        Get the content for the response (lazily decoded).
        """
        if self._data is None:
            self._data = self.response.content.decode("utf-8")
        return self._data

    def getheaders(self):
        """
        Return a dictionary of the response headers.
        """
        return self.response.headers

    def getheader(self, name, default=None):
        """
        Return a given response header.
        """
        return self.response.headers.get(name, default)


class RestClient(RESTClientObject):
    """A rest client interface based on requests, with retry."""

    def __init__(self, *args, **kwargs):
        # pylint: disable=super-init-not-called
        self.session = create_requests_session(*args, **kwargs)

    def request(
        self,
        method,
        url,
        query_params=None,
        headers=None,
        body=None,
        post_params=None,
        _preload_content=True,
        _request_timeout=None,
    ):
        """
        :param method: http request method
        :param url: http request url
        :param query_params: query parameters in the url
        :param headers: http request headers
        :param body: request json body, for `application/json`
        :param post_params: request post parameters,
                            `application/x-www-form-urlencoded`
                            and `multipart/form-data`
        :param _preload_content: if False, the response object will be returned without
                                 reading/decoding response data. Default is True.
        :param _request_timeout: timeout setting for this request. If one number provided, it will be total request
                                 timeout. It can also be a pair (tuple) of (connection, read) timeouts.
        """
        # Based on the RESTClientObject class generated by Swagger
        method = method.upper()
        assert method in ["GET", "HEAD", "DELETE", "POST", "PUT", "PATCH", "OPTIONS"]

        post_params = post_params or {}
        headers = headers or {}

        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        request_kwargs = {}

        if query_params:
            url += "?" + urlencode(query_params)

        if method in ["POST", "PUT", "PATCH", "OPTIONS", "DELETE"]:
            if re.search("json", headers["Content-Type"], re.IGNORECASE):
                request_body = None
                if body:
                    request_body = json.dumps(body)
                request_kwargs["data"] = request_body
            elif headers["Content-Type"] == "application/x-www-form-urlencoded":
                request_kwargs["data"] = post_params
            elif headers["Content-Type"] == "multipart/form-data":
                del headers["Content-Type"]
                request_kwargs["data"] = post_params
            elif isinstance(body, str):
                request_kwargs["data"] = body
            else:
                # Cannot generate the request from given parameters
                msg = """Cannot prepare a request message for provided arguments.
                         Please check that your arguments match declared content type."""
                raise ApiException(status=0, reason=msg)

        try:
            resp = self.session.request(
                method,
                url,
                timeout=_request_timeout,
                stream=not _preload_content,
                headers=headers,
                **request_kwargs
            )
        except requests.exceptions.RequestException as exc:
            msg = "{0}\n{1}".format(type(exc).__name__, str(exc))
            raise ApiException(status=0, reason=msg)

        resp.encoding = resp.apparent_encoding or "utf-8"
        rest_resp = RestResponse(resp)

        if _preload_content:
            logger.debug("response body: %s", rest_resp.data)

        if not 200 <= rest_resp.status <= 299:
            raise ApiException(http_resp=rest_resp)

        return rest_resp
