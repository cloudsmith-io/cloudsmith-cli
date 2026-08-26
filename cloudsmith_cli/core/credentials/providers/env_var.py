"""Environment variable credential provider."""

from __future__ import annotations

from ..models import CredentialContext, CredentialResult
from ..provider import CredentialProvider


class EnvVarProvider(CredentialProvider):
    """Resolves credentials from the CLOUDSMITH_API_KEY environment variable."""

    name = "env_var"

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        api_key = context.api_key_from_env
        if api_key and api_key.strip():
            api_key = api_key.strip()
            suffix = api_key[-4:]
            return CredentialResult(
                api_key=api_key,
                source_name="env_var",
                source_detail=f"CLOUDSMITH_API_KEY env var (ends with ...{suffix})",
            )
        return None
