"""CI/CD environment detectors for OIDC token retrieval."""

from __future__ import annotations

import logging

from .aws import AWSDetector
from .azure_devops import AzureDevOpsDetector
from .base import (
    DEFAULT_OIDC_AUDIENCE,
    OIDC_AUDIENCE_ENV_VAR,
    EnvironmentDetector,
    get_oidc_audience,
)
from .bitbucket_pipelines import BitbucketPipelinesDetector
from .circleci import CircleCIDetector
from .generic import GenericDetector
from .github_actions import GitHubActionsDetector
from .gitlab_ci import GitLabCIDetector

logger = logging.getLogger(__name__)

# Ordered list of detectors to try
_DETECTORS: list[type[EnvironmentDetector]] = [
    GitHubActionsDetector,
    GitLabCIDetector,
    CircleCIDetector,
    AzureDevOpsDetector,
    BitbucketPipelinesDetector,
    AWSDetector,
    GenericDetector,
]


def detect_environment(debug: bool = False) -> EnvironmentDetector | None:
    """Try each detector in order, returning the first that matches."""
    for detector_cls in _DETECTORS:
        detector = detector_cls()
        try:
            if detector.detect():
                if debug:
                    logger.debug("Detected CI/CD environment: %s", detector.name)
                return detector
        except Exception:  # pylint: disable=broad-exception-caught
            # Intentionally broad - one detector failing shouldn't stop others
            logger.debug(
                "Detector %s raised an exception during detection",
                detector.name,
                exc_info=True,
            )
            continue

    if debug:
        logger.debug("No CI/CD environment detected for OIDC")
    return None
