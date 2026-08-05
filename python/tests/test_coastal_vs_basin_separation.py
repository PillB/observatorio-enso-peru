"""Contratos de separación costero vs cuenca.

- Los indicadores costeros tienen scope='coastal'.
- Los indicadores de cuenca tienen scope='basin'.
- Un indicador no se infiere del otro (no se deriva costero de cuenca ni
  viceversa, salvo ICEN/RONI que son derivaciones explícitas declaradas).
"""

from __future__ import annotations

import pytest

from enso.methodology import INDICATORS, INDICATOR_BY_ID


def test_coastal_indicators_have_coastal_scope():
    for ind_id in ("nino12", "icen"):
        assert INDICATOR_BY_ID[ind_id].scope == "coastal"


def test_basin_indicators_have_basin_scope():
    for ind_id in ("nino34", "roni", "soi", "u850", "d20"):
        assert INDICATOR_BY_ID[ind_id].scope == "basin"


def test_no_indicator_mixed_scope():
    for ind in INDICATORS:
        assert ind.scope in ("coastal", "basin")


def test_coastal_not_inferred_from_basin():
    """ICEN deriva de Niño 1+2 (costero), NO de Niño 3.4 (cuenca)."""
    icen = INDICATOR_BY_ID["icen"]
    n12 = INDICATOR_BY_ID["nino12"]
    n34 = INDICATOR_BY_ID["nino34"]
    assert icen.scope == "coastal"
    assert n12.scope == "coastal"
    assert n34.scope == "basin"
    # El ICEN se alimenta de TSM Niño 1+2 (documentado).
    assert "Niño 1+2" in icen.variable or "Niño 1+2" in icen.notes


def test_roni_derives_from_nino34_not_from_nino12():
    roni = INDICATOR_BY_ID["roni"]
    n12 = INDICATOR_BY_ID["nino12"]
    assert roni.scope == "basin"
    assert n12.scope == "coastal"
    assert "Niño 3.4" in roni.variable or "Niño 3.4" in roni.notes


def test_region_bounds_differ_coastal_vs_basin():
    n12 = INDICATOR_BY_ID["nino12"]
    n34 = INDICATOR_BY_ID["nino34"]
    # Niño 1+2 y Niño 3.4 son regiones geográficas distintas.
    assert (n12.regionBounds.latMin, n12.regionBounds.lonMin) != \
           (n34.regionBounds.latMin, n34.regionBounds.lonMin)


def test_coastal_alert_separate_from_basin_alert():
    """El estado consolidado mantiene dos alertas independientes."""
    from enso.pipeline import Pipeline
    import json
    import os
    pipe = Pipeline(out_dir="python/out", cache_dir="python/cache",
                    allow_network=False)
    # No requiere datos reales: sólo valida la estructura del status.json.
    # Si la corrida no pudo ejecarse antes, force-escribimos status mínimo.
    pipe.run()
    with open("python/out/status.json", "r", encoding="utf-8") as fh:
        status = json.load(fh)
    assert "coastal" in status
    assert "basin" in status
    assert status["coastal"]["alert"] != status["basin"]["alert"] or \
           status["coastal"]["alertSource"] != status["basin"]["alertSource"]
