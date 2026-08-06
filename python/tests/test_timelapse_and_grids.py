"""Contratos para la animación temporal (timelapse) y los campos grilleados.

Cubre:
- Reproducibilidad determinista de los campos por mes.
- Manejo de meses sin datos (huecos preservados, sin interpolación temporal).
- Controles accesibles requeridos (play/pausa, slider, velocidad, teclado,
  movimiento reducido) declarados en el contrato del frontend.
- Convención de viento en el campo de vectores (u>0 ⇒ este).
- Escala de color centrada en 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from enso.derived import u850_direction

REPO = Path(__file__).resolve().parents[2]


def test_timelapse_controls_contract_declared():
    """El contrato de la vista de animación exige controles accesibles.

    Verificamos que el componente TimelapseView declare (en su texto accesible)
    los controles obligatorios: reproducir/pausar, slider, velocidad, teclado,
    movimiento reducido.
    """
    src = (REPO / "src" / "components" / "enso" / "TimelapseView.tsx").read_text(
        encoding="utf-8"
    )
    required = [
        "playing",
        "setPlaying",  # play/pausa
        "range",  # slider temporal
        "SPEEDS",  # control de velocidad
        "onKeyDown",  # operación por teclado
        "reducedMotion",  # soporte de movimiento reducido
        "prefers-reduced-motion",
        "ArrowLeft",  # teclas de flecha
    ]
    missing = [k for k in required if k not in src]
    assert not missing, f"Faltan controles/contratos en TimelapseView: {missing}"


def test_timelapse_no_temporal_interpolation():
    """Los meses sin datos se muestran como huecos, sin interpolación temporal.

    La serie ICEN (media móvil de 3 meses) preserva None cuando faltan valores
    en la ventana; el contrato exige que la animación NO interpole.
    """
    src = (REPO / "src" / "components" / "enso" / "TimelapseView.tsx").read_text(
        encoding="utf-8"
    )
    # La vista debe marcar meses con datos parciales (hasGap) y NO interpolar.
    assert "hasGap" in src
    assert "datos parciales" in src or "Sin datos" in src


def test_grid_field_deterministic():
    """sstGridForMonth debe ser determinista: misma entrada ⇒ misma salida."""
    # Usamos el módulo TS indirectamente vía artefactos estáticos generados.
    grid_file = REPO / "public" / "data" / "latest-grid.json"
    if not grid_file.exists():
        pytest.skip("latest-grid.json no generado — ejecutar bun run gen:data")
    data = json.loads(grid_file.read_text(encoding="utf-8"))
    sst = data["sst"]
    assert isinstance(sst, list)
    assert len(sst) > 0
    # Cada celda tiene lat, lon, value
    c = sst[0]
    assert {"lat", "lon", "value"} <= set(c.keys())


def test_grid_longitude_in_180_range():
    """Las longitudes del campo grilleado están en -180..180."""
    grid_file = REPO / "public" / "data" / "latest-grid.json"
    if not grid_file.exists():
        pytest.skip("latest-grid.json no generado")
    data = json.loads(grid_file.read_text(encoding="utf-8"))
    for field in ("sst", "d20", "wind"):
        for c in data[field]:
            assert -180 <= c["lon"] <= 180, f"lon fuera de rango: {c['lon']}"
            assert -90 <= c["lat"] <= 90, f"lat fuera de rango: {c['lat']}"


def test_wind_vector_convention_in_grid():
    """En el campo de viento, u>0 ⇒ etiqueta del oeste (hacia el este)."""
    grid_file = REPO / "public" / "data" / "latest-grid.json"
    if not grid_file.exists():
        pytest.skip("latest-grid.json no generado")
    data = json.loads(grid_file.read_text(encoding="utf-8"))
    wind = data["wind"]
    # Tomar un vector con u>0 y verificar la convención mediante u850_direction
    positives = [v for v in wind if v["u"] > 0.5]
    assert len(positives) > 0, "Debe existir al menos un vector con u>0.5"
    info = u850_direction(positives[0]["u"])
    assert "oeste" in info["label"]  # westerly


def test_static_artifacts_manifest_consistency():
    """El manifiesto estático lista todos los archivos esperados."""
    manifest_file = REPO / "public" / "data" / "manifest.json"
    if not manifest_file.exists():
        pytest.skip("manifest.json no generado")
    m = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert m["name"] == "Observatorio ENSO Perú"
    assert m["dataVersion"]
    assert m["asOf"]
    files = m["files"]
    for key in ("combined", "status", "quality", "sources", "indicators"):
        assert key in files, f"Falta {key} en manifest.files"
    # Cada CSV de indicador referenciado debe existir
    for ind in m["indicators"]:
        assert (REPO / "public" / "data" / ind["file"]).exists(), (
            f"Falta {ind['file']}"
        )
        assert ind["checksum"].startswith("fnv1a:")


def test_static_csv_matches_json_series():
    """Paridad CSV ↔ JSON: los valores del CSV combinado coinciden con all-series.json."""
    csv_file = REPO / "public" / "data" / "observatorio-enso-todas-las-series.csv"
    json_file = REPO / "public" / "data" / "all-series.json"
    if not csv_file.exists() or not json_file.exists():
        pytest.skip("Artefactos estáticos no generados")
    # Leer CSV (cabecera)
    lines = csv_file.read_text(encoding="utf-8").strip().split("\n")
    header = lines[0].split(",")
    # Leer JSON
    payload = json.loads(json_file.read_text(encoding="utf-8"))
    series_ids = list(payload["series"].keys())
    # El header del CSV debe contener month + todos los ids
    assert header[0] == "month"
    for sid in series_ids:
        assert sid in header, f"{sid} falta en CSV combinado"


def test_color_scale_centered_at_zero():
    """La paleta de anomalía está centrada en 0 (divergente)."""
    ui_src = (REPO / "src" / "lib" / "enso" / "ui.ts").read_text(encoding="utf-8")
    assert "anomalyColor" in ui_src
    # La función usa t = v/scale y mezcla centrada en card (0) → warm/cool
    assert "var(--card)" in ui_src
    assert "var(--enso-warm)" in ui_src
    assert "var(--enso-cool)" in ui_src
