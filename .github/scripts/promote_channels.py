# Copyright 2026 Cloudsmith Ltd
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests==2.34.2"]
# ///
"""Move the release channels that VERSION holds.

The channels are the GitHub "Latest" release and the Docker Hub tags latest,
MAJOR and MAJOR.MINOR. release_channels.py says which channels VERSION holds.
"""

import os
import subprocess

from release_channels import find_channels, github_session, repository_url


def make_latest_release(tag):
    session = github_session()
    response = session.get(f"{repository_url()}/releases/tags/{tag}", timeout=30)
    response.raise_for_status()
    response = session.patch(
        f"{repository_url()}/releases/{response.json()['id']}",
        json={"make_latest": "true"},
        timeout=30,
    )
    response.raise_for_status()


def move_docker_tags(version, channels):
    repository = os.environ["DOCKERHUB_REPOSITORY"]
    major, minor, _ = version.split(".")
    floating_tags = {
        "latest": "latest",
        "major-latest": major,
        "minor-latest": f"{major}.{minor}",
    }
    tag_arguments = [
        argument
        for channel, tag in floating_tags.items()
        if channels[channel]
        for argument in ("--tag", f"{repository}:{tag}")
    ]
    if not tag_arguments:
        print("A higher release holds every floating tag; skipping")
        return
    subprocess.run(
        [
            "docker",
            "buildx",
            "imagetools",
            "create",
            *tag_arguments,
            f"{repository}:{version}",
        ],
        check=True,
    )


def main():
    version = os.environ["VERSION"]
    channels = find_channels(version)
    if channels["latest"]:
        make_latest_release(os.environ["GITHUB_REF_NAME"])
    if os.environ["HAS_DOCKERHUB"] == "true":
        move_docker_tags(version, channels)


if __name__ == "__main__":
    main()
