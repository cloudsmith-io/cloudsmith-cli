import json
import time

import pytest

from ....core.api.files import CHUNK_SIZE
from ...commands.delete import delete
from ...commands.list_ import list_
from ...commands.push import push
from ...commands.status import status
from ..utils import random_str


@pytest.mark.usefixtures("set_api_key_env_var", "set_api_host_env_var")
@pytest.mark.parametrize(
    "filesize",
    [
        1,  # A tiny file that will be uploaded using python bindings as a one-off post.
        CHUNK_SIZE * 3,  # A large file that will be uploaded to S3 in multiple chunks.
    ],
)
def test_push_and_delete_raw_package(
    runner, organization, tmp_repository, tmp_path, filesize
):
    # List packages again - should be empty.
    org_repo = f'{organization}/{tmp_repository["slug"]}'
    result = runner.invoke(
        list_, args=["pkgs", org_repo, "-F", "json"], catch_exceptions=False
    )
    data = json.loads(result.output)["data"]
    assert len(data) == 0

    # Create a file of the requested size.
    pkg_file = tmp_path / f"{random_str()}.txt"
    with open(pkg_file, "wb") as f:
        # Fill the file with null bytes.
        f.truncate(filesize)

    # Push it to cloudsmith as a raw package using the push command.
    runner.invoke(
        push, args=["raw", org_repo, str(pkg_file.resolve())], catch_exceptions=False
    )

    # List packages, check that it is there.
    result = runner.invoke(
        list_, args=["pkgs", org_repo, "-F", "json"], catch_exceptions=False
    )
    data = json.loads(result.output)["data"]
    assert len(data) == 1
    small_file_data = data[0]
    assert small_file_data["filename"] == pkg_file.name

    # Wait for the package to sync.
    org_repo_package = f"{org_repo}/{small_file_data['slug']}"
    for _ in range(10):
        time.sleep(5)
        result = runner.invoke(status, args=[org_repo_package], catch_exceptions=False)
        if "Fully Synchronised" in result.output:
            break
    else:
        raise TimeoutError("Test timed out waiting for package sync")

    # Delete the package.
    runner.invoke(delete, args=["-y", org_repo_package], catch_exceptions=False)

    # Wait for package deletion to take effect.
    for _ in range(10):
        time.sleep(5)
        result = runner.invoke(status, args=[org_repo_package], catch_exceptions=False)
        if "status: 404 - Not Found" in result.output:
            break
    else:
        raise TimeoutError("Test timed out waiting for package deletion")

    # List packages again - should be empty.
    result = runner.invoke(
        list_, args=["pkgs", org_repo, "-F", "json"], catch_exceptions=False
    )
    data = json.loads(result.output)["data"]
    assert len(data) == 0
