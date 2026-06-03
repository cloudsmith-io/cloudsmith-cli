"""Credentials file provider."""

from __future__ import annotations

from ..models import CredentialContext, CredentialResult
from ..provider import CredentialProvider


class CredentialsFileProvider(CredentialProvider):
    """Resolves credentials from the api_key stored in credentials.ini."""

    name = "credentials_file"

    def resolve(self, context: CredentialContext) -> CredentialResult | None:
        api_key = context.api_key_from_file
        if api_key and api_key.strip():
            api_key = api_key.strip()
            suffix = api_key[-4:]
            return CredentialResult(
                api_key=api_key,
                source_name="credentials_file",
                source_detail=f"credentials.ini (ends with ...{suffix})",
            )
        return None
