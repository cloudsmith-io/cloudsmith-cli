#!/usr/bin/env python
"""
Wrapper for npm-credentials-cloudsmith (pnpm tokenHelper).

This is the entry point binary that pnpm calls to get an auth token.
It delegates to: cloudsmith credential-helper npm

See: https://pnpm.io/npmrc#url-tokenhelper

Configure in user ~/.npmrc:
    //npm.cloudsmith.io/:tokenHelper=/absolute/path/to/npm-credentials-cloudsmith

Find the path with: which npm-credentials-cloudsmith
"""
import subprocess
import sys


def main():
    """pnpm tokenHelper entry point. Delegates to cloudsmith credential-helper npm."""
    try:
        result = subprocess.run(
            ["cloudsmith", "credential-helper", "npm"],
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


if __name__ == "__main__":
    main()
