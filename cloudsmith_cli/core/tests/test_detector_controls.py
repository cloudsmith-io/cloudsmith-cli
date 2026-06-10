# Copyright 2026 Cloudsmith Ltd
"""Tests for OIDC detector selection controls (disable set + order)."""

from unittest import mock

import pytest

from cloudsmith_cli.core.credentials.models import CredentialContext
from cloudsmith_cli.core.credentials.oidc import detectors as detectors_pkg
from cloudsmith_cli.core.credentials.oidc.detectors import (
    detect_environment,
    disable_env_var,
    disabled_detectors_from_env,
    registered_detectors,
)
from cloudsmith_cli.core.credentials.oidc.detectors.base import EnvironmentDetector


class _FakeDetector(EnvironmentDetector):
    detects = True

    def detect(self) -> bool:
        return self.detects

    def get_token(self) -> str:
        return f"{self.id}-token"


class AlphaDetector(_FakeDetector):
    name = "Alpha"
    id = "alpha"


class BravoDetector(_FakeDetector):
    name = "Bravo"
    id = "bravo"


@pytest.fixture
def fake_detectors():
    """Register two always-matching fake detectors, Alpha before Bravo."""
    with mock.patch.object(detectors_pkg, "_DETECTORS", [AlphaDetector, BravoDetector]):
        yield


def _context(**kwargs):
    return CredentialContext(**kwargs)


class TestDefaultBehaviour:
    def test_first_in_default_order_wins(self, fake_detectors):
        detector = detect_environment(_context())
        assert isinstance(detector, AlphaDetector)

    def test_returns_none_when_nothing_detects(self, fake_detectors):
        with mock.patch.object(AlphaDetector, "detects", False), mock.patch.object(
            BravoDetector, "detects", False
        ):
            assert detect_environment(_context()) is None


class TestDisabledDetectors:
    def test_disabled_detector_is_skipped(self, fake_detectors):
        detector = detect_environment(
            _context(oidc_disabled_detectors=frozenset({"alpha"}))
        )
        assert isinstance(detector, BravoDetector)

    def test_disabling_all_returns_none(self, fake_detectors):
        assert (
            detect_environment(
                _context(oidc_disabled_detectors=frozenset({"alpha", "bravo"}))
            )
            is None
        )


class TestDisabledDetectorsFromEnv:
    def test_env_var_name(self):
        assert disable_env_var("alpha") == "CLOUDSMITH_OIDC_ALPHA_DISABLED"

    @pytest.mark.parametrize("value", ["true", "TRUE", "  true  ", "True"])
    def test_truthy_values_disable(self, fake_detectors, value):
        disabled = disabled_detectors_from_env(
            {"CLOUDSMITH_OIDC_ALPHA_DISABLED": value}
        )
        assert disabled == frozenset({"alpha"})

    @pytest.mark.parametrize("value", ["false", "", "   ", "1", "yes", "on", "0"])
    def test_non_true_values_do_not_disable(self, fake_detectors, value):
        disabled = disabled_detectors_from_env(
            {"CLOUDSMITH_OIDC_ALPHA_DISABLED": value}
        )
        assert disabled == frozenset()

    def test_unset_means_enabled(self, fake_detectors):
        assert disabled_detectors_from_env({}) == frozenset()


class TestDetectorOrder:
    def test_order_reorders_evaluation(self, fake_detectors):
        detector = detect_environment(_context(oidc_detector_order="bravo,alpha"))
        assert isinstance(detector, BravoDetector)

    def test_order_limits_candidate_set(self, fake_detectors):
        # Only bravo is listed; alpha must not be considered even though it
        # would otherwise match first.
        with mock.patch.object(BravoDetector, "detects", False):
            assert detect_environment(_context(oidc_detector_order="bravo")) is None

    def test_unknown_id_is_ignored(self, fake_detectors):
        detector = detect_environment(_context(oidc_detector_order="nope,alpha"))
        assert isinstance(detector, AlphaDetector)

    def test_empty_order_falls_back_to_default(self, fake_detectors):
        detector = detect_environment(_context(oidc_detector_order="   "))
        assert isinstance(detector, AlphaDetector)


class TestOrderAndDisableCompose:
    def test_disable_wins_over_order(self, fake_detectors):
        # alpha is listed first in the order but disabled, so bravo wins.
        detector = detect_environment(
            _context(
                oidc_detector_order="alpha,bravo",
                oidc_disabled_detectors=frozenset({"alpha"}),
            )
        )
        assert isinstance(detector, BravoDetector)


class TestRealDetectorIds:
    def test_all_registered_detectors_have_unique_ids(self):
        ids = [cls.id for cls in registered_detectors()]
        assert "base" not in ids
        assert len(ids) == len(set(ids))
        assert "generic" in ids
