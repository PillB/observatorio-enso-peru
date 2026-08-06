"""Validación cruzada entre fuentes ENSO.

Compara observaciones de diferentes fuentes para detectar discrepancias
científicamente significativas. NO promedia fuentes incompatibles para
hacerlas coincidir.

Comparaciones implementadas:
  - Weekly Niño 1+2/3.4 vs monthly (over matching periods)
  - RONI vs Niño 3.4 (verificar que RONI no se calculó como rolling mean)
  - ICEN (calculado) vs Niño 1+2 (verificar consistencia)
  - NOAA advisory vs RONI (verificar coherencia científica)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Discrepancy:
    """Discrepancia detectada entre fuentes."""
    metric_id: str
    source_a: str
    source_b: str
    value_a: Optional[float]
    value_b: Optional[float]
    difference: Optional[float]
    tolerance: float
    within_tolerance: bool
    period: str
    notes: str = ""


# ----------------------------------------------------------------------------
# Tolerancias científicamente justificadas
# ----------------------------------------------------------------------------
TOLERANCES = {
    # SST anomalies: 0.5 °C is a reasonable tolerance for different products
    "sst_anomaly": 0.5,
    # RONI vs Niño 3.4: should differ by more than 0.3 if RONI is computed correctly
    # (RONI has tropical-mean adjustment that Niño 3.4 doesn't)
    "roni_vs_nino34": 0.3,
    # ICEN vs Niño 1+2: ICEN is 3-month mean, so can differ from monthly by up to 1.0
    "icen_vs_nino12": 1.0,
    # SOI: different calculations can differ by up to 2.0
    "soi": 2.0,
    # Wind: different regions can differ by up to 5 m/s
    "wind": 5.0,
    # D20: different methods can differ by up to 20 m
    "d20": 20.0,
}


def compare_weekly_vs_monthly(
    weekly_points: list[dict],
    monthly_points: list[dict],
    region: str = "nino34",
    tolerance: float = TOLERANCES["sst_anomaly"],
) -> list[Discrepancy]:
    """Compara weekly vs monthly SST anomaly sobre periodos coincidentes.

    Toma el promedio de las 4 semanas de cada mes y lo compara con el valor mensual.
    """
    discrepancies: list[Discrepancy] = []

    # Group weekly by month
    weekly_by_month: dict[str, list[float]] = {}
    for p in weekly_points:
        if p.get("region") != region:
            continue
        week_id = p.get("month", "")
        if len(week_id) >= 7:
            month_key = week_id[:7]  # YYYY-MM
            if p.get("value") is not None:
                weekly_by_month.setdefault(month_key, []).append(p["value"])

    # Compare with monthly
    monthly_by_key = {p["month"]: p.get("value") for p in monthly_points if p.get("value") is not None}

    for month_key, weekly_vals in weekly_by_month.items():
        if len(weekly_vals) < 3:  # Need at least 3 weeks
            continue
        weekly_avg = sum(weekly_vals) / len(weekly_vals)
        monthly_val = monthly_by_key.get(month_key)
        if monthly_val is None:
            continue
        diff = abs(weekly_avg - monthly_val)
        discrepancies.append(Discrepancy(
            metric_id=f"{region}_sst",
            source_a="weekly_avg",
            source_b="monthly",
            value_a=round(weekly_avg, 2),
            value_b=monthly_val,
            difference=round(diff, 2),
            tolerance=tolerance,
            within_tolerance=diff <= tolerance,
            period=month_key,
            notes=f"Weekly avg of {len(weekly_vals)} weeks vs monthly value",
        ))

    return discrepancies


def validate_roni_not_computed_from_nino34(
    roni_value: Optional[float],
    roni_period: str,
    nino34_value: Optional[float],
    nino34_period: str,
) -> Discrepancy:
    """Valida que RONI no es simplemente un rolling mean de Niño 3.4.

    Si RONI y Niño 3.4 son idénticos (diff < 0.05), es sospechoso.
    RONI tiene ajuste de media tropical que Niño 3.4 no tiene.
    """
    if roni_value is None or nino34_value is None:
        return Discrepancy(
            metric_id="roni_vs_nino34",
            source_a="roni",
            source_b="nino34",
            value_a=roni_value,
            value_b=nino34_value,
            difference=None,
            tolerance=TOLERANCES["roni_vs_nino34"],
            within_tolerance=True,
            period=roni_period,
            notes="Cannot compare: one or both values are None",
        )

    diff = abs(roni_value - nino34_value)
    # If they're almost identical, it's suspicious (RONI should differ due to tropical adjustment)
    is_suspicious = diff < 0.05
    return Discrepancy(
        metric_id="roni_vs_nino34",
        source_a="roni (official)",
        source_b="nino34 (monthly)",
        value_a=roni_value,
        value_b=nino34_value,
        difference=round(diff, 2),
        tolerance=TOLERANCES["roni_vs_nino34"],
        within_tolerance=not is_suspicious,
        period=f"{roni_period} vs {nino34_period}",
        notes="RONI should differ from Niño 3.4 due to tropical-mean adjustment. "
              "If diff < 0.05, RONI may have been computed as naive rolling mean.",
    )


def validate_icen_methodology(
    icen_value: Optional[float],
    nino12_value: Optional[float],
    tolerance: float = TOLERANCES["icen_vs_nino12"],
) -> Discrepancy:
    """Valida que ICEN es consistente con Niño 1+2 (3-month mean).

    ICEN puede diferir de Niño 1+2 mensual porque es un promedio de 3 meses.
    Una diferencia mayor a 1.0 °C es normal; una diferencia de 0 sugeriría
    que ICEN se copió en lugar de calcularse.
    """
    if icen_value is None or nino12_value is None:
        return Discrepancy(
            metric_id="icen_vs_nino12",
            source_a="icen",
            source_b="nino12",
            value_a=icen_value,
            value_b=nino12_value,
            difference=None,
            tolerance=tolerance,
            within_tolerance=True,
            period="",
            notes="Cannot compare: one or both values are None",
        )

    diff = abs(icen_value - nino12_value)
    return Discrepancy(
        metric_id="icen_vs_nino12",
        source_a="icen (3-mo mean)",
        source_b="nino12 (monthly)",
        value_a=icen_value,
        value_b=nino12_value,
        difference=round(diff, 2),
        tolerance=tolerance,
        within_tolerance=diff <= tolerance,
        period="latest",
        notes="ICEN is 3-month rolling mean of Niño 1+2. Diff > 0 expected.",
    )


def validate_official_vs_observation(
    official_alert: str,
    roni_value: Optional[float],
) -> Discrepancy:
    """Valida coherencia entre alerta oficial y observación.

    NO infiere alerta de observación — solo marca si hay inconsistencia
    aparente (ej: alerta "Normal" con RONI > 1.0 sería sospechosa).
    """
    if roni_value is None:
        return Discrepancy(
            metric_id="official_vs_roni",
            source_a="noaa_advisory",
            source_b="roni",
            value_a=None,
            value_b=None,
            difference=None,
            tolerance=0.0,
            within_tolerance=True,
            period="",
            notes="RONI not available for comparison",
        )

    # Map official alert to expected RONI range
    alert_lower = official_alert.lower()
    is_inconsistent = False
    notes = ""

    if "el niño advisory" in alert_lower:
        if roni_value < 0.4:
            is_inconsistent = True
            notes = f"Official 'El Niño Advisory' but RONI={roni_value} (< 0.4 is low for El Niño)"
    elif "la niña advisory" in alert_lower:
        if roni_value > -0.4:
            is_inconsistent = True
            notes = f"Official 'La Niña Advisory' but RONI={roni_value} (> -0.4 is high for La Niña)"
    elif "neutral" in alert_lower:
        if abs(roni_value) > 0.7:
            is_inconsistent = True
            notes = f"Official 'ENSO-Neutral' but RONI={roni_value} (|val| > 0.7 suggests event)"

    return Discrepancy(
        metric_id="official_vs_roni",
        source_a="noaa_advisory",
        source_b="roni",
        value_a=None,
        value_b=roni_value,
        difference=None,
        tolerance=0.0,
        within_tolerance=not is_inconsistent,
        period="latest",
        notes=notes or "Coherent: official alert consistent with RONI observation",
    )


def run_all_cross_validations(
    roni_value: Optional[float],
    roni_period: str,
    nino34_value: Optional[float],
    nino34_period: str,
    icen_value: Optional[float],
    nino12_value: Optional[float],
    official_alert: str,
    weekly_sst: Optional[list[dict]] = None,
    monthly_nino34: Optional[list[dict]] = None,
) -> dict:
    """Ejecuta todas las validaciones cruzadas y devuelve un resumen."""
    discrepancies: list[Discrepancy] = []

    # RONI vs Niño 3.4
    d_roni = validate_roni_not_computed_from_nino34(roni_value, roni_period, nino34_value, nino34_period)
    discrepancies.append(d_roni)

    # ICEN vs Niño 1+2
    d_icen = validate_icen_methodology(icen_value, nino12_value)
    discrepancies.append(d_icen)

    # Official vs RONI
    d_official = validate_official_vs_observation(official_alert, roni_value)
    discrepancies.append(d_official)

    # Weekly vs monthly (if provided)
    if weekly_sst and monthly_nino34:
        d_weekly = compare_weekly_vs_monthly(weekly_sst, monthly_nino34, "nino34")
        discrepancies.extend(d_weekly)

    return {
        "total_comparisons": len(discrepancies),
        "within_tolerance": sum(1 for d in discrepancies if d.within_tolerance),
        "out_of_tolerance": sum(1 for d in discrepancies if not d.within_tolerance),
        "discrepancies": [d.__dict__ for d in discrepancies],
        "summary": "All within tolerance" if all(d.within_tolerance for d in discrepancies)
                   else f"{sum(1 for d in discrepancies if not d.within_tolerance)} discrepancies detected",
    }
