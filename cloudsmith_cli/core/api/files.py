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
from ..utils import calculate_file_md5, calculate_file_md5, get_file_size
from .exceptions import ApiException, catch_raise_api_exception
from .init import get_api_client

SIMPLE_UPLOAD_MAX_FILE_SIZE = 1024 * 1024 * 1024 * 5  # 5GB
MULTIPART_CHUNK_SIZE = 1024 * 1024 * 100  # 100MB
FILES_API_BASE_URL = "https://api.cloudsmith.io/v1/files"


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


def init_multipart_upload(opts, owner, repo, filepath):
    """
    Initialize a multipart upload.
    Returns a tuple of (identifier, upload_url, upload_headers)
    """

    filename = os.path.basename(filepath)
    resp = requests.post(
        f"{FILES_API_BASE_URL}/{owner}/{repo}/",
        headers={"X-Api-Key": opts.api_key, "accept": "application/json"},
        json={
            "method": "put_parts",
            "filename": filename,
            "md5_checksum": calculate_file_md5(filepath),
        },
    )
    resp.raise_for_status()

    identifier = resp.json()["identifier"]
    upload_url = resp.json()["upload_url"]
    upload_headers = resp.json()["upload_headers"]

    return identifier, upload_url, upload_headers


def do_multipart_upload(
    opts,
    owner,
    repo,
    **kwargs,
):
    """
    Upload a file in multiple parts.
    Returns the identifier of the uploaded file.
    """
    filepath = kwargs["filepath"]
    identifier = kwargs["identifier"]
    upload_url = kwargs["upload_url"]
    upload_headers = kwargs["upload_headers"]
    progress_callback = kwargs["progress_callback"]
    
    filesize = get_file_size(filepath)
    headers = {"X-Api-Key": opts.api_key}

    with open(filepath, "rb") as f:
        offset = 0
        part_number = 1
        while offset < filesize:
            chunk_size = min(filesize, offset + MULTIPART_CHUNK_SIZE) - offset
            chunk = f.read(chunk_size)

            resp = requests.put(
                upload_url,
                headers=headers,
                data=chunk,
                params={
                    "upload_id": upload_headers["Upload-Id"],
                    "part_number": part_number,
                },
            )
            resp.raise_for_status()

            offset += chunk_size
            part_number += 1

            progress_callback(chunk_size)

    resp = requests.post(
        f"{FILES_API_BASE_URL}/{owner}/{repo}/{identifier}/complete/",
        headers=headers,
        params={"upload_id": upload_headers["Upload-Id"], "complete": "true"},
    )
    resp.raise_for_status()
    identifier = resp.json()["identifier"]

    return identifier


def init_multipart_upload(opts, owner, repo, filepath):
    """
    Initialize a multipart upload.
    Returns a tuple of (identifier, upload_url, upload_headers)
    """

    filename = os.path.basename(filepath)
    resp = requests.post(
        f"{FILES_API_BASE_URL}/{owner}/{repo}/",
        headers={"X-Api-Key": opts.api_key, "accept": "application/json"},
        json={
            "method": "put_parts",
            "filename": filename,
            "md5_checksum": calculate_file_md5(filepath),
        },
    )
    resp.raise_for_status()

    identifier = resp.json()["identifier"]
    upload_url = resp.json()["upload_url"]
    upload_headers = resp.json()["upload_headers"]

    return identifier, upload_url, upload_headers


def do_multipart_upload(
    opts,
    owner,
    repo,
    **kwargs,
):
    """
    Upload a file in multiple parts.
    Returns the identifier of the uploaded file.
    """
    filepath = kwargs["filepath"]
    identifier = kwargs["identifier"]
    upload_url = kwargs["upload_url"]
    upload_headers = kwargs["upload_headers"]
    progress_callback = kwargs["progress_callback"]
    multi_part_chunk_size = kwargs["multi_part_chunk_size"]
    
    filesize = get_file_size(filepath)
    headers = {"X-Api-Key": opts.api_key}

    with open(filepath, "rb") as f:
        offset = 0
        part_number = 1
        while offset < filesize:
            chunk_size = min(filesize, offset + multi_part_chunk_size) - offset
            chunk = f.read(chunk_size)

            resp = requests.put(
                upload_url,
                headers=headers,
                data=chunk,
                params={
                    "upload_id": upload_headers["Upload-Id"],
                    "part_number": part_number,
                },
            )
            resp.raise_for_status()

            offset += chunk_size
            part_number += 1

            progress_callback(chunk_size)

    resp = requests.post(
        f"{FILES_API_BASE_URL}/{owner}/{repo}/{identifier}/complete/",
        headers=headers,
        params={"upload_id": upload_headers["Upload-Id"], "complete": "true"},
    )
    resp.raise_for_status()
    identifier = resp.json()["identifier"]

    return identifier

