# Copyright 2026 Cloudsmith Ltd
"""GitLab CI OIDC detector.

Reads an OIDC token from environment variables populated by GitLab's
``id_tokens`` configuration in ``.gitlab-ci.yml``.

References:
    https://docs.gitlab.com/ci/cloud_services/
    https://docs.cloudsmith.com/integrations/integrating-with-gitlab-cicd
"""

from __future__ import annotations

import os

from .base import EnvironmentDetector


class GitLabCIDetector(EnvironmentDetector):
    """Detects GitLab CI and reads an OIDC token from an environment variable.

    GitLab requires users to configure ``id_tokens`` in ``.gitlab-ci.yml``,
    minting a token with ``aud`` set to the Cloudsmith OIDC endpoint and
    exposing it as ``CLOUDSMITH_OIDC_TOKEN``. The legacy ``CI_JOB_JWT``/
    ``CI_JOB_JWT_V2`` variables are deliberately not consulted: they were
    removed in GitLab 17.0, carry the GitLab instance URL as their audience
    (not the Cloudsmith audience the token exchange validates), and were
    auto-injected into every job on older instances.
    """

    name = "GitLab CI"

    TOKEN_ENV_VAR = "CLOUDSMITH_OIDC_TOKEN"

    def detect(self) -> bool:
        if os.environ.get("GITLAB_CI") != "true":
            return False
        return bool(os.environ.get(self.TOKEN_ENV_VAR))

    def get_token(self) -> str:
        token = os.environ.get(self.TOKEN_ENV_VAR)
        if token:
            return token
        raise ValueError(
            "GitLab CI detected but no OIDC token found. "
            "Configure id_tokens in .gitlab-ci.yml and expose it as "
            + self.TOKEN_ENV_VAR
        )
