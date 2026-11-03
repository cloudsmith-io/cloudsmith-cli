"""API - Files endpoints."""

import io
import os
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, BinaryIO

import cloudsmith_api
import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

from .. import ratelimits
from ..session import create_requests_session
from ..utils import calculate_file_md5
from .exceptions import ApiException, catch_raise_api_exception
from .init import get_api_client

if TYPE_CHECKING:
    from ...cli.config import Options

CHUNK_SIZE = 1024 * 1024 * 100
# Python applies a socket timeout to each send and receive, so this bounds a
# stall but not the duration of a transfer that keeps moving.
UPLOAD_TIMEOUT_SECONDS = 120.0


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


class _RewindableMultipartBody(MultipartEncoderMonitor):
    """A multipart upload body that urllib3 can rewind to resend on a retry."""

    def __init__(
        self,
        fields: list[tuple[str, Any]],
        file_obj: BinaryIO,
        callback: Callable[[MultipartEncoderMonitor], None] | None,
    ) -> None:
        super().__init__(MultipartEncoder(fields), callback=callback)
        self._file_obj = file_obj

    def __iter__(self) -> Iterator[bytes]:
        # requests records the start position, and rewinds to it on a 307 or
        # 308 redirect, only for a body that it can iterate.
        return iter(lambda: self.read(io.DEFAULT_BUFFER_SIZE), b"")

    def tell(self) -> int:
        return self.bytes_read

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if (offset, whence) != (0, os.SEEK_SET):
            raise io.UnsupportedOperation("The upload body can only rewind to 0")
        # The encoder reads the file from its current position, and the
        # content-type header already names the first boundary.
        self._file_obj.seek(0)
        self.encoder = MultipartEncoder(
            self.encoder.fields, boundary=self.encoder.boundary_value
        )
        self.bytes_read = 0
        return 0


def _send_upload_request(
    send: Callable[..., requests.Response], *args: Any, **kwargs: Any
) -> requests.Response:
    """Send an upload request, and raise a status-0 ApiException if it fails."""
    try:
        return send(*args, timeout=UPLOAD_TIMEOUT_SECONDS, **kwargs)
    except requests.RequestException as exc:
        raise ApiException(0, detail=f"{type(exc).__name__}\n{exc}") from exc


def _open_upload_file(filepath: str) -> BinaryIO:
    """Open a file to upload, and raise a status-0 ApiException if it fails."""
    try:
        return open(filepath, "rb")
    except OSError as exc:
        raise ApiException(0, detail=f"Cannot read {filepath}: {exc}") from exc


def upload_file(
    upload_url: str,
    upload_fields: dict[str, Any] | None,
    filepath: str,
    callback: Callable[[MultipartEncoderMonitor], None] | None = None,
) -> None:
    """Upload a pre-signed file to Cloudsmith."""
    with _open_upload_file(filepath) as file_obj:
        fields = list((upload_fields or {}).items())
        fields.append(("file", (os.path.basename(filepath), file_obj)))
        body = _RewindableMultipartBody(fields, file_obj, callback)

        config = cloudsmith_api.Configuration()
        if config.proxy:
            proxies = {"http": config.proxy, "https": config.proxy}
        else:
            proxies = None

        headers = {"content-type": body.content_type}

        client = get_files_api()
        headers["user-agent"] = client.api_client.user_agent

        session = create_requests_session()
        resp = _send_upload_request(
            session.post, upload_url, data=body, headers=headers, proxies=proxies
        )

    try:
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ApiException(
            resp.status_code, headers=resp.headers, body=resp.content
        ) from exc


def multi_part_upload_file(
    opts: "Options",
    upload_url: str,
    owner: str,
    repo: str,
    filepath: str,
    callback: Callable[[], None],
    upload_id: str,
) -> None:
    headers = opts.credential.auth_headers() if opts.credential else {}

    with open(filepath, "rb") as f:
        chunk_number = 1
        session = create_requests_session()
        while chunk := f.read(CHUNK_SIZE):
            resp = _send_upload_request(
                session.put,
                upload_url,
                headers=headers,
                # A file object goes out in blocks, so the timeout bounds
                # each block and not the send of the whole chunk.
                data=io.BytesIO(chunk),
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
            chunk_number += 1

    api = get_files_api()
    with catch_raise_api_exception():
        api.files_complete(
            owner,
            repo,
            identifier=upload_id,
            data={"upload_id": upload_id, "complete": True},
        )
