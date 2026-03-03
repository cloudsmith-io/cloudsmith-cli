"""GitLab CI OIDC detector.

Reads OIDC token from environment variables populated by GitLab's
``id_tokens`` configuration in ``.gitlab-ci.yml``.

References:
    https://docs.gitlab.com/ci/cloud_services/
    https://docs.cloudsmith.com/integrations/integrating-with-gitlab-cicd
"""

from __future__ import annotations

import os

from .base import EnvironmentDetector


class GitLabCIDetector(EnvironmentDetector):
    """Detects GitLab CI and reads OIDC token from environment variable.

    GitLab requires users to configure ``id_tokens`` in .gitlab-ci.yml.
    The token is exposed as an environment variable with a user-chosen name.
    We check common conventions: CLOUDSMITH_OIDC_TOKEN, CI_JOB_JWT_V2, CI_JOB_JWT.
    """

    name = "GitLab CI"

    TOKEN_ENV_VARS = ["CLOUDSMITH_OIDC_TOKEN", "CI_JOB_JWT_V2", "CI_JOB_JWT"]

    def detect(self) -> bool:
        if os.environ.get("GITLAB_CI") != "true":
            return False
        return any(os.environ.get(var) for var in self.TOKEN_ENV_VARS)

    def get_token(self) -> str:
        for var in self.TOKEN_ENV_VARS:
            token = os.environ.get(var)
            if token:
                return token
        raise ValueError(
            "GitLab CI detected but no OIDC token found. "
            "Configure id_tokens in .gitlab-ci.yml and set one of: "
            + ", ".join(self.TOKEN_ENV_VARS)
        )
