# Copyright 2026 Cloudsmith Ltd
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests==2.34.2"]
# ///
"""Move the release channels that VERSION holds.

The GitHub "Latest" release and the Docker Hub tags latest, MAJOR and
MAJOR.MINOR each point at one release. The last release to write a pointer
wins. If every release moves every pointer, an older release moves them back.

This script moves a channel only when VERSION is the highest published release
in that channel. For example, start with v1.40.1 as the highest release:

- v2.0.0 ships. It moves latest, 2 and 2.0.
- v1.40.2 ships with a fix for 1.x users. It moves 1 and 1.40. latest stays
  on v2.0.0.
- The v1.40.1 release is re-run. It moves no channel, because v1.40.2 holds
  1 and 1.40.
"""

import os
import re
import subprocess

import requests

RELEASE_PATTERN = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")
CHANNEL_PREFIX_LENGTHS = {"latest": 0, "major": 1, "minor": 2}


def parse_release(text):
    match = RELEASE_PATTERN.fullmatch(text)
    return tuple(int(part) for part in match.groups()) if match else None


def github_session():
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    return session


def repository_url():
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    return f"{api_url}/repos/{os.environ['GITHUB_REPOSITORY']}"


def published_releases():
    session = github_session()
    url = f"{repository_url()}/releases?per_page=100"
    tags = []
    while url:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        tags.extend(
            release["tag_name"] for release in response.json() if not release["draft"]
        )
        url = response.links.get("next", {}).get("url")
    releases = (
        parse_release(tag.removeprefix("v")) for tag in tags if tag.startswith("v")
    )
    return [release for release in releases if release]


def is_highest(version, releases, prefix_length):
    prefix = version[:prefix_length]
    return all(
        release <= version for release in releases if release[:prefix_length] == prefix
    )


def held_channels(version):
    releases = published_releases()
    return {
        channel
        for channel, prefix_length in CHANNEL_PREFIX_LENGTHS.items()
        if is_highest(version, releases, prefix_length)
    }


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
    major, minor, _ = version
    floating_tags = {
        "latest": "latest",
        "major": f"{major}",
        "minor": f"{major}.{minor}",
    }
    tag_arguments = [
        argument
        for channel, tag in floating_tags.items()
        if channel in channels
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
            f"{repository}:{os.environ['VERSION']}",
        ],
        check=True,
    )


def main():
    version = parse_release(os.environ["VERSION"])
    if version is None:
        raise SystemExit(f"VERSION {os.environ['VERSION']} is not MAJOR.MINOR.PATCH")
    channels = held_channels(version)
    print(f"This release holds: {', '.join(sorted(channels)) or 'no channel'}")
    if "latest" in channels:
        make_latest_release(os.environ["GITHUB_REF_NAME"])
    if os.environ["HAS_DOCKERHUB"] == "true":
        move_docker_tags(version, channels)


if __name__ == "__main__":
    main()
