# Copyright 2026 Cloudsmith Ltd
"""Tests for config-file + CLI-layer OIDC detector controls."""

import pytest

from ..config import ConfigReader, Options
from ..decorators import _config_disabled_detectors, _warn_on_oidc_detector_controls


@pytest.fixture
def config_file(tmp_path):
    """Yield a writer for a temporary config.ini, restoring reader state."""
    original_files = list(ConfigReader.config_files)

    def write(body):
        path = tmp_path / "config.ini"
        path.write_text(body)
        return str(path)

    yield write
    ConfigReader.config_files = original_files


class TestConfigFileControls:
    def test_detector_order_is_read_from_config(self, config_file):
        path = config_file("[default]\noidc_detector_order = github, aws\n")
        opts = Options()
        opts.load_config_file(path)
        assert opts.oidc_detector_order == "github, aws"

    def test_disabled_detectors_is_read_from_config(self, config_file):
        path = config_file("[default]\noidc_disabled_detectors = aws,gitlab\n")
        opts = Options()
        opts.load_config_file(path)
        assert opts.oidc_disabled_detectors == "aws,gitlab"


class TestConfigDisabledDetectors:
    def test_parses_comma_separated_ids(self):
        assert _config_disabled_detectors("aws, gitlab") == frozenset({"aws", "gitlab"})

    def test_lowercases_and_strips(self):
        assert _config_disabled_detectors("  AWS , GitLab ") == frozenset(
            {"aws", "gitlab"}
        )

    def test_empty_or_none_is_empty_set(self):
        assert _config_disabled_detectors(None) == frozenset()
        assert _config_disabled_detectors("  ") == frozenset()


class TestDetectorControlWarnings:
    def test_unknown_id_warns(self, capsys):
        _warn_on_oidc_detector_controls("github,nope", frozenset())
        err = capsys.readouterr().err
        assert "nope" in err
        assert "github" not in err.split("Valid ids", 1)[0]

    def test_no_warning_when_all_ids_known(self, capsys):
        _warn_on_oidc_detector_controls("github,aws", frozenset())
        assert capsys.readouterr().err == ""

    def test_no_warning_without_controls(self, capsys):
        _warn_on_oidc_detector_controls(None, frozenset())
        assert capsys.readouterr().err == ""

    def test_warns_when_no_detectors_enabled_via_order(self, capsys):
        _warn_on_oidc_detector_controls("nope", frozenset())
        assert "no detectors are enabled" in capsys.readouterr().err.lower()

    def test_warns_when_order_fully_disabled(self, capsys):
        _warn_on_oidc_detector_controls("aws", frozenset({"aws"}))
        assert "no detectors are enabled" in capsys.readouterr().err.lower()

    def test_no_enabled_warning_in_normal_case(self, capsys):
        _warn_on_oidc_detector_controls("github,aws", frozenset())
        assert "no detectors are enabled" not in capsys.readouterr().err.lower()
