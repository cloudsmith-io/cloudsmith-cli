# -*- coding: utf-8 -*-
"""API - Files endpoints."""
from __future__ import absolute_import, print_function, unicode_literals

import os

import click
import cloudsmith_api
import requests
import six
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

from .. import ratelimits
from ..rest import create_requests_session
from ..utils import calculate_file_md5
from .exceptions import ApiException, catch_raise_api_exception
from .init import get_api_client


def get_files_api():
    """Get the files API client."""
    return get_api_client(cloudsmith_api.FilesApi)


def validate_request_file_upload(owner, repo, filepath, md5_checksum=None):
    """Validate parameters for requesting a file upload."""
    client = get_files_api()
    md5_checksum = md5_checksum or calculate_file_md5(filepath)

    with catch_raise_api_exception():
        _, _, headers = client.files_validate_with_http_info(
            owner=owner,
            repo=repo,
            data={"filename": os.path.basename(filepath), "md5_checksum": md5_checksum},
        )

    ratelimits.maybe_rate_limit(client, headers)
    return md5_checksum


def request_file_upload(owner, repo, filepath, md5_checksum=None):
    """Request a new package file upload (for creating packages)."""
    client = get_files_api()
    md5_checksum = md5_checksum or calculate_file_md5(filepath)

    with catch_raise_api_exception():
        data, _, headers = client.files_create_with_http_info(
            owner=owner,
            repo=repo,
            data={"filename": os.path.basename(filepath), "md5_checksum": md5_checksum},
        )

    # pylint: disable=no-member
    # Pylint detects the returned value as a tuple
    ratelimits.maybe_rate_limit(client, headers)
    return data.identifier, data.upload_url, data.upload_fields


def upload_file(upload_url, upload_fields, filepath, callback=None):
    """Upload a pre-signed file to Cloudsmith."""
    upload_fields = list(six.iteritems(upload_fields))
    upload_fields.append(
        ("file", (os.path.basename(filepath), click.open_file(filepath, "rb")))
    )
    encoder = MultipartEncoder(upload_fields)
    monitor = MultipartEncoderMonitor(encoder, callback=callback)

    config = cloudsmith_api.Configuration()
    if config.proxy:
        proxies = {"http": config.proxy, "https": config.proxy}
    else:
        proxies = None

    headers = {"content-type": monitor.content_type}

    client = get_files_api()
    headers["user-agent"] = client.api_client.user_agent

    session = create_requests_session()
    resp = session.post(upload_url, data=monitor, headers=headers, proxies=proxies)

    try:
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ApiException(
            resp.status_code, headers=exc.response.headers, body=exc.response.content
        )
