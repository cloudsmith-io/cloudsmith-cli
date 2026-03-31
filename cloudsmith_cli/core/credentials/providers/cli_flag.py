"""CLI flag credential provider."""

from __future__ import annotations

from ..models import CredentialContext, CredentialResult
from ..provider import CredentialProvider


class CLIFlagProvider(CredentialProvider):
    """Resolves credentials from a CLI flag value passed via CredentialContext."""

    name = "cli_flag"

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        api_key = context.api_key
        if api_key and api_key.strip():
            suffix = api_key.strip()[-4:]
            return CredentialResult(
                api_key=api_key.strip(),
                source_name="cli_flag",
                source_detail=f"--api-key flag, CLOUDSMITH_API_KEY, or credentials.ini (ends with ...{suffix})",
            )
        return None
