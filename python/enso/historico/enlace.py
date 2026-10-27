"""Une las fuentes que cuentan el mismo evento y mide qué se sabía antes de cada uno.

**Corroboración** (``link``). Un reporte del COEN o una nota de prensa casi siempre cuentan una emergencia que el
SINPAD o DesInventar ya registran. Para no contarla dos veces, cada candidato (``cosecha``) busca una fila del
mismo lugar, del mismo grupo de peligro (o lluvias con lo que las lluvias causan) y de fechas compatibles:

* COEN con código SINPAD: la emergencia del SINPAD con ese código.
* COEN con fecha de ocurrencia (del PDF): ±3 días; con la fecha del primer reporte: del evento hasta 10 días
  antes. Si no hay, una emergencia del SINPAD del mismo distrito y grupo hasta 30 días alrededor.
* Prensa con fecha de publicación: un evento de hasta 10 días antes (o del día siguiente); si la nota cita la fecha
  del evento, de 3 días antes de esa fecha hasta el día siguiente a la publicación; con solo el mes, del mismo mes
  o del anterior. Una nota de provincia corrobora cualquier distrito de esa provincia.
* Periódicos antiguos (hemeroteca): un evento de hasta 45 días antes de la publicación (un cable o la carta de un
  cónsul tardaban semanas y los semanarios los reproducían después), o una fila de ese mes o ese año que solo
  tiene el mes o el año (archivos curados). Una página de departamento corrobora cualquier lugar del departamento.
* Otras fuentes con fecha propia (desbordes de lagunas glaciares): ±3 días con el día; el mismo mes con solo el
  mes; con solo el año no se unen.

Si encuentra la fila, le suma su enlace (``FuentesAdicionales``), su origen (``OrigenesCorroboran``) y uno a
``Corroboracion``; las cifras de daños del COEN pasan a la fila solo si la fila no trae ninguna. Si no, el
candidato queda como fila propia (un evento que la otra fuente no registró: el COEN marca algunos como «no
registrada en el SINPAD»), y las notas siguientes del mismo evento se suman a él.

**Prevención** (``prevention``). Para cada distrito: las declaratorias de emergencia por peligro inminente
(prevención) y por impacto (respuesta), las evaluaciones técnicas del peligro (INGEMMET, IGP), los puntos del
inventario de peligros del INGEMMET con su fecha, y los eventos oficiales que ocurrieron *después* de que el
peligro del mismo grupo estaba inventariado, evaluado o declarado inminente. Una declaratoria de toda una
provincia o un departamento cuenta para cada uno de sus distritos. Por país, los llamamientos de la Cruz Roja
(IFRC). Es la evidencia para la pregunta del experto: si el Perú supo del peligro y aun así el daño se repitió.
"""

from __future__ import annotations

import bisect
from collections import Counter, defaultdict
from datetime import date
from typing import Iterable, Optional

from . import esquema as E

#: Cuántos enlaces adicionales se guardan por fila (el conteo, ``Corroboracion``, los cuenta todos).
MAX_LINKS = 10
#: Grupos de peligro que las lluvias causan (una nota de «lluvias» corrobora un huaico y al revés).
RAIN_GROUPS = {"hidrometeorologico", "geologico-hidro"}
#: Hasta cuántos días antes de su publicación puede haber ocurrido lo que cuenta una página de periódico antiguo.
ARCHIVE_DAYS = 45


def _ord(day: str) -> int:
    return date.fromisoformat(day[:10]).toordinal()


def compatible(a: str, b: str) -> bool:
    """Si dos DangerType pueden ser el mismo evento."""
    ga, gb = E.danger_group(a), E.danger_group(b)
    if ga == gb:
        return True
    return ("Lluvias intensas" in (a, b)) and ga in RAIN_GROUPS and gb in RAIN_GROUPS


class _Index:
    """Filas por lugar (distrito, provincia y departamento), ordenadas por fecha."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.by: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.sinpad: dict[str, int] = {}
        for i, r in enumerate(rows):
            self.add(i, r, sort=False)
        for v in self.by.values():
            v.sort()

    def add(self, i: int, r: dict, sort: bool = True) -> None:
        code, d = r["Ubigeo"], _ord(r["Date"])
        keys = [code] + ([code[:4]] if len(code) == 6 else []) + ([code[:2]] if len(code) > 2 else [])
        for k in keys:
            if sort:
                bisect.insort(self.by[k], (d, i))
            else:
                self.by[k].append((d, i))
        if r["Origen"] == "sinpad" and r.get("IdFuente"):
            self.sinpad.setdefault(str(r["IdFuente"]), i)

    def find(self, code: str, lo: int, hi: int, danger: str, center: int,
             origins: Optional[set] = None, precisions: Optional[set] = None, whole: bool = False) -> Optional[int]:
        """La fila de ``code`` (distrito, o cualquier distrito si ``code`` es una provincia, o con ``whole`` cualquier
        lugar si es un departamento) con fecha en [lo, hi] y peligro compatible más cercana a ``center`` (y del mismo
        DangerType si hay empate)."""
        best = None
        rows = self.by.get(code, [])
        for d, i in rows[bisect.bisect_left(rows, (lo, -1)):bisect.bisect_right(rows, (hi, len(self.rows)))]:
            r = self.rows[i]
            if origins is not None and r["Origen"] not in origins:
                continue
            if precisions is not None and r["PrecisionFecha"] not in precisions:
                continue
            if (len(code) == 2 and not whole) or not compatible(r["DangerType"], danger):
                continue
            if len(code) == 6 and r["Ubigeo"] != code:
                continue
            score = (abs(d - center), r["DangerType"] != danger, i)
            if best is None or score < best[0]:
                best = (score, i)
        return best[1] if best else None


def _attach(target: dict, cand: dict) -> None:
    target["Corroboracion"] = int(target.get("Corroboracion") or 0) + 1
    links = [u for u in (target.get("FuentesAdicionales") or "").split(" | ") if u]
    if cand["Fuente"] not in links and len(links) < MAX_LINKS and cand["Fuente"] != target["Fuente"]:
        links.append(cand["Fuente"])
    target["FuentesAdicionales"] = " | ".join(links)
    origins = set(filter(None, (target.get("OrigenesCorroboran") or "").split(",")))
    origins.add(cand["Origen"])
    target["OrigenesCorroboran"] = ",".join(sorted(origins))
    if cand.get("_decretos"):
        target.setdefault("_decretos", [])
        target["_decretos"] += [d for d in cand["_decretos"] if d not in target["_decretos"]]
    if cand["Origen"] == "coen":
        imp = {k: cand.get(k) for k in E.IMPACT_COLUMNS if cand.get(k)}
        if imp and target.get("ImpactoReportado") != "si":
            target.update(imp)
            target["ImpactoReportado"] = "si"
            target["FuenteCita"] = f"{target['FuenteCita']}; cifras de daños: {cand['FuenteCita']}"
            target["Descripción"] = (f"{target['Descripción']} Daños según el COEN: "
                                     + ", ".join(f"{E.IMPACT_LABELS.get(k, k)} {_fmt(v)}" for k, v in imp.items()) + ".").strip()
        if target["Origen"] == "sinpad" and "Según el COEN" not in target["Descripción"] and cand.get("_relato"):
            target["Descripción"] = f"{target['Descripción']} Según el COEN: «{cand['Descripción'][:300]}»".strip()


def _fmt(v) -> str:
    v = float(v)
    return f"{v:,.0f}".replace(",", " ") if v == int(v) else f"{v:,.2f}".replace(",", " ")


def link(records: list[dict], candidates: Iterable[dict], stats: Optional[Counter] = None) -> list[dict]:
    """Une los candidatos a las filas (``records`` se modifica) y devuelve los que quedan como filas propias. Los
    candidatos se procesan en el orden dado: primero el COEN, después la prensa, para que una nota pueda
    corroborar una emergencia que solo el COEN registró."""
    stats = stats if stats is not None else Counter()
    for r in records:
        r.setdefault("Corroboracion", 0)
        r.setdefault("FuentesAdicionales", "")
        r.setdefault("OrigenesCorroboran", "")
        r.setdefault("FechaTipo", "evento")
    pool = list(records)
    idx = _Index(pool)
    added: list[dict] = []
    for c in candidates:
        d = _ord(c["Date"])
        hit = None
        if c["Origen"] == "coen":
            if c.get("_sinpad") and c["_sinpad"] in idx.sinpad:
                hit, how = idx.sinpad[c["_sinpad"]], "código SINPAD"
            elif c.get("FechaTipo") == "evento":
                hit, how = idx.find(c["Ubigeo"], d - 3, d + 3, c["DangerType"], d), "lugar y fecha"
            else:
                hit, how = idx.find(c["Ubigeo"], d - 10, d + 1, c["DangerType"], d), "lugar y fecha"
            if hit is None and c.get("_sinpad") is not None:
                hit, how = idx.find(c["Ubigeo"], d - 30, d + 30, c["DangerType"], d, origins={"sinpad"}), "lugar y mes"
        elif c["Origen"] == "hemeroteca":
            whole = len(c["Ubigeo"]) == 2
            hit, how = idx.find(c["Ubigeo"], d - ARCHIVE_DAYS, d + 1, c["DangerType"], d, whole=whole), "lugar y fecha"
            if hit is None:
                month = date.fromisoformat(c["Date"][:8] + "01").toordinal()
                hit, how = idx.find(c["Ubigeo"], month, month, c["DangerType"], d, precisions={"mes"}, whole=whole), \
                    "lugar y mes"
            if hit is None:
                year = date(int(c["Date"][:4]), 1, 1).toordinal()
                hit, how = idx.find(c["Ubigeo"], year, year, c["DangerType"], d, precisions={"anio"}, whole=whole), \
                    "lugar y año"
        elif c["Origen"] != "prensa":  # otra fuente de eventos con fecha propia (GLOF)
            if c["PrecisionFecha"] == "dia":
                hit, how = idx.find(c["Ubigeo"], d - 3, d + 3, c["DangerType"], d), "lugar y fecha"
            elif c["PrecisionFecha"] == "mes":
                first = date.fromisoformat(c["Date"][:8] + "01")
                nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
                hit, how = idx.find(c["Ubigeo"], first.toordinal(), nxt.toordinal() - 1, c["DangerType"], d), "lugar y mes"
        else:
            if c["PrecisionFecha"] == "mes":
                first = date.fromisoformat(c["Date"][:8] + "01")
                prev = date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1)
                nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
                hit, how = idx.find(c["Ubigeo"], prev.toordinal(), nxt.toordinal() - 1, c["DangerType"], d), "lugar y mes"
            elif c.get("FechaTipo") == "texto":
                pub = _ord(c.get("_publicado") or c["Date"])
                hit, how = idx.find(c["Ubigeo"], d - 3, pub + 1, c["DangerType"], d), "lugar y fecha del texto"
            else:
                hit, how = idx.find(c["Ubigeo"], d - 10, d + 1, c["DangerType"], d), "lugar y fecha"
        if hit is not None:
            _attach(pool[hit], c)
            stats[f"{c['Origen']}: corrobora ({how})"] += 1
            continue
        stats[f"{c['Origen']}: fila propia"] += 1
        c.setdefault("Corroboracion", 0)
        c.setdefault("FuentesAdicionales", "")
        c.setdefault("OrigenesCorroboran", "")
        pool.append(c)
        idx.add(len(pool) - 1, c)
        added.append(c)
    return added


# ---------------------------------------------------------------------------
# Prevención
# ---------------------------------------------------------------------------
#: Una declaratoria por peligro inminente cubre los eventos de los 12 meses siguientes (las declaratorias duran
#: 60 días y se prorrogan; la temporada de lluvias dura de diciembre a abril).
IMMINENT_DAYS = 365


def prevention(records: list[dict], decrees: list[dict], evaluations: list[dict], appeals: Optional[list[dict]] = None,
               since: int = 2003, origins: Optional[set] = None) -> dict:
    """Indicadores de prevención por distrito y por año.

    * ``distritos``: {ubigeo: [decretosInminente, decretosImpacto, prorrogas, evaluaciones, primeraEvaluacion,
      puntosInventario, inventarioDesde, eventos, eventosTrasEvaluacion, eventosTrasInventario, eventosTrasInminente,
      eventosConAviso, aniosConEvento]}.
    * ``anual``: por año, decretos por peligro inminente, por impacto y prórrogas; evaluaciones técnicas; puntos
      inventariados; llamamientos internacionales por desastres climáticos (IFRC); eventos (de ``origins``, por
      defecto las fuentes oficiales con fecha de evento) y cuántos ocurrieron cuando el peligro del distrito ya
      estaba evaluado, inventariado o declarado inminente.

    Las declaratorias de una provincia o un departamento entero cuentan para cada uno de sus distritos.

    Un evento cuenta «tras evaluación» si su distrito tenía un informe técnico (INGEMMET, IGP) de un año anterior
    del mismo grupo de peligro (o de cualquiera si el informe no lo dice; un informe de huaicos vale para
    «lluvias intensas»), «tras inventario» si INGEMMET ya había inventariado ahí un peligro de ese grupo en un año
    anterior, y «tras inminente» si hubo una declaratoria por peligro inminente que cubría su distrito y un peligro
    compatible (``compatible``: una declaratoria por lluvias cubre los huaicos) en los 365 días previos, o si el COEN dice que el distrito estaba declarado en emergencia por
    peligro inminente cuando ocurrió. ``eventosConAviso``: cualquiera de los tres."""
    origins = origins or {"desinventar", "sinpad", "coen"}
    reports: dict[str, list[tuple[int, str]]] = defaultdict(list)
    inventory: dict[str, list[tuple[int, str]]] = defaultdict(list)
    dist = defaultdict(lambda: Counter())
    yearly = defaultdict(Counter)
    for e in evaluations:
        inv = e.get("tipo") == "inventario"
        for code in e["ubigeos"]:
            if len(code) == 6:
                (inventory if inv else reports)[code].append((e["anio"], e.get("grupo", "")))
                if inv:
                    dist[code]["puntosInventario"] += e.get("puntos", 1)
        yearly[e["anio"]]["puntosInventario" if inv else "evaluaciones"] += e.get("puntos", 1) if inv else 1
    imminent: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for d in decrees:
        y = int(d["fecha"][:4])
        key = {"inminente": "decretosInminente", "impacto": "decretosImpacto"}.get(d["tipo"], "prorrogas")
        yearly[y][key] += 1
        for code in d["ubigeos"]:
            dist[code][key] += 1
            if d["tipo"] in ("inminente", "prorroga"):
                imminent[code].append((_ord(d["fecha"]), d["peligro"]))
    for a in appeals or []:
        if a.get("clima"):
            yearly[int(a["fecha"][:4])]["llamamientosClima"] += 1
    for code, lst in reports.items():
        dist[code]["evaluaciones"] = len(lst)
        dist[code]["primeraEvaluacion"] = min(y for y, _ in lst)
    for code, lst in inventory.items():
        dist[code]["inventarioDesde"] = min(y for y, _ in lst)

    def covers(eg: str, g: str, danger: str) -> bool:
        return not eg or eg == g or (danger == "Lluvias intensas" and eg in RAIN_GROUPS)

    years_with = defaultdict(set)
    for r in records:
        if r["Origen"] not in origins or r.get("FechaTipo", "evento") != "evento" or len(r["Ubigeo"]) != 6:
            continue
        y = int(r["Anio"])
        if y < since:
            continue
        code, g, d, dt = r["Ubigeo"], r["GrupoPeligro"], _ord(r["Date"]), r["DangerType"]
        dist[code]["eventos"] += 1
        years_with[code].add(r["AnioHidrologico"] or str(y))
        yearly[y]["eventos"] += 1
        flags = {
            "eventosTrasEvaluacion": any(ey < y and covers(eg, g, dt) for ey, eg in reports.get(code, [])),
            "eventosTrasInventario": any(ey < y and covers(eg, g, dt) for ey, eg in inventory.get(code, [])),
            "eventosTrasInminente": any(0 <= d - dd <= IMMINENT_DAYS and (not dp or compatible(dp, dt))
                                        for area in (code, code[:4], code[:2]) for dd, dp in imminent.get(area, []))
            or any(x.get("inminente") for x in r.get("_decretos") or []),
        }
        flags["eventosConAviso"] = any(flags.values())
        for k, v in flags.items():
            if v:
                dist[code][k] += 1
                yearly[y][k] += 1
    for code, ys in years_with.items():
        dist[code]["aniosConEvento"] = len(ys)
    # Una declaratoria de toda una provincia o un departamento cubre a cada uno de sus distritos.
    areas = {c: dist.pop(c) for c in [c for c in dist if len(c) < 6]}
    for code, v in dist.items():
        for area in (code[:4], code[:2]):
            for k in ("decretosInminente", "decretosImpacto", "prorrogas"):
                v[k] += areas.get(area, {}).get(k, 0)
    cols = ["decretosInminente", "decretosImpacto", "prorrogas", "evaluaciones", "primeraEvaluacion", "puntosInventario",
            "inventarioDesde", "eventos", "eventosTrasEvaluacion", "eventosTrasInventario", "eventosTrasInminente",
            "eventosConAviso", "aniosConEvento"]
    acols = ["decretosInminente", "decretosImpacto", "prorrogas", "evaluaciones", "puntosInventario", "llamamientosClima",
             "eventos", "eventosTrasEvaluacion", "eventosTrasInventario", "eventosTrasInminente", "eventosConAviso"]
    return {
        "columnas": cols,
        "distritos": {c: [v.get(k, 0) or 0 for k in cols] for c, v in sorted(dist.items())},
        "columnasAnual": ["anio"] + acols,
        "anual": [[y] + [yearly[y].get(k, 0) for k in acols] for y in sorted(yearly)],
    }
