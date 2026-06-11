"""Environment detectors for OIDC token retrieval."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .aws import AWSDetector
from .azure_devops import AzureDevOpsDetector
from .base import EnvironmentDetector
from .bitbucket_pipelines import BitbucketPipelinesDetector
from .circleci import CircleCIDetector
from .generic import GenericDetector
from .github_actions import GitHubActionsDetector
from .gitlab_ci import GitLabCIDetector

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ... import CredentialContext

logger = logging.getLogger(__name__)

_DETECTORS: list[type[EnvironmentDetector]] = [
    CircleCIDetector,
    AzureDevOpsDetector,
    GitHubActionsDetector,
    BitbucketPipelinesDetector,
    GitLabCIDetector,
    AWSDetector,
    GenericDetector,
]


def registered_detectors() -> list[type[EnvironmentDetector]]:
    """Return the registered OIDC detectors in their default priority order."""
    return list(_DETECTORS)


def disable_env_var(identifier: str) -> str:
    """The environment variable that disables the detector with this id."""
    return f"CLOUDSMITH_OIDC_{identifier.upper()}_DISABLED"


def _is_disabled_value(value: str | None) -> bool:
    """Only the literal string ``true`` (case-insensitive) disables a detector."""
    return (value or "").strip().lower() == "true"


def disabled_detectors_from_env(environ: Mapping[str, str]) -> frozenset[str]:
    """Detector ids disabled via their CLOUDSMITH_OIDC_<ID>_DISABLED variable."""
    return frozenset(
        detector_cls.id
        for detector_cls in _DETECTORS
        if _is_disabled_value(environ.get(disable_env_var(detector_cls.id)))
    )


def _ordered_detectors(order: str | None) -> list[type[EnvironmentDetector]]:
    """Detectors in evaluation order, honouring an explicit order string.

    When ``order`` is unset/empty the default registration order is used.
    Otherwise only the listed ids are considered, in the listed order;
    unknown ids are logged and skipped, and duplicate ids keep their first
    position so each detector is evaluated at most once.
    """
    raw_order = (order or "").strip()
    if not raw_order:
        return list(_DETECTORS)

    detectors_by_id = {detector_cls.id: detector_cls for detector_cls in _DETECTORS}
    ordered: dict[str, type[EnvironmentDetector]] = {}
    for token in raw_order.split(","):
        identifier = token.strip().lower()
        if not identifier or identifier in ordered:
            continue
        detector_cls = detectors_by_id.get(identifier)
        if detector_cls is None:
            logger.debug("Ignoring unknown OIDC detector id: %s", identifier)
            continue
        ordered[identifier] = detector_cls
    return list(ordered.values())


def _enabled_detectors(
    order: str | None, disabled: frozenset[str]
) -> list[type[EnvironmentDetector]]:
    """Ordered detectors with disabled ones removed (disable always wins)."""
    return [
        detector_cls
        for detector_cls in _ordered_detectors(order)
        if detector_cls.id not in disabled
    ]


def detect_environment(
    context: CredentialContext,
) -> EnvironmentDetector | None:
    """Try each detector in order, returning the first that matches."""
    enabled = _enabled_detectors(
        context.oidc_detector_order, context.oidc_disabled_detectors
    )
    if not enabled:
        logger.debug("No OIDC detectors enabled after applying order/disable controls")
    for detector_cls in enabled:
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
