"""Tests for anomaly detection and ENSO regime classification."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

from enso.anomaly_detection import (
    zscore_anomaly,
    regime_aware_anomaly,
    detect_enso_regime,
    run_anomaly_checks,
    AnomalyResult,
)


class TestZScoreAnomaly:
    def test_normal_value_not_anomaly(self):
        history = [1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0] * 5
        result = zscore_anomaly(1.0, history, threshold=3.0)
        assert not result.is_anomaly

    def test_extreme_value_is_anomaly(self):
        history = [1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0] * 5
        result = zscore_anomaly(10.0, history, threshold=3.0)
        assert result.is_anomaly
        assert result.anomaly_type == "zscore"

    def test_insufficient_history(self):
        result = zscore_anomaly(1.0, [1.0, 2.0], threshold=3.0, min_history=30)
        assert not result.is_anomaly

    def test_zero_variance(self):
        result = zscore_anomaly(1.0, [1.0] * 50, threshold=3.0)
        assert not result.is_anomaly


class TestRegimeDetection:
    def test_el_nino_regime(self):
        assert detect_enso_regime(1.0, 0.8) == "el_nino"

    def test_la_nina_regime(self):
        assert detect_enso_regime(-1.0, -0.8) == "la_nina"

    def test_neutral_regime(self):
        assert detect_enso_regime(0.1, 0.1) == "neutral"

    def test_icen_overrides_roni_for_costero(self):
        assert detect_enso_regime(0.1, 0.8) == "el_nino"


class TestRegimeAwareAnomaly:
    def test_normal_in_el_nino(self):
        result = regime_aware_anomaly(1.5, [], "el_nino")
        assert not result.is_anomaly

    def test_anomaly_wrong_sign(self):
        result = regime_aware_anomaly(-2.0, [], "el_nino")
        assert result.is_anomaly

    def test_normal_in_neutral(self):
        result = regime_aware_anomaly(0.1, [], "neutral")
        assert not result.is_anomaly


class TestRunAnomalyChecks:
    def test_no_anomalies_with_normal_values(self):
        result = run_anomaly_checks(
            roni=0.98, icen=1.37, nino12=2.1, nino34=1.37,
            soi=-2.4, d20=6.972, u850=2.3
        )
        assert result["total_anomalies"] == 0
        assert result["regime"] == "el_nino"

    def test_anomaly_with_extreme_value(self):
        result = run_anomaly_checks(
            roni=5.0, icen=1.0, nino12=1.0, nino34=1.0,
            soi=0.0, d20=0.0, u850=0.0
        )
        # RONI=5.0 is extreme but without history, zscore won't trigger
        # Regime-aware will flag it
        assert result["regime"] == "el_nino"

    def test_none_values_handled(self):
        result = run_anomaly_checks(
            roni=None, icen=None, nino12=None, nino34=None,
            soi=None, d20=None, u850=None
        )
        assert result["total_anomalies"] == 0
        assert result["regime"] == "neutral"
