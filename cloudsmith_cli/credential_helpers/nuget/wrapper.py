#!/usr/bin/env python
"""
Wrapper for CredentialProvider.Cloudsmith (NuGet credential provider).

This is the entry point binary that NuGet calls to get feed credentials.
It delegates to: cloudsmith credential-helper nuget

See: https://learn.microsoft.com/en-us/nuget/reference/extensibility/nuget-exe-credential-providers

Configure by setting NUGET_CREDENTIALPROVIDERS_PATH to include the directory
containing this binary, or place it alongside nuget.exe.

    export NUGET_CREDENTIALPROVIDERS_PATH=/path/to/directory/

For dotnet CLI, place in one of the plugin search directories:
    - ~/.nuget/plugins/netcore/CredentialProvider.Cloudsmith/ (Linux/macOS)
    - %USERPROFILE%\\.nuget\\plugins\\netcore\\CredentialProvider.Cloudsmith\\ (Windows)

Usage by NuGet:
    CredentialProvider.Cloudsmith -uri <packageSourceUri> [-isRetry] [-nonInteractive]

Exit codes:
    0: Success (credentials returned as JSON on stdout)
    1: Provider not applicable for this URI
    2: Failure
"""
import argparse
import subprocess
import sys


def main():
    """NuGet credential provider entry point. Delegates to cloudsmith credential-helper nuget."""
    parser = argparse.ArgumentParser(description="Cloudsmith NuGet Credential Provider")
    parser.add_argument("-uri", required=True, help="Package source URI")
    parser.add_argument("-isRetry", action="store_true", help="Whether this is a retry")
    parser.add_argument(
        "-nonInteractive", action="store_true", help="Non-interactive mode"
    )

    args = parser.parse_args()

    try:
        result = subprocess.run(
            ["cloudsmith", "credential-helper", "nuget", args.uri],
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
