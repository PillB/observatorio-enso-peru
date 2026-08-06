"""Contratos para pronósticos ENSO e impacto regional.

Cubre:
- El pronóstico es interpretación del observatorio (no oficial).
- Las probabilidades categorizadas suman ~100%.
- El ensamble tiene el número esperado de miembros.
- El impacto regional cubre los departamentos costeros del Perú.
- Los niveles de riesgo están en 1..4.
- La influencia es mayor en el norte (Tumbes/Piura) que en el sur (Tacna).
- Las notas no afirman ser alertas oficiales.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_forecasts_artifact_exists():
    """El artefacto forecasts.json debe existir tras gen:data."""
    f = REPO / "public" / "data" / "forecasts.json"
    if not f.exists():
        pytest.skip("forecasts.json no generado — ejecutar bun run gen:data")
    data = json.loads(f.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 12  # 12 trimestres


def test_forecast_probabilities_sum_to_100():
    """Las probabilidades El Niño + Neutral + La Niña ≈ 100%."""
    f = REPO / "public" / "data" / "forecasts.json"
    if not f.exists():
        pytest.skip("forecasts.json no generado")
    data = json.loads(f.read_text(encoding="utf-8"))
    for season in data:
        total = season["probNino"] + season["probNeutral"] + season["probNina"]
        assert 99 <= total <= 101, f"Probabilidades no suman 100%: {total}"


def test_forecast_plume_has_members():
    """Cada trimestre debe tener un ensamble de 9 trayectorias."""
    f = REPO / "public" / "data" / "forecasts.json"
    if not f.exists():
        pytest.skip("forecasts.json no generado")
    data = json.loads(f.read_text(encoding="utf-8"))
    for season in data:
        assert len(season["plume"]) == 9, f"Ensamble debe tener 9 miembros"


def test_forecast_labeled_as_observatory_interpretation():
    """La vista de pronóstico debe declarar que es interpretación del observatorio."""
    src = (REPO / "src" / "components" / "enso" / "ForecastsView.tsx").read_text(encoding="utf-8")
    assert "interpretación generada por el observatorio" in src.lower() or "observatorio" in src.lower()
    assert "no sustituyen los pronósticos oficiales" in src.lower() or "no sustituy" in src.lower()


def test_regional_impact_covers_coastal_departments():
    """El impacto regional debe cubrir los departamentos costeros del Perú."""
    f = REPO / "public" / "data" / "regional-impact.json"
    if not f.exists():
        pytest.skip("regional-impact.json no generado")
    data = json.loads(f.read_text(encoding="utf-8"))
    names = [d["name"] for d in data]
    required = ["Tumbes", "Piura", "Lambayeque", "Lima", "Tacna"]
    for name in required:
        assert name in names, f"Falta departamento costero: {name}"


def test_regional_risk_levels_in_range():
    """Los niveles de riesgo deben estar en 1..4."""
    f = REPO / "public" / "data" / "regional-impact.json"
    if not f.exists():
        pytest.skip("regional-impact.json no generado")
    data = json.loads(f.read_text(encoding="utf-8"))
    for d in data:
        assert 1 <= d["riskLevel"] <= 4, f"Riesgo fuera de rango: {d['riskLevel']}"
        assert d["riskLabel"] in ("Bajo", "Moderado", "Alto", "Muy alto")


def test_regional_north_higher_risk_than_south():
    """Durante El Niño Costero, el norte (Tumbes) tiene riesgo >= sur (Tacna)."""
    f = REPO / "public" / "data" / "regional-impact.json"
    if not f.exists():
        pytest.skip("regional-impact.json no generado")
    data = json.loads(f.read_text(encoding="utf-8"))
    by_name = {d["name"]: d for d in data}
    tumbes = by_name.get("Tumbes", {})
    tacna = by_name.get("Tacna", {})
    if tumbes and tacna:
        assert tumbes["riskLevel"] >= tacna["riskLevel"], (
            "El norte debe tener riesgo >= al sur durante El Niño Costero"
        )


def test_regional_not_official_alert():
    """La vista regional no debe afirmar ser alerta oficial."""
    src = (REPO / "src" / "components" / "enso" / "RegionalView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "no es un pronóstico oficial" in src_lower or "no es una alerta" in src_lower
    assert "indeci" in src_lower and "cenepred" in src_lower and "senamhi" in src_lower


def test_dark_mode_toggle_exists():
    """El toggle de tema claro/oscuro debe existir."""
    src = (REPO / "src" / "components" / "enso" / "ThemeToggle.tsx").read_text(encoding="utf-8")
    assert "useTheme" in src
    assert "next-themes" in src
    assert "Cambiar a modo oscuro" in src
    assert "Cambiar a modo claro" in src
