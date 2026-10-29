"""Measure traced heap while the multipart upload helper sends adjacent parts."""

import json
import tempfile
import tracemalloc
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cloudsmith_cli.core.api import files


def measure_peak_traced_heap(filepath):
    """Return peak traced heap for one upload with request bodies retained."""
    import requests

    files_client = Mock()

    def put(_url, data, **_kwargs):
        response = requests.Response()
        response.status_code = 200
        response.request = SimpleNamespace(body=data)
        return response

    session = SimpleNamespace(put=put)
    with (
        patch.object(files, "create_requests_session", return_value=session),
        patch.object(files, "get_files_api", return_value=files_client),
    ):
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            files.multi_part_upload_file(
                SimpleNamespace(credential=None),
                "https://upload.example.invalid/parts",
                "owner",
                "repo",
                str(filepath),
                lambda: None,
                "upload-id",
            )
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

    files_client.files_complete.assert_called_once()
    return peak


def main():
    part_size = files.CHUNK_SIZE
    file_size = 2 * part_size + 1
    with tempfile.TemporaryDirectory() as directory:
        filepath = Path(directory) / "package.raw"
        with filepath.open("wb") as output:
            output.truncate(file_size)
        peak = measure_peak_traced_heap(filepath)

    print(
        json.dumps(
            {
                "file_size_bytes": file_size,
                "part_size_bytes": part_size,
                "peak_traced_heap_bytes": peak,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
