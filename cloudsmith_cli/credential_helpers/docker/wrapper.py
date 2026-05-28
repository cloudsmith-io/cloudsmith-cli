#!/usr/bin/env python
"""
Wrapper for docker-credential-cloudsmith.

This is the entry point binary that Docker calls. It delegates to the main
cloudsmith credential-helper docker command for credential lookups and handles
read-only protocol operations locally.

See: https://github.com/docker/docker-credential-helpers

Configure in ~/.docker/config.json:
    {
        "credHelpers": {
            "docker.cloudsmith.io": "cloudsmith"
        }
    }
"""
import subprocess
import sys


def main():
    """
    Docker credential helper wrapper.

    Docker calls this with the operation as argv[1]:
    - get: Retrieve credentials
    - store: Store credentials (not supported)
    - erase: Erase credentials (not supported)
    - list: List credentials (not supported)

    The helper is read-only, so only 'get' returns Cloudsmith credentials.
    """
    if len(sys.argv) < 2:
        print(
            "Error: Missing operation argument. "
            "Usage: docker-credential-cloudsmith <get|store|erase|list>",
            file=sys.stderr,
        )
        sys.exit(1)

    operation = sys.argv[1]

    if operation == "get":
        try:
            result = subprocess.run(
                ["cloudsmith", "credential-helper", "docker"],
                stdin=sys.stdin,
                capture_output=False,
                check=False,
            )
            sys.exit(result.returncode)
        except FileNotFoundError:
            print(
                "Error: 'cloudsmith' command not found. "
                "Make sure cloudsmith-cli is installed.",
                file=sys.stderr,
            )
            sys.exit(1)
    elif operation in ("store", "erase"):
        try:
            if not sys.stdin.isatty():
                sys.stdin.read()
        except (OSError, ValueError):
            pass
        sys.exit(0)
    elif operation == "list":
        print("{}")
        sys.exit(0)
    else:
        print(
            f"Error: Unknown operation '{operation}'. "
            "Valid operations: get, store, erase, list",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
