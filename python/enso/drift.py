"""Guardia de regresión: compara lo que se acaba de leer de una fuente con lo publicado la vez anterior.

Los lectores (``enso.feeds``) validan la forma de cada respuesta (cabeceras, rangos físicos, meses ordenados), pero una
respuesta puede tener la forma correcta y aun así ser peor que la de ayer sin que nada falle:

* **Historia recortada** (``series-shrunk``): la fuente sirve un archivo truncado o el lector deja de leer un bloque y
  la serie pierde puntos. ``check_series`` solo exige 12.
* **Último periodo hacia atrás** (``series-regressed``): un espejo, una caché o una copia vieja de un recolector trae
  un archivo anterior. El dato saldría marcado con su edad real, pero el sitio «retrocedería» sin explicación.
* **Historia reescrita** (``history-rewritten``): una columna corrida o una base climática nueva cambia valores de
  hace años. Las fuentes revisan los últimos meses (ONI, ERSST, GODAS), no la historia antigua.
* **Serie que desaparece** (``series-missing``): una región o bloque que ayer estaba y hoy no.

Todas son advertencias: se publican en el registro de la corrida y abren un issue (``tools.sync_issues``). La
función es pura (datos → incidencias), sin red, y la prueban ``tests/test_drift.py`` y las copias reales de
``tests/fixtures/sources/history``.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

#: Puntos que una serie puede perder sin aviso (la fuente reacomoda el final: meses provisionales que se quitan).
SHRINK_TOLERANCE = 2
#: Los últimos meses se revisan con normalidad (ONI y RONI 2–3 estaciones, ERSST unos meses, GODAS hasta un año).
RECENT_POINTS = 24
#: Cambio que cuenta como reescritura en un punto antiguo, en las unidades de la serie, y fracción de puntos
#: antiguos que tienen que cambiar para avisar (un valor corregido suelto no es un cambio de formato).
REWRITE_DELTA = 0.25
REWRITE_FRACTION = 0.02
REWRITE_MIN_POINTS = 3


def _key(p: dict) -> Optional[str]:
    k = p.get("period") or p.get("date")
    return k if isinstance(k, str) else None


def _value(p: dict) -> Optional[float]:
    for name in ("value", "anom"):
        v = p.get(name)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def series(data: Any, path: str = "") -> Iterator[tuple[str, list[dict]]]:
    """Las series de una fuente: cada lista de puntos con ``period`` o ``date`` (y ``value`` o ``anom``), con su ruta
    dentro de ``data`` (``anom.nino12``, ``original``…). Lo demás (textos, listados de documentos) se ignora."""
    if isinstance(data, list):
        # Un punto suelto sin periodo (un lector con un error) no convierte la serie en «desaparecida»: basta con
        # que la mayoría tenga periodo; los que no lo tienen no se comparan.
        keyed = [p for p in data if isinstance(p, dict) and _key(p)]
        if data and len(keyed) * 2 > len(data) and any(_value(p) is not None for p in keyed):
            yield path or "$", keyed
        return
    if isinstance(data, dict):
        for k, v in data.items():
            yield from series(v, f"{path}.{k}" if path else str(k))


def compare(previous: Any, current: Any, source: str = "") -> list[tuple[str, str]]:
    """(código, mensaje) por cada regresión de ``current`` frente a ``previous`` (los ``data`` de las dos lecturas)."""
    old = dict(series(previous))
    new = dict(series(current))
    out: list[tuple[str, str]] = []
    label = f"{source}: " if source else ""
    for name, before in old.items():
        after = new.get(name)
        if after is None:
            out.append(("series-missing", f"{label}la serie «{name}» ({len(before)} puntos) ya no aparece en la respuesta."))
            continue
        if len(after) < len(before) - SHRINK_TOLERANCE:
            out.append(("series-shrunk", f"{label}la serie «{name}» pasó de {len(before)} a {len(after)} puntos: la "
                                         "respuesta viene recortada o el lector dejó de leer una parte."))
        last_before = max((_key(p) for p in before if _value(p) is not None), default=None)
        last_after = max((_key(p) for p in after if _value(p) is not None), default=None)
        if last_before and last_after and last_after < last_before:
            out.append(("series-regressed", f"{label}el último dato de «{name}» retrocedió de {last_before} a "
                                            f"{last_after}: la respuesta es más vieja que la publicada (espejo, caché "
                                            "o copia atrasada)."))
        prev_vals = {_key(p): _value(p) for p in before}
        keys = sorted(k for k in prev_vals if k)
        cutoff = keys[-RECENT_POINTS] if len(keys) > RECENT_POINTS else None
        if cutoff is None:
            continue
        old_pts = changed = 0
        worst = None
        for p in after:
            k, v = _key(p), _value(p)
            if k is None or k >= cutoff or k not in prev_vals:
                continue
            pv = prev_vals[k]
            if pv is None or v is None:
                continue
            old_pts += 1
            d = round(abs(v - pv), 6)  # 0,25 exacto no cuenta (sin el redondeo, 2,61−2,36 da 0,2500000001)
            if d > REWRITE_DELTA:
                changed += 1
                if worst is None or d > worst[2]:
                    worst = (k, pv, d, v)
        if old_pts and changed >= REWRITE_MIN_POINTS and changed / old_pts > REWRITE_FRACTION:
            k, pv, _, v = worst
            out.append(("history-rewritten", f"{label}{changed} de {old_pts} valores antiguos de «{name}» cambiaron más "
                                             f"de {REWRITE_DELTA} (el mayor: {k}, {pv:+.2f} → {v:+.2f}): columna corrida, "
                                             "otra base climática u otra variable. Revisar antes de confiar en la serie."))
    return out
