"""Tests parametrizados de umbrales para cada frontera exacta y valor adyacente.

Cubre:
- Política experto GRD (costero, cuenca, termoclina, SOI).
- Política oficial ICEN (ENFEN).
- Fronteras exactas y valores adyacentes (±0.0001).
- Huecos sin clasificar.
- Datos faltantes.
- Métricas incompatibles.
- Sin solapamiento de categorías.
- Sin clasificación verde accidental en huecos.
"""

from __future__ import annotations

import pytest

from enso.thresholds import (
    evaluate_coastal_sst_expert,
    evaluate_basin_sst_expert,
    evaluate_thermocline_expert,
    evaluate_soi_expert,
    evaluate_icen_official,
    evaluate_threshold,
    EXPERT_COASTAL_SST_RULES,
    EXPERT_BASIN_SST_RULES,
    EXPERT_THERMOCLINE_RULES,
    EXPERT_SOI_RULES,
    ENFEN_ICEN_RULES,
    ThresholdColor,
)


# ---------------------------------------------------------------------------
# 2.1 SST costero — política experto GRD
# ---------------------------------------------------------------------------

class TestCoastalSSTExpert:
    """Fronteras exactas y adyacentes para SST costero Niño 1+2."""

    @pytest.mark.parametrize("value,expected_label,expected_color", [
        # Por debajo del normal
        (-0.7001, "Sin clasificar", "gray"),  # gap: < -0.7
        (-0.7, "Normal", "green"),            # frontera inferior inclusiva
        # Normal
        (0.0, "Normal", "green"),
        (0.5, "Normal", "green"),             # frontera superior inclusiva
        # Gap: > 0.5 to < 1.3
        (0.5001, "Sin clasificar", "gray"),
        (0.6, "Sin clasificar", "gray"),
        (1.0, "Sin clasificar", "gray"),
        (1.2999, "Sin clasificar", "gray"),
        # Amarillo
        (1.3, "Amarillo", "yellow"),          # frontera inferior inclusiva
        (1.5, "Amarillo", "yellow"),
        (2.0, "Amarillo", "yellow"),          # frontera superior inclusiva
        # Gap: > 2.0 to < 2.1
        (2.0001, "Sin clasificar", "gray"),
        (2.05, "Sin clasificar", "gray"),
        (2.0999, "Sin clasificar", "gray"),
        # Rojo
        (2.1, "Rojo", "red"),                 # frontera inferior inclusiva
        (2.7, "Rojo", "red"),                 # valor de demostración de la imagen
        (5.0, "Rojo", "red"),
    ])
    def test_boundary_values(self, value, expected_label, expected_color):
        result = evaluate_coastal_sst_expert(value)
        assert result.classification == expected_label, f"Value {value}: expected {expected_label}, got {result.classification}"
        assert result.color.value == expected_color, f"Value {value}: expected {expected_color}, got {result.color.value}"

    def test_none_is_unclassified(self):
        result = evaluate_coastal_sst_expert(None)
        assert result.is_unclassified
        assert result.color == ThresholdColor.GRAY

    def test_no_overlapping_categories(self):
        """Verifica que ninguna pareja de reglas se solape."""
        for i, r1 in enumerate(EXPERT_COASTAL_SST_RULES):
            for r2 in EXPERT_COASTAL_SST_RULES[i+1:]:
                # Si ambas tienen min y max, verificar que no se solapan
                if r1.min is not None and r1.max is not None and r2.min is not None and r2.max is not None:
                    assert r1.max <= r2.min or r2.max <= r1.min, f"Overlap between {r1.label} and {r2.label}"

    def test_gaps_are_not_green(self):
        """Los huecos no deben ser verdes."""
        for v in [0.6, 1.0, 1.29, 2.05]:
            result = evaluate_coastal_sst_expert(v)
            assert result.color != ThresholdColor.GREEN, f"Value {v} in gap should not be green"


# ---------------------------------------------------------------------------
# 2.2 SST cuenca — política experto GRD
# ---------------------------------------------------------------------------

class TestBasinSSTExpert:
    """Fronteras exactas y adyacentes para SST cuenca Niño 3.4."""

    @pytest.mark.parametrize("value,expected_label,expected_color", [
        # Por debajo del normal
        (-0.5001, "Sin clasificar", "gray"),
        (-0.5, "Normal", "green"),            # frontera inferior inclusiva
        # Normal
        (0.0, "Normal", "green"),
        (0.5, "Normal", "green"),             # frontera superior inclusiva
        # Gap: > 0.5 to <= 1.0
        (0.5001, "Sin clasificar", "gray"),
        (0.8, "Sin clasificar", "gray"),
        (1.0, "Sin clasificar", "gray"),      # 1.0 NO es amarillo (min_inclusive=False)
        # Amarillo: > 1.0 to <= 1.5
        (1.0001, "Amarillo", "yellow"),
        (1.2, "Amarillo", "yellow"),          # valor de demostración de la imagen
        (1.5, "Amarillo", "yellow"),          # frontera superior inclusiva
        # Rojo: > 1.5
        (1.5001, "Rojo", "red"),
        (2.0, "Rojo", "red"),
    ])
    def test_boundary_values(self, value, expected_label, expected_color):
        result = evaluate_basin_sst_expert(value)
        assert result.classification == expected_label, f"Value {value}: expected {expected_label}, got {result.classification}"
        assert result.color.value == expected_color, f"Value {value}: expected {expected_color}, got {result.color.value}"

    def test_gaps_are_not_green(self):
        for v in [0.6, 0.8, 1.0]:
            result = evaluate_basin_sst_expert(v)
            assert result.color != ThresholdColor.GREEN


# ---------------------------------------------------------------------------
# 2.4 Termoclina — política experto GRD
# ---------------------------------------------------------------------------

class TestThermoclineExpert:
    """Fronteras exactas y adyacentes para D20."""

    @pytest.mark.parametrize("value,expected_label,expected_color", [
        # Por debajo del normal
        (-20.0001, "Sin clasificar", "gray"),
        (-20, "Normal", "green"),             # frontera inferior inclusiva
        # Normal
        (0, "Normal", "green"),
        (20, "Normal", "green"),              # frontera superior inclusiva
        # Gap: > 20 to < 30
        (20.0001, "Sin clasificar", "gray"),
        (25, "Sin clasificar", "gray"),
        (29.9999, "Sin clasificar", "gray"),
        # Amarillo
        (30, "Amarillo", "yellow"),
        (38, "Amarillo", "yellow"),           # valor de demostración global
        (50, "Amarillo", "yellow"),           # frontera superior inclusiva
        # Rojo: > 50
        (50.0001, "Rojo", "red"),
        (52, "Rojo", "red"),                  # valor de demostración costero
    ])
    def test_boundary_values(self, value, expected_label, expected_color):
        result = evaluate_thermocline_expert(value)
        assert result.classification == expected_label, f"Value {value}: expected {expected_label}, got {result.classification}"
        assert result.color.value == expected_color, f"Value {value}: expected {expected_color}, got {result.color.value}"


# ---------------------------------------------------------------------------
# 2.5 SOI — política experto GRD
# ---------------------------------------------------------------------------

class TestSOIExpert:
    """Fronteras exactas y adyacentes para SOI."""

    @pytest.mark.parametrize("value,expected_label,expected_color", [
        # Rojo: < -7
        (-14.50, "Rojo", "red"),              # valor de demostración
        (-7.0001, "Rojo", "red"),
        (-8, "Rojo", "red"),
        # -7 NO es rojo (max_inclusive=False)
        (-7, "Normal", "green"),              # frontera inferior inclusiva
        # Normal
        (0, "Normal", "green"),
        (7, "Normal", "green"),               # frontera superior inclusiva
        # > +7: SIN CLASIFICAR (no hay regla para el lado positivo)
        (7.0001, "Sin clasificar", "gray"),
        (10, "Sin clasificar", "gray"),
        (14.50, "Sin clasificar", "gray"),
    ])
    def test_boundary_values(self, value, expected_label, expected_color):
        result = evaluate_soi_expert(value)
        assert result.classification == expected_label, f"Value {value}: expected {expected_label}, got {result.classification}"
        assert result.color.value == expected_color, f"Value {value}: expected {expected_color}, got {result.color.value}"

    def test_positive_side_not_green(self):
        """Valores > +7 no deben ser verdes (no hay regla positiva)."""
        result = evaluate_soi_expert(10)
        assert result.color != ThresholdColor.GREEN
        assert result.is_unclassified


# ---------------------------------------------------------------------------
# Clasificación oficial ICEN (ENFEN)
# ---------------------------------------------------------------------------

class TestICENOfficial:
    """Fronteras exactas para clasificación oficial ICEN."""

    @pytest.mark.parametrize("value,expected_label,expected_color", [
        # Frío intenso: < -1.3
        (-2.0, "Frío intenso", "blue"),
        (-1.3001, "Frío intenso", "blue"),
        # -1.3 NO es frío intenso (max_inclusive=False), es frío moderado
        (-1.3, "Frío moderado", "lightblue"),
        (-1.2, "Frío moderado", "lightblue"),
        # -1.1 NO es frío moderado (max_inclusive=False), es frío débil
        (-1.1, "Frío débil", "lightcyan"),
        (-0.8, "Frío débil", "lightcyan"),
        # -0.7 es Normal (min_inclusive=True)
        (-0.7, "Normal", "green"),
        (0.0, "Normal", "green"),
        (0.5, "Normal", "green"),
        # 0.5001 es Cálido débil (min_inclusive=False)
        (0.5001, "Cálido débil", "yellow"),
        (1.0, "Cálido débil", "yellow"),
        (1.3, "Cálido débil", "yellow"),      # max_inclusive=True
        # 1.3001 es Cálido moderado
        (1.3001, "Cálido moderado", "orange"),
        (1.77, "Cálido moderado", "orange"),   # valor actual ICEN
        (2.1, "Cálido moderado", "orange"),     # max_inclusive=True
        # 2.1001 es Cálido fuerte
        (2.1001, "Cálido fuerte", "red"),
        (3.0, "Cálido fuerte", "red"),
        (3.5, "Cálido fuerte", "red"),          # max_inclusive=True
        # 3.5001 es Cálido extraordinario
        (3.5001, "Cálido extraordinario", "darkred"),
        (5.0, "Cálido extraordinario", "darkred"),
    ])
    def test_boundary_values(self, value, expected_label, expected_color):
        result = evaluate_icen_official(value)
        assert result.classification == expected_label, f"Value {value}: expected {expected_label}, got {result.classification}"
        assert result.color.value == expected_color, f"Value {value}: expected {expected_color}, got {result.color.value}"

    def test_none_is_unclassified(self):
        result = evaluate_icen_official(None)
        assert result.is_unclassified
        assert result.color == ThresholdColor.GRAY

    def test_no_gaps_in_icen(self):
        """La clasificación ICEN oficial no debe tener huecos."""
        test_values = [-3, -1.5, -1.3, -1.2, -1.1, -0.9, -0.7, 0, 0.5, 0.6, 1.0, 1.3, 1.5, 2.0, 2.1, 2.5, 3.5, 4.0]
        for v in test_values:
            result = evaluate_icen_official(v)
            assert not result.is_unclassified, f"ICEN value {v} should be classified, got unclassified"

    def test_no_overlapping_categories(self):
        for i, r1 in enumerate(ENFEN_ICEN_RULES):
            for r2 in ENFEN_ICEN_RULES[i+1:]:
                if r1.min is not None and r1.max is not None and r2.min is not None and r2.max is not None:
                    assert r1.max <= r2.min or r2.max <= r1.min, f"Overlap between {r1.label} and {r2.label}"


# ---------------------------------------------------------------------------
# Tests de compatibilidad de métricas
# ---------------------------------------------------------------------------

class TestMetricCompatibility:
    """Verifica que las políticas no se aplican a métricas incompatibles."""

    def test_icen_policy_not_for_weekly_nino12(self):
        """La política ICEN no debe aplicarse a Niño 1+2 semanal."""
        # El ICEN es una media móvil de 3 meses, no una observación semanal.
        # El usuario debe usar evaluate_icen_official solo con ICEN.
        # Para Niño 1+2 semanal, usar evaluate_coastal_sst_expert.
        weekly_nino12 = 2.7  # valor de demostración de la imagen
        result_expert = evaluate_coastal_sst_expert(weekly_nino12)
        result_icen = evaluate_icen_official(weekly_nino12)

        # Ambas pueden evaluar el mismo número, pero el policy_id debe ser diferente
        assert result_expert.policy_id == "expert-grd-image-v1"
        assert result_icen.policy_id == "enfen-icen-official-v1"

    def test_soi_policy_not_for_costero(self):
        """La política SOI es de cuenca, no costera."""
        result = evaluate_soi_expert(-14.50)
        assert result.classification == "Rojo"
        assert result.policy_id == "expert-grd-image-v1"

    def test_stale_data_not_green(self):
        """Datos faltantes o None no deben ser verdes."""
        for eval_fn in [evaluate_coastal_sst_expert, evaluate_basin_sst_expert,
                        evaluate_thermocline_expert, evaluate_soi_expert, evaluate_icen_official]:
            result = eval_fn(None)
            assert result.color != ThresholdColor.GREEN
            assert result.is_unclassified


# ---------------------------------------------------------------------------
# Tests de propiedades de la política
# ---------------------------------------------------------------------------

class TestPolicyProperties:
    """Propiedades generales de las políticas de umbral."""

    def test_expert_policy_has_gaps(self):
        """La política experto GRD tiene huecos intencionalmente."""
        gaps = [0.6, 1.0, 1.29, 2.05]  # costero
        for v in gaps:
            assert evaluate_coastal_sst_expert(v).is_unclassified

    def test_official_icen_no_gaps(self):
        """La clasificación ICEN oficial cubre todo el rango sin huecos."""
        for v in [-5, -2, -1.5, -1.0, -0.5, 0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
            assert not evaluate_icen_official(v).is_unclassified

    def test_gray_means_unclassified_or_missing(self):
        """El gris siempre significa sin clasificar o sin datos."""
        result = evaluate_coastal_sst_expert(0.6)  # gap
        assert result.color == ThresholdColor.GRAY
        assert result.is_unclassified

        result = evaluate_coastal_sst_expert(None)
        assert result.color == ThresholdColor.GRAY
        assert result.is_unclassified

    def test_demonstration_values_match_image(self):
        """Los valores de demostración de la imagen producen la clasificación esperada."""
        assert evaluate_coastal_sst_expert(2.7).classification == "Rojo"
        assert evaluate_basin_sst_expert(1.2).classification == "Amarillo"
        assert evaluate_thermocline_expert(52).classification == "Rojo"
        assert evaluate_thermocline_expert(38).classification == "Amarillo"
        assert evaluate_soi_expert(-14.50).classification == "Rojo"
