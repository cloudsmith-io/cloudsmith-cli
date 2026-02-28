#!/usr/bin/env python
"""
Wrapper for cargo-credential-cloudsmith.

This is the entry point binary that Cargo calls to get registry credentials.
It delegates to: cloudsmith credential-helper cargo --cargo-plugin

See: https://doc.rust-lang.org/cargo/reference/credential-provider-protocol.html

Configure in ~/.cargo/config.toml:
    [registry]
    credential-provider = ["cargo-credential-cloudsmith"]

    # Or for a specific registry:
    [registries.cloudsmith]
    index = "sparse+https://cargo.cloudsmith.io/org/repo/"
    credential-provider = ["cargo-credential-cloudsmith"]
"""
import subprocess
import sys


def main():
    """Cargo credential provider entry point. Delegates to cloudsmith credential-helper cargo."""
    try:
        result = subprocess.run(
            ["cloudsmith", "credential-helper", "cargo", "--cargo-plugin"],
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
