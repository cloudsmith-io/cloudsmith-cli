# Copyright 2026 Cloudsmith Ltd
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Print the release channels that VERSION moves, as key=value lines for $GITHUB_OUTPUT.

A channel (latest, MAJOR, MAJOR.MINOR) moves only when VERSION is the highest
published release in that channel. A pre-release moves no channel.
"""

import os
import re
import subprocess

RELEASE_PATTERN = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")
CHANNEL_PREFIX_LENGTHS = {"latest": 0, "major-latest": 1, "minor-latest": 2}


def parse_release(text):
    match = RELEASE_PATTERN.fullmatch(text)
    return tuple(int(part) for part in match.groups()) if match else None


def published_releases():
    tags = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{os.environ['GITHUB_REPOSITORY']}/releases",
            "--jq",
            ".[] | select(.draft == false and .prerelease == false) | .tag_name",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    releases = (
        parse_release(tag.removeprefix("v")) for tag in tags if tag.startswith("v")
    )
    return [release for release in releases if release]


def is_highest(version, releases, prefix_length):
    prefix = version[:prefix_length]
    return all(
        release <= version for release in releases if release[:prefix_length] == prefix
    )


def main():
    version = parse_release(os.environ["VERSION"])
    channels = {"prerelease": version is None}
    releases = published_releases() if version else []
    for channel, prefix_length in CHANNEL_PREFIX_LENGTHS.items():
        channels[channel] = bool(version) and is_highest(
            version, releases, prefix_length
        )
    for channel, moves in channels.items():
        print(f"{channel}={str(moves).lower()}")


if __name__ == "__main__":
    main()
