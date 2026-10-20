"""Señal operativa del equipo GRD y categorías científicas.

La señal GRD se calcula SOLO aquí (Python) a partir de la política
transcrita en ``config/threshold-policies/expert-grd-image-v1.yaml``. El
navegador la consume ya calculada; nunca la recalcula.

Los huecos entre intervalos de la política quedan «Sin clasificación en la
política experta» y nunca se pintan como normales. Un dato vencido o
faltante tampoco produce color.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "threshold-policies" / "expert-grd-image-v1.yaml"

LEVEL = {"green": "ok", "yellow": "watch", "red": "alert"}
LABEL = {
    "ok": "Condición dentro del rango operativo normal",
    "watch": "Señal operativa amarilla",
    "alert": "Señal operativa roja",
    "unclassified": "Sin clasificación en la política experta",
    "na": "Dato actual no disponible",
}


def load_policy(path: Path = POLICY_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _in(rule: dict, v: float) -> bool:
    lo, hi = rule.get("min"), rule.get("max")
    if lo is not None and not (v >= lo if rule.get("min_inclusive") else v > lo):
        return False
    if hi is not None and not (v <= hi if rule.get("max_inclusive") else v < hi):
        return False
    return True


def classify(rules: list[dict], v: Optional[float]) -> tuple[str, str]:
    if v is None:
        return "na", LABEL["na"]
    for r in rules:
        if "direction" in r:
            continue
        if _in(r, v):
            lvl = LEVEL[r["color"]]
            return lvl, LABEL[lvl]
    return "unclassified", LABEL["unclassified"]


def _signal(key: str, name: str, region: str, metric: str, value, units: str, period: str,
            source: str, level: str, label: str, basis: str, stale: bool) -> dict:
    if stale and level not in ("na",):
        level, label = "na", LABEL["na"]
    return {
        "id": key, "name": name, "region": region, "metric": metric, "value": value,
        "units": units, "period": period, "source": source, "level": level, "label": label,
        "basis": basis, "stale": stale,
    }


def grd_signals(inputs: dict, policy: Optional[dict] = None) -> dict:
    """Calcula la señal GRD por indicador.

    ``inputs`` trae, para cada clave, ``{value, period, source, stale}``:
      coastal_sst, basin_sst, wind_coastal, wind_global, d20_coastal,
      d20_global, soi_troup.
    """
    p = policy or load_policy()
    out = []

    def add(key, name, region, metric, units, rules, basis):
        x = inputs.get(key) or {}
        lvl, lab = classify(rules, x.get("value"))
        out.append(_signal(key, name, region, metric, x.get("value"), units, x.get("period"),
                           x.get("source"), lvl, lab, basis, bool(x.get("stale"))))

    add("coastal_sst", "Anomalía de TSM", "Niño Costero 1+2", "Anomalía mensual de TSM Niño 1+2", "degC",
        p["coastal_sst"]["rules"], "Normal −0,7 a +0,5 °C; amarillo +1,3 a +2,0 °C; rojo > +2,1 °C")
    add("basin_sst", "Anomalía de TSM", "Niño Global 3.4", "Anomalía mensual de TSM Niño 3.4", "degC",
        p["basin_sst"]["rules"], "Normal −0,5 a +0,5 °C; amarillo > +1,0 a +1,5 °C; rojo > +1,5 °C")

    for key, region in (("wind_coastal", "Niño Costero (Pacífico oriental)"), ("wind_global", "Niño Global (Pacífico central)")):
        x = inputs.get(key) or {}
        v = x.get("value")
        if v is None:
            lvl, lab, direction = "na", LABEL["na"], None
        elif v < 0:
            lvl, lab, direction = "alert", LABEL["alert"], "Oeste a este"
        else:
            lvl, lab, direction = "ok", LABEL["ok"], "Este a oeste"
        sig = _signal(key, "Vientos alisios", region, "Índice de viento alisio a 850 hPa (CPC; positivo = del este)",
                      v, "m/s", x.get("period"), x.get("source"), lvl, lab,
                      "Normal: alisios de este a oeste; rojo: flujo de oeste a este", bool(x.get("stale")))
        sig["direction"] = direction
        out.append(sig)

    add("d20_coastal", "Profundidad de la termoclina (20 °C)", "Niño Costero", "Anomalía de D20", "m",
        p["thermocline"]["rules"], "Normal −20 a +20 m; amarillo 30 a 50 m; rojo > 50 m")
    add("d20_global", "Profundidad de la termoclina (20 °C)", "Niño Global", "Anomalía de D20", "m",
        p["thermocline"]["rules"], "Normal −20 a +20 m; amarillo 30 a 50 m; rojo > 50 m")
    add("soi_troup", "Índice de Oscilación del Sur", "Niño Costero y Niño Global", "SOI escala Troup (×10)", "dimensionless",
        p["soi"]["rules"], "Normal −7 a +7; rojo < −7")

    return {
        "policy_id": p.get("policy_id"), "policy_name": "Señal operativa del equipo GRD",
        "approval_status": p.get("approval_status"), "version": p.get("version"),
        "disclaimer": "Interpretación operativa del observatorio según la tabla del equipo GRD. No equivale al sistema oficial de alertas de ENFEN ni al de NOAA.",
        "signals": out,
    }


# ---------------------------------------------------------------------------
# Categorías científicas publicadas por las instituciones
# ---------------------------------------------------------------------------
# ICEN — magnitudes según la Nota Técnica ENFEN 01-2024 (vigente desde
# diciembre de 2024). Ver docs/metodologia.md para la fuente y la regla de
# persistencia (tres meses consecutivos).
# Intervalos en °C: lado frío cerrado por abajo, lado cálido cerrado por
# arriba, Neutra cerrada en ambos extremos [−0,7; +0,5].
ICEN_CATEGORIES = [
    (lambda v: v < -1.3, "Fría fuerte", "cool"),
    (lambda v: -1.3 <= v < -1.1, "Fría moderada", "cool"),
    (lambda v: -1.1 <= v < -0.7, "Fría débil", "cool"),
    (lambda v: -0.7 <= v <= 0.5, "Neutra", "neutral"),
    (lambda v: 0.5 < v <= 1.3, "Cálida débil", "warm"),
    (lambda v: 1.3 < v <= 2.1, "Cálida moderada", "warm"),
    (lambda v: 2.1 < v <= 3.5, "Cálida fuerte", "warm"),
    (lambda v: v > 3.5, "Cálida extraordinaria", "warm"),
]
ICEN_TABLE = [
    ("Fría fuerte", "< −1,3"), ("Fría moderada", "−1,3 a < −1,1"), ("Fría débil", "−1,1 a < −0,7"),
    ("Neutra", "−0,7 a +0,5"), ("Cálida débil", "> +0,5 a +1,3"), ("Cálida moderada", "> +1,3 a +2,1"),
    ("Cálida fuerte", "> +2,1 a +3,5"), ("Cálida extraordinaria", "> +3,5"),
]


def icen_category(v: Optional[float]) -> Optional[dict]:
    if v is None:
        return None
    for test, label, tone in ICEN_CATEGORIES:
        if test(round(v, 2)):
            return {"label": f"Condición {label.lower()}", "short": label, "tone": tone}
    return None


def oni_category(v: Optional[float]) -> Optional[dict]:
    """Umbral ±0,5 °C de NOAA/CPC con la convención usual de intensidad."""
    if v is None:
        return None
    a = abs(v)
    if a < 0.5:
        return {"label": "Neutral", "tone": "neutral"}
    phase = "El Niño" if v > 0 else "La Niña"
    strength = "débil" if a < 1.0 else "moderado" if a < 1.5 else "fuerte" if a < 2.0 else "muy fuerte"
    if phase == "La Niña":
        strength = {"débil": "débil", "moderado": "moderada", "fuerte": "fuerte", "muy fuerte": "muy fuerte"}[strength]
    return {"label": f"Umbral de {phase} {strength}", "tone": "warm" if v > 0 else "cool"}


def anomaly_tone(v: Optional[float], neutral: float = 0.5) -> str:
    if v is None:
        return "na"
    return "warm" if v >= neutral else "cool" if v <= -neutral else "neutral"
