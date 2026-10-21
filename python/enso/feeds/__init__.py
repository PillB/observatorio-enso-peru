"""Parsers tolerantes a cambios de formato para las fuentes del observatorio.

Cada parser:
  * es una función pura (texto → datos), sin red;
  * localiza la información por estructura y nombre (cabeceras, etiquetas)
    en lugar de posiciones fijas, para sobrevivir a cambios menores;
  * valida el resultado (rangos físicos plausibles, meses únicos y
    ordenados) y lanza ``FormatChanged`` si la estructura ya no se reconoce;
  * devuelve una huella estructural (``fingerprint``) que permite detectar
    cambios de formato entre corridas aunque el parseo siga funcionando.

Los parsers se prueban contra respuestas reales capturadas en
``tests/fixtures/sources`` (actuales e históricas del Internet Archive).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional


class FormatChanged(ValueError):
    """La respuesta de la fuente ya no tiene la estructura esperada."""


@dataclass
class Parsed:
    """Resultado de un parser."""

    data: Any
    fingerprint: str
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def fingerprint(*parts: str) -> str:
    """Huella corta y estable de los rasgos estructurales de un documento."""
    h = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return h[:12]


NUM = re.compile(r"-?\d+\.\d+|-?\d+")
FLOAT = re.compile(r"-?\d+\.\d+")

MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
MON3 = {m[:3]: i for m, i in MONTHS_EN.items()}


def period(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def check_series(points: list[dict], *, lo: float, hi: float, name: str,
                 min_points: int = 12) -> list[str]:
    """Valida una serie mensual. Lanza FormatChanged si es inutilizable."""
    if len(points) < min_points:
        raise FormatChanged(f"{name}: solo {len(points)} puntos")
    keys = [p["period"] for p in points]
    if len(set(keys)) != len(keys):
        raise FormatChanged(f"{name}: periodos duplicados")
    if keys != sorted(keys):
        raise FormatChanged(f"{name}: periodos desordenados")
    warnings = []
    bad = [p for p in points if p["value"] is not None and not lo <= p["value"] <= hi]
    if bad:
        if len(bad) > max(3, len(points) // 50):
            raise FormatChanged(f"{name}: {len(bad)} valores fuera de rango [{lo}, {hi}]")
        for p in bad:
            warnings.append(f"{name}: valor implausible descartado {p['period']}={p['value']}")
            p["value"] = None
    return warnings


def trim_missing(points: list[dict]) -> list[dict]:
    """Quita los periodos vacíos al final (meses futuros rellenados con -999)."""
    end = len(points)
    while end and points[end - 1]["value"] is None:
        end -= 1
    return points[:end]


def norm_missing(v: Optional[float], *sentinels: float) -> Optional[float]:
    if v is None:
        return None
    for s in sentinels or (-999.0, -99.9, -99.99, -9999.0):
        if v <= s + 1e-6:
            return None
    return v
