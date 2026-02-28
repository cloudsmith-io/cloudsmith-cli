#!/usr/bin/env python
"""
Wrapper for terraform-credentials-cloudsmith.

This is the entry point binary that Terraform calls to get registry credentials.
It delegates to: cloudsmith credential-helper terraform

See: https://developer.hashicorp.com/terraform/internals/credentials-helpers

Configure in ~/.terraformrc:
    credentials_helper "cloudsmith" {
        args = []
    }

Note: The binary must be discoverable by Terraform. Either symlink it into
a directory on your PATH as 'terraform-credentials-cloudsmith', or place it
in one of Terraform's default plugin search locations:
    - ~/.terraform.d/plugins/ (Linux/macOS)
    - %APPDATA%\\terraform.d\\plugins\\ (Windows)
"""
import subprocess
import sys


def main():
    """
    Terraform credential helper entry point.

    Terraform calls this with:
    - get <hostname>: Delegate to cloudsmith credential-helper terraform
    - store <hostname>: Not supported
    - forget <hostname>: Not supported
    """
    if len(sys.argv) < 3:
        print(
            "Usage: terraform-credentials-cloudsmith <get|store|forget> <hostname>",
            file=sys.stderr,
        )
        sys.exit(1)

    operation = sys.argv[1]
    hostname = sys.argv[2]

    if operation == "get":
        try:
            result = subprocess.run(
                ["cloudsmith", "credential-helper", "terraform", hostname],
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

    elif operation == "store":
        # Read and discard stdin (Terraform sends JSON)
        sys.stdin.read()
        print(
            "Error: Storing credentials is not supported. "
            "Credentials are managed by the Cloudsmith credential chain.",
            file=sys.stderr,
        )
        sys.exit(1)

    elif operation == "forget":
        print(
            "Error: Forgetting credentials is not supported. "
            "Credentials are managed by the Cloudsmith credential chain.",
            file=sys.stderr,
        )
        sys.exit(1)

    else:
        print(
            f"Error: Unknown operation '{operation}'. "
            "Valid operations: get, store, forget",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
