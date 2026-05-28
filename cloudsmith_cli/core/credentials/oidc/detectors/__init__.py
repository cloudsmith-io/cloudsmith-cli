"""Environment detectors for OIDC token retrieval."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .aws import AWSDetector
from .base import EnvironmentDetector

if TYPE_CHECKING:
    from ... import CredentialContext

logger = logging.getLogger(__name__)

_DETECTORS: list[type[EnvironmentDetector]] = [
    AWSDetector,
]


def detect_environment(
    context: CredentialContext,
) -> EnvironmentDetector | None:
    """Try each detector in order, returning the first that matches."""
    for detector_cls in _DETECTORS:
        detector = detector_cls(context=context)
        try:
            if detector.detect():
                if context.debug:
                    logger.debug("Detected OIDC environment: %s", detector.name)
                return detector
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug(
                "Detector %s raised an exception during detection",
                detector.name,
                exc_info=True,
            )
            continue

    if context.debug:
        logger.debug("No supported OIDC environment detected")
    return None
