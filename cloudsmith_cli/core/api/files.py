"""API - Files endpoints."""
from __future__ import absolute_import, print_function, unicode_literals
import os

import click
import cloudsmith_api
import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
from ..utils import calculate_file_md5
from .exceptions import catch_raise_api_exception, ApiException


def get_files_api():
    """Get the files API client."""
    config = cloudsmith_api.Configuration()
    client = cloudsmith_api.FilesApi()
    if config.user_agent:
        client.api_client.user_agent = config.user_agent
    return client


def request_file_upload(owner, repo, filepath):
    """Request a new package file upload (for creating packages)."""
    client = get_files_api()

    with catch_raise_api_exception():
        data = client.files_create(
            owner=owner,
            repo=repo,
            data={
                'filename': os.path.basename(filepath),
                'md5_checksum': calculate_file_md5(filepath)
            }
        )

    return data.identifier, data.upload_url, data.upload_fields


def upload_file(identifier, upload_url, upload_fields, filepath,
                callback=None):
    """Upload a pre-signed file to Cloudsmith."""
    upload_fields = upload_fields.items()
    upload_fields.append(
        ('file', (os.path.basename(filepath), click.open_file(filepath, 'rb')))
    )
    encoder = MultipartEncoder(upload_fields)
    monitor = MultipartEncoderMonitor(encoder, callback=callback)

    config = cloudsmith_api.Configuration()
    if config.proxy:
        proxies = {
            'http': config.proxy,
            'https': config.proxy
        }
    else:
        proxies = None

    headers = {'content-type': monitor.content_type}

    if config.user_agent:
        headers['user-agent'] = config.user_agent

    resp = requests.post(
        upload_url, data=monitor,
        headers=headers, proxies=proxies
    )

    try:
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ApiException(
            resp.status_code,
            headers=exc.response.headers,
            body=exc.response.content
        )
