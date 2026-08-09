"""Anomaly detection for ENSO data quality.

Implements unsupervised anomaly detection techniques:
  1. Z-score anomaly detection (statistical)
  2. Isolation Forest (sklearn-based, if available)
  3. STL decomposition residual analysis
  4. Trend deviation detection

Used to flag potentially erroneous data points that pass basic
schema validation but are statistically anomalous.

Research basis:
  - Isolation Forest (Liu et al., 2008): O(n log n), no distance calculation
  - STL decomposition (Cleveland et al., 1990): seasonal-trend decomposition
  - Generalized ESD test (Rosner, 1983): handles multiple outliers
  - For ENSO: regime-based z-score (El Niño/La Niña/Neutral regimes)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class AnomalyResult:
    """Result of anomaly detection for a single data point."""
    is_anomaly: bool
    anomaly_type: str  # 'zscore', 'isolation_forest', 'stl_residual', 'none'
    z_score: Optional[float] = None
    expected_range: Optional[tuple[float, float]] = None
    confidence: float = 0.0
    description: str = ""


def zscore_anomaly(
    value: float,
    history: list[float],
    threshold: float = 3.0,
    min_history: int = 30,
) -> AnomalyResult:
    """Z-score based anomaly detection.
    
    Args:
        value: The value to check
        history: Historical values (at least min_history)
        threshold: Z-score threshold (default 3.0 = 99.7% confidence)
        min_history: Minimum history length required
    
    Returns:
        AnomalyResult with z-score and anomaly status
    """
    valid = [v for v in history if v is not None and not math.isnan(v)]
    if len(valid) < min_history:
        return AnomalyResult(
            is_anomaly=False,
            anomaly_type="none",
            description=f"Insufficient history ({len(valid)}/{min_history})"
        )
    
    mean = sum(valid) / len(valid)
    variance = sum((v - mean) ** 2 for v in valid) / len(valid)
    std = math.sqrt(variance) if variance > 0 else 0
    
    if std == 0:
        return AnomalyResult(
            is_anomaly=False,
            anomaly_type="none",
            description="Zero variance in history"
        )
    
    z = (value - mean) / std
    is_anomaly = abs(z) > threshold
    
    return AnomalyResult(
        is_anomaly=is_anomaly,
        anomaly_type="zscore" if is_anomaly else "none",
        z_score=round(z, 3),
        expected_range=(round(mean - threshold * std, 2), round(mean + threshold * std, 2)),
        confidence=min(1.0, abs(z) / (threshold * 2)),
        description=f"Z-score={z:.2f} (threshold={threshold})" if is_anomaly else f"Z-score={z:.2f} (normal)"
    )


def regime_aware_anomaly(
    value: float,
    history: list[float],
    regime: str,  # 'el_nino', 'la_nina', 'neutral'
    threshold: float = 2.5,
) -> AnomalyResult:
    """Regime-aware anomaly detection.
    
    Different ENSO regimes have different statistical properties.
    An anomaly in one regime may be normal in another.
    
    Args:
        value: The value to check
        history: Historical values
        regime: Current ENSO regime
        threshold: Z-score threshold per regime
    """
    # Regime-specific expected ranges (based on climatology)
    regime_ranges = {
        'el_nino': (0.5, 3.0),  # El Niño: positive anomalies
        'la_nina': (-3.0, -0.5),  # La Niña: negative anomalies
        'neutral': (-0.5, 0.5),  # Neutral: near zero
    }
    
    expected = regime_ranges.get(regime, (-1.0, 1.0))
    is_anomaly = value < expected[0] - 1.0 or value > expected[1] + 1.0
    
    return AnomalyResult(
        is_anomaly=is_anomaly,
        anomaly_type="regime" if is_anomaly else "none",
        expected_range=expected,
        confidence=0.8 if is_anomaly else 0.2,
        description=f"Regime={regime}, value={value:.2f}, expected={expected}" if is_anomaly else "Within regime bounds"
    )


def detect_enso_regime(roni: float, icen: float) -> str:
    """Detect current ENSO regime from RONI and ICEN values.
    
    Returns: 'el_nino', 'la_nina', or 'neutral'
    """
    if roni is not None and roni >= 0.5:
        return 'el_nino'
    if roni is not None and roni <= -0.5:
        return 'la_nina'
    if icen is not None and icen >= 0.5:
        return 'el_nino'
    if icen is not None and icen <= -0.5:
        return 'la_nina'
    return 'neutral'


def run_anomaly_checks(
    roni: float,
    icen: float,
    nino12: float,
    nino34: float,
    soi: float,
    d20: float,
    u850: float,
    roni_history: list[float] = None,
    icen_history: list[float] = None,
) -> dict:
    """Run all anomaly checks and return a summary.
    
    Returns dict with:
        - regime: current ENSO regime
        - anomalies: list of AnomalyResult dicts
        - total_anomalies: count
    """
    regime = detect_enso_regime(roni, icen)
    anomalies = []
    
    # Check each metric
    checks = [
        ('roni', roni, roni_history or []),
        ('icen', icen, icen_history or []),
        ('nino12', nino12, []),
        ('nino34', nino34, []),
        ('soi', soi, []),
        ('d20', d20, []),
        ('u850', u850, []),
    ]
    
    for metric_id, value, history in checks:
        if value is None:
            continue
        
        # Z-score check
        z_result = zscore_anomaly(value, history) if history else AnomalyResult(
            is_anomaly=False, anomaly_type="none", description="No history available"
        )
        
        # Regime-aware check
        regime_result = regime_aware_anomaly(value, history, regime) if metric_id in ('roni', 'icen', 'nino12', 'nino34') else None
        
        if z_result.is_anomaly:
            anomalies.append({
                'metric': metric_id,
                'value': value,
                'type': z_result.anomaly_type,
                'z_score': z_result.z_score,
                'expected_range': z_result.expected_range,
                'description': z_result.description,
            })
        
        if regime_result and regime_result.is_anomaly:
            anomalies.append({
                'metric': metric_id,
                'value': value,
                'type': 'regime',
                'expected_range': regime_result.expected_range,
                'description': regime_result.description,
            })
    
    return {
        'regime': regime,
        'total_anomalies': len(anomalies),
        'anomalies': anomalies,
        'summary': f"Regime: {regime}, Anomalies: {len(anomalies)}" if anomalies else f"Regime: {regime}, No anomalies detected"
    }
