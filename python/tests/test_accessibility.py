"""Contratos de accesibilidad de los gráficos del frontend.

A partir de un manifiesto fixture de IDs de gráficos, verifica que cada
uno declara un ``aria-label`` y ``role='img'``.
"""

from __future__ import annotations

import pytest

# Fixture: manifiesto de gráficos declarados por el frontend.
# (Espejo del contrato que cumplen los componentes en src/components/enso/charts.tsx.)
CHART_MANIFEST = [
    {
        "id": "chart-nino12",
        "role": "img",
        "aria_label": "Serie mensual de anomalía de TSM en Niño 1+2 (costero)",
    },
    {
        "id": "chart-icen",
        "role": "img",
        "aria_label": "Serie del ICEN con umbrales ENFEN",
    },
    {
        "id": "chart-nino34",
        "role": "img",
        "aria_label": "Serie mensual de anomalía de TSM en Niño 3.4 (cuenca)",
    },
    {
        "id": "chart-roni",
        "role": "img",
        "aria_label": "Serie del RONI con umbral operativo ±0.5 °C",
    },
    {
        "id": "chart-soi",
        "role": "img",
        "aria_label": "Serie mensual del SOI (Tahiti − Darwin)",
    },
    {
        "id": "chart-u850",
        "role": "img",
        "aria_label": "Anomalía del viento zonal a 850 hPa",
    },
    {
        "id": "chart-d20",
        "role": "img",
        "aria_label": "Anomalía de la profundidad de la isoterma de 20 °C (D20)",
    },
]


def test_every_chart_has_role_img():
    for c in CHART_MANIFEST:
        assert c["role"] == "img", f"{c['id']}: role != img"


def test_every_chart_has_aria_label():
    for c in CHART_MANIFEST:
        assert c["aria_label"], f"{c['id']}: aria_label vacío"
        assert len(c["aria_label"]) >= 10, f"{c['id']}: aria_label demasiado corto"


def test_aria_label_mentions_indicator_or_concept():
    """Cada aria-label menciona el indicador o concepto relevante."""
    for c in CHART_MANIFEST:
        label = c["aria_label"].lower()
        cid = c["id"].lower()
        # El id o el texto del label menciona al indicador.
        assert any(kw in label or kw in cid for kw in (
            "niño", "nino", "icen", "roni", "soi", "viento", "d20",
            "termoclina", "tsm", "anomalía", "anomalia",
        )), c["id"]


def test_aria_label_distinguishes_coastal_vs_basin():
    """Al menos un gráfico menciona 'costero' y otro 'cuenca'."""
    labels = " ".join(c["aria_label"].lower() for c in CHART_MANIFEST)
    assert "costero" in labels
    assert "cuenca" in labels


def test_no_chart_missing_accessibility_attrs():
    """Ningún gráfico puede omitir role o aria-label."""
    for c in CHART_MANIFEST:
        assert "role" in c, f"{c.get('id')}: sin role"
        assert "aria_label" in c, f"{c.get('id')}: sin aria_label"
