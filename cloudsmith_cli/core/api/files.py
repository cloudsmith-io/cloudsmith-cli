"""API - Files endpoints."""

import os

import click
import cloudsmith_api
import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

from .. import ratelimits
from ..session import create_requests_session
from ..utils import calculate_file_md5
from .exceptions import ApiException, catch_raise_api_exception
from .init import get_api_client

CHUNK_SIZE = 1024 * 1024 * 100


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


def request_file_upload(
    owner, repo, filepath, md5_checksum=None, is_multi_part_upload=False
):
    """Request a new package file upload (for creating packages)."""
    client = get_files_api()
    md5_checksum = md5_checksum or calculate_file_md5(filepath)

    method = "put_parts" if is_multi_part_upload else "post"

    with catch_raise_api_exception():
        data, _, headers = client.files_create_with_http_info(
            owner=owner,
            repo=repo,
            data={
                "filename": os.path.basename(filepath),
                "md5_checksum": md5_checksum,
                "method": method,
            },
        )

    # pylint: disable=no-member
    # Pylint detects the returned value as a tuple
    ratelimits.maybe_rate_limit(client, headers)
    return data.identifier, data.upload_url, data.upload_fields


def _send_upload_request(send, *args, **kwargs):
    """Send an upload request, and raise a status-0 ApiException if it fails."""
    try:
        return send(*args, **kwargs)
    except requests.RequestException as exc:
        raise ApiException(0, detail=f"{type(exc).__name__}\n{exc}") from exc


def upload_file(upload_url, upload_fields, filepath, callback=None):
    """Upload a pre-signed file to Cloudsmith."""
    upload_fields = list(upload_fields.items())
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
    resp = _send_upload_request(
        session.post, upload_url, data=monitor, headers=headers, proxies=proxies
    )

    try:
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ApiException(
            resp.status_code, headers=exc.response.headers, body=exc.response.content
        )


class _FilePart:
    """A seekable file-part view for Requests' length and replay handling."""

    def __init__(self, fileobj, start, length):
        self.fileobj = fileobj
        self.start = start
        self.length = length
        self.position = 0

    def __len__(self):
        return self.length

    def __iter__(self):
        self.fileobj.seek(self.start + self.position)
        while self.position < self.length:
            size = min(64 * 1024, self.length - self.position)
            chunk = self.fileobj.read(size)
            if len(chunk) != size:
                raise OSError("upload source ended before the current part")
            self.position += len(chunk)
            yield chunk

    def tell(self):
        return self.position

    def seek(self, position):
        self.position = position


def multi_part_upload_file(
    opts, upload_url, owner, repo, filepath, callback, upload_id
):
    headers = opts.credential.auth_headers() if opts.credential else {}

    with open(filepath, "rb") as f:
        chunk_number = 1
        offset = 0
        session = create_requests_session()
        while True:
            file_size = os.fstat(f.fileno()).st_size
            chunk_size = min(CHUNK_SIZE, file_size - offset)
            if chunk_size <= 0:
                break

            part = _FilePart(f, offset, chunk_size)
            resp = _send_upload_request(
                session.put,
                upload_url,
                headers=headers,
                data=part,
                params={
                    "upload_id": upload_id,
                    "part_number": chunk_number,
                },
            )
            try:
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise ApiException(
                    resp.status_code,
                    headers=exc.response.headers,
                    body=exc.response.content,
                )
            callback()
            offset += chunk_size
            chunk_number += 1

    api = get_files_api()
    with catch_raise_api_exception():
        api.files_complete(
            owner,
            repo,
            identifier=upload_id,
            data={"upload_id": upload_id, "complete": True},
        )
