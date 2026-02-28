#!/usr/bin/env python
"""
Wrapper for docker-credential-cloudsmith.

This is the entry point binary that Docker calls. It delegates to the main
cloudsmith credential-helper docker command.

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

    We only support 'get' and delegate to: cloudsmith credential-helper docker
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
    elif operation in ("store", "erase", "list"):
        print(
            f"Error: Operation '{operation}' is not supported. "
            "Only 'get' is available for Cloudsmith credential helper.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        print(
            f"Error: Unknown operation '{operation}'. "
            "Valid operations: get, store, erase, list",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
