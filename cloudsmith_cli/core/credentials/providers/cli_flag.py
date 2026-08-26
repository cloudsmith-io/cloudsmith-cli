"""CLI flag credential provider."""

from __future__ import annotations

from ..models import CredentialContext, CredentialResult
from ..provider import CredentialProvider


class CLIFlagProvider(CredentialProvider):
    """Resolves credentials from the --api-key CLI flag."""

    name = "cli_flag"

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        api_key = context.api_key_from_flag
        if api_key and api_key.strip():
            api_key = api_key.strip()
            suffix = api_key[-4:]
            return CredentialResult(
                api_key=api_key,
                source_name="cli_flag",
                source_detail=f"--api-key flag (ends with ...{suffix})",
            )
        return None
