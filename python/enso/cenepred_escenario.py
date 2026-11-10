"""Escenario de riesgo por lluvias del CENEPRED para cada distrito: lectura diaria desde el SIGRID.

Lo usa la página «Mi zona» (``data/escenario-distritos.json``; si falta, la copia incluida en el sitio,
``assets/capas/escenario-distritos.json``). Sale de la página pública de escenarios del SIGRID
(https://sigrid.cenepred.gob.pe/sigridv3/escenarios, «lluvias, pronóstico trimestral»), que ofrece cada escenario
como una descarga sin inicio de sesión:

- la lista de escenarios (``escenario-trimestral/data-mm``, JSON): número, meses de vigencia, mes en que se elaboró y
  documento del SIGRID que lo sustenta;
- ``storage/escenario_trimestral/<número>_tabla.zip``: dos libros de Excel del CENEPRED, uno por peligro, con una
  fila por distrito (hoja ``BD_…``) y su diccionario de datos.

De cada distrito se guardan solo el nivel que le dio el CENEPRED y lo que cuenta en las áreas de mayor
susceptibilidad (personas, viviendas, establecimientos de salud, instituciones educativas y km de vías), tal como
vienen: aquí no se calcula ni se corrige nada.

Qué escenario se publica (``choose``): el vigente hoy (el mes de hoy está entre su inicio y su fin) y, entre varios
vigentes, el elaborado más recientemente; si ninguno está vigente, el próximo en empezar; si todos vencieron, el que
venció último (y queda la incidencia ``escenario-vencido``). El CENEPRED publica cada mes un escenario de tres meses y,
aparte, uno del verano (enero a marzo) que actualiza varias veces.

Cómo llega (``acquire``): la lista y el ZIP se piden con el cliente de la actualización diaria (``Fetcher.get``), que
lee robots.txt y respeta el Crawl-delay del SIGRID, y si el SIGRID no responde usa la copia de esa misma URL que bajaron
n8n o el servidor del Perú (regla ``follow`` del registro: el ZIP de los tres escenarios de número más alto de la
lista). Si nada llega, se conserva el escenario de la publicación anterior, marcado como conservado; si tampoco hay
uno, la copia incluida en el sitio. Un cambio de formato (columnas, niveles, ubigeos, hojas o un ZIP que no es un ZIP)
detiene la lectura: no se adivina. Cada caso deja su incidencia, que el flujo de la actualización convierte en issue.

Robots: el robots.txt del SIGRID prohíbe ``/sigridv3/storage/``. Es información pública de una entidad peruana
(Ley N° 27806) que la propia página ofrece con un botón; el proyecto la pide igual, con al menos 5 s entre pedidos
(``reach.public_peru``, decisión del 26 de octubre de 2026). Son dos pedidos por corrida.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from .feeds import FormatChanged

SOURCE = "cenepred-escenario"
INSTITUTION = "CENEPRED"
PAGE = "https://sigrid.cenepred.gob.pe/sigridv3/escenarios"
LIST_URL = "https://sigrid.cenepred.gob.pe/sigridv3/escenario-trimestral/data-mm"
TABLE_URL = "https://sigrid.cenepred.gob.pe/sigridv3/storage/escenario_trimestral/{id}_tabla.zip"
DOC_URL = "https://sigrid.cenepred.gob.pe/sigridv3/documento/{doc}"
#: Regla ``follow`` del registro: n8n y el servidor del Perú bajan, de la lista, el ZIP de los ``max`` escenarios de
#: número más alto (el vigente y los próximos están siempre entre ellos: los números crecen con cada publicación).
FOLLOW = {"pattern": r'"id"\s*:\s*"(\d{1,6})"', "template": TABLE_URL.replace("{id}", "{1}"), "max": 3,
          "order": "desc"}
#: Copia incluida en el sitio (``tools.build_escenario_distritos``).
SEED_PATH = Path(__file__).resolve().parents[2] / "public" / "assets" / "capas" / "escenario-distritos.json"
#: Niveles del CENEPRED, de mayor a menor.
RISK_LEVELS = ["Muy Alto", "Alto", "Medio", "Bajo"]
#: Por peligro: cómo se llama la hoja de datos del libro y qué columnas se leen (nivel de riesgo y lo que hay en las
#: áreas de mayor susceptibilidad: personas, viviendas, establecimientos de salud, instituciones educativas, km de vías).
HAZARDS = {
    "mm": {"name": "Movimientos en masa (huaycos y deslizamientos)", "sheet": "BD_ERMMasa",
           "cols": ["nriesg_mm", "pob_smm", "viv_smm", "eess_smm", "iiee_smm", "vias_smm"]},
    "inu": {"name": "Inundaciones", "sheet": "BD_ERInund",
            "cols": ["nriesg_inu", "pob_sinu", "viv_sinu", "eess_sinu", "iiee_sinu", "vias_sinu"]},
}
FIELDS = ["nivel", "personas", "viviendas", "salud", "educativas", "viasKm"]
#: Menos distritos que esto en una tabla es un archivo cortado o de otro alcance (el país tiene 1 891).
MIN_DISTRICTS = 1800
#: Días tras el inicio del mes siguiente al del escenario mostrado en que debería haber uno más nuevo vigente.
GRACE_DAYS = 15
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
_MONTH = re.compile(r"^\d{4}-\d{2}-\d{2}")


# --- Leer un libro de Excel sin dependencias ------------------------------------------------------------------------

def _col(ref: str) -> int:
    """Índice de columna de una celda: «A1» → 0, «AB7» → 27."""
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def sheets(data: bytes) -> dict[str, list[list]]:
    """{hoja: filas} de un .xlsx: cada fila, la lista de sus valores (texto, número o ``None``) por columna."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall("p:Relationship", NS)}
        out: dict[str, list[list]] = {}
        for s in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS):
            target = rels[s.get(f"{{{NS['r']}}}id")].lstrip("/")
            path = target if target.startswith("xl/") else f"xl/{target}"
            rows: list[list] = []
            for row in ET.fromstring(z.read(path)).iter(f"{{{NS['m']}}}row"):
                vals: list = []
                for c in row.findall("m:c", NS):
                    i = _col(c.get("r"))
                    vals.extend([None] * (i + 1 - len(vals)))
                    v, t = c.find("m:v", NS), c.get("t")
                    if t == "inlineStr":
                        vals[i] = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                    elif v is None or v.text is None:
                        vals[i] = None
                    elif t == "s":
                        vals[i] = shared[int(v.text)]
                    elif t in ("str", "b", "e"):
                        vals[i] = v.text
                    else:
                        f = float(v.text)
                        vals[i] = int(f) if f.is_integer() else f
                rows.append(vals)
            out[s.get("name")] = rows
        return out
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, AttributeError, TypeError, IndexError) as exc:
        raise FormatChanged(f"libro de Excel ilegible: {type(exc).__name__}: {exc}"[:300]) from exc


# --- La lista de escenarios ------------------------------------------------------------------------------------------

def scenarios(body: bytes | str) -> list[dict]:
    """Los escenarios de la lista del SIGRID, validados. Falla (``FormatChanged``) si no es la lista esperada."""
    try:
        data = json.loads(body.decode("utf-8-sig") if isinstance(body, bytes) else body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise FormatChanged(f"la lista de escenarios no es JSON ({exc})"[:300]) from exc
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise FormatChanged("la lista de escenarios no trae «data» o viene vacía")
    out = []
    for r in rows:
        if not isinstance(r, dict) or not re.fullmatch(r"\d{1,6}", str(r.get("id", ""))) or not all(
                _MONTH.match(str(r.get(k) or "")) for k in ("mes_inicio_vigencia", "mes_fin_vigencia", "mes_elaboracion")):
            raise FormatChanged(f"escenario con otra forma: {str(r)[:200]}")
        if r["mes_inicio_vigencia"][:7] > r["mes_fin_vigencia"][:7]:
            raise FormatChanged(f"escenario {r['id']}: termina antes de empezar")
        out.append({k: str(r.get(k) or "") for k in ("id", "mes_inicio_vigencia", "mes_fin_vigencia",
                                                     "mes_elaboracion", "id_documento")})
    return out


def _key(s: dict) -> tuple:
    return s["mes_elaboracion"][:7], s["mes_inicio_vigencia"][:7], int(s["id"])


def choose(items: list[dict], today: date) -> tuple[dict, str, Optional[dict]]:
    """(escenario que se publica, por qué: ``vigente`` | ``proximo`` | ``vencido``, el siguiente en empezar o
    ``None``). Ver la regla en el encabezado del módulo."""
    if not items:
        raise FormatChanged("la lista de escenarios viene vacía")
    month = today.strftime("%Y-%m")
    in_force = [s for s in items if s["mes_inicio_vigencia"][:7] <= month <= s["mes_fin_vigencia"][:7]]
    later = [s for s in items if s["mes_inicio_vigencia"][:7] > month]
    if in_force:
        shown, why = max(in_force, key=_key), "vigente"
    elif later:
        start = min(s["mes_inicio_vigencia"][:7] for s in later)
        shown, why = max((s for s in later if s["mes_inicio_vigencia"][:7] == start), key=_key), "proximo"
    else:
        shown, why = max(items, key=lambda s: (s["mes_fin_vigencia"][:7], *_key(s))), "vencido"
    nxt = [s for s in later if s is not shown and s["mes_inicio_vigencia"][:7] > shown["mes_inicio_vigencia"][:7]]
    upcoming = None
    if nxt:
        start = min(s["mes_inicio_vigencia"][:7] for s in nxt)
        upcoming = max((s for s in nxt if s["mes_inicio_vigencia"][:7] == start), key=_key)
    return shown, why, upcoming


def pick(items: list[dict], wanted: Optional[str] = None, today: Optional[date] = None) -> dict:
    """El escenario pedido por número o, sin número, el que se publicaría hoy (``choose``)."""
    if wanted:
        for s in items:
            if str(s["id"]) == str(wanted):
                return s
        raise FormatChanged(f"el escenario {wanted} no está en la lista del SIGRID")
    return choose(items, today or date.today())[0]


def brief(s: Optional[dict]) -> Optional[dict]:
    if not s:
        return None
    return {"id": str(s["id"]), "from": s["mes_inicio_vigencia"][:7], "until": s["mes_fin_vigencia"][:7],
            "prepared": s["mes_elaboracion"][:7]}


# --- La tabla del escenario -------------------------------------------------------------------------------------------

def _num(v) -> float | int:
    if v is None or v == "":
        return 0
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        raise FormatChanged(f"cifra inesperada {v!r}") from exc
    if f < 0:
        raise FormatChanged(f"cifra negativa {v!r}")
    return int(f) if f.is_integer() else round(f, 1)


def district_rows(rows: list[list], cols: list[str]) -> dict[str, list]:
    """{ubigeo: [nivel (0 = muy alto … 3 = bajo), personas, viviendas, salud, educativas, km de vías]} de la hoja de
    datos de un peligro. Falla si falta una columna o si un distrito trae un nivel que no es de los cuatro."""
    if not rows:
        raise FormatChanged("la hoja de datos viene vacía")
    head = [str(h).strip() if h is not None else "" for h in rows[0]]
    missing = [c for c in ["UBIGEO", *cols] if c not in head]
    if missing:
        raise FormatChanged(f"la hoja no trae las columnas {missing}: el CENEPRED cambió el formato")
    ix = {c: head.index(c) for c in ["UBIGEO", *cols]}
    out: dict[str, list] = {}
    for r in rows[1:]:
        r = r + [None] * (len(head) - len(r))
        if r[ix["UBIGEO"]] in (None, ""):
            continue
        u = str(r[ix["UBIGEO"]]).strip().zfill(6)
        if not re.fullmatch(r"\d{6}", u):
            raise FormatChanged(f"ubigeo inesperado: {u!r}")
        level = " ".join(str(r[ix[cols[0]]] or "").split()).title()
        if level not in RISK_LEVELS:
            raise FormatChanged(f"{u}: nivel de riesgo inesperado {r[ix[cols[0]]]!r}")
        if u in out:
            raise FormatChanged(f"{u}: distrito repetido")
        out[u] = [RISK_LEVELS.index(level), *(_num(r[ix[c]]) for c in cols[1:])]
    return out


def read_tables(zip_bytes: bytes) -> dict[str, dict[str, list]]:
    """{peligro: {ubigeo: fila}} de los libros del ZIP del escenario: cada peligro, del libro que trae su hoja."""
    if not zip_bytes.startswith(b"PK"):
        head = zip_bytes[:200].decode("latin-1", "replace").lower()
        what = "una página HTML (¿inicio de sesión o verificación?)" if "<html" in head or "<!doctype" in head else \
            "otro tipo de archivo"
        raise FormatChanged(f"la tabla del escenario no es un ZIP: llegó {what}")
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = z.namelist()
    except zipfile.BadZipFile as exc:
        raise FormatChanged(f"ZIP dañado o cortado: {exc}") from exc
    found: dict[str, dict[str, list]] = {}
    for name in names:
        if not name.lower().endswith(".xlsx"):
            continue
        try:
            book = sheets(z.read(name))
        except (zipfile.BadZipFile, OSError) as exc:  # un libro cortado dentro del ZIP
            raise FormatChanged(f"{name}: ilegible ({exc})") from exc
        for key, h in HAZARDS.items():
            if h["sheet"] in book:
                if key in found:
                    raise FormatChanged(f"dos libros traen la hoja {h['sheet']}")
                found[key] = district_rows(book[h["sheet"]], h["cols"])
    missing = [h["sheet"] for k, h in HAZARDS.items() if k not in found]
    if missing:
        raise FormatChanged(f"el ZIP no trae las hojas {missing}")
    return found


def build(scenario: dict, tables: dict[str, dict[str, list]], generated_by: str = "python -m tools.build_escenario_distritos") -> dict:
    codes = sorted(set(tables["mm"]) | set(tables["inu"]))
    return {
        "source": "CENEPRED, SIGRID: escenario de riesgo por lluvias con pronóstico trimestral, por movimientos en "
                  "masa y por inundaciones, a nivel distrital",
        "url": PAGE,
        "table": TABLE_URL.format(id=scenario["id"]),
        "document": DOC_URL.format(doc=scenario["id_documento"]) if scenario.get("id_documento") else "",
        "scenario": brief(scenario),
        "generatedBy": generated_by,
        "levels": RISK_LEVELS,
        "hazards": {k: h["name"] for k, h in HAZARDS.items()},
        "fields": FIELDS,
        "note": "Personas, viviendas, establecimientos de salud, instituciones educativas y km de vías en las áreas "
                "de mayor susceptibilidad del distrito, según el CENEPRED. null: el distrito no está en esa tabla.",
        "districts": {u: [tables["mm"].get(u), tables["inu"].get(u)] for u in codes},
    }


def check_coverage(tables: dict[str, dict[str, list]]) -> None:
    """Una tabla con muy pocos distritos es un archivo cortado o de otro alcance: no se publica."""
    for k, t in tables.items():
        if len(t) < MIN_DISTRICTS:
            raise FormatChanged(f"la tabla de {HAZARDS[k]['name'].lower()} trae {len(t)} distritos "
                                f"(se esperan al menos {MIN_DISTRICTS})")


# --- La lectura diaria -------------------------------------------------------------------------------------------------

def load_seed() -> Optional[dict]:
    try:
        doc = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("districts"), dict) and doc.get("scenario") else None


def _valid_previous(doc) -> bool:
    return (isinstance(doc, dict) and isinstance(doc.get("districts"), dict) and len(doc["districts"]) >= MIN_DISTRICTS
            and isinstance(doc.get("scenario"), dict) and doc.get("fields") == FIELDS and doc.get("levels") == RISK_LEVELS)


def from_seed(today: date, why: str = "copia incluida en el sitio") -> Optional[dict]:
    """Sin red (pruebas con fixtures) o sin nada anterior: la copia incluida en el sitio."""
    doc = load_seed()
    if doc is None:
        return None
    return {**doc, "checkedAt": today.isoformat(), "retrievedAt": None, "channel": "seed", "carried": True,
            "seed": True, "problem": why, "listed": None}


def _carry(previous: Optional[dict], today: date, problem: str, log, listed: Optional[dict] = None) -> Optional[dict]:
    if _valid_previous(previous):
        out = {**previous, "checkedAt": today.isoformat(), "carried": True, "problem": problem}
        if listed is not None:
            out["listed"] = listed
        return out
    log.add("warning", SOURCE, "fetch", "escenario-seed",
            "No hay un escenario anterior que conservar: se publica la copia incluida en el sitio "
            f"({(load_seed() or {}).get('scenario')}).")
    return from_seed(today, problem)


def acquire(fetcher, previous: Optional[dict], log, today: date) -> Optional[dict]:
    """Lee la lista y la tabla del escenario que corresponde hoy y devuelve lo que se publica en
    ``escenario-distritos.json`` (o ``None`` si no hay nada que publicar).

    Incidencias (``log``; el flujo de la actualización las vuelve issues y los cierra solo):
    - ``escenario-unreachable`` (aviso): ni el SIGRID ni las copias de n8n o del Perú dieron la lista o la tabla; se
      conserva el escenario anterior.
    - ``escenario-format`` (error): la lista o la tabla cambiaron de forma; se conserva el anterior.
    - ``escenario-newer-unread`` (aviso): la lista trae un escenario distinto del publicado y su tabla no llegó.
    - ``escenario-vencido`` (aviso): ningún escenario de la lista está vigente ni por empezar.
    - ``escenario-seed`` (aviso): no había anterior y se publica la copia incluida en el sitio."""
    from .fetch import FetchError

    prev = previous if _valid_previous(previous) else None
    try:
        lst = fetcher.get([LIST_URL], archive=False)
    except FetchError as exc:
        log.add("warning", SOURCE, "fetch", "escenario-unreachable",
                f"La lista de escenarios del SIGRID no respondió ({exc}); se conserva el escenario publicado.")
        return _carry(prev, today, "la lista de escenarios del SIGRID no respondió", log)
    try:
        items = scenarios(lst.body)
        shown, why, upcoming = choose(items, today)
    except FormatChanged as exc:
        log.add("error", SOURCE, "parse", "escenario-format",
                f"La lista de escenarios del SIGRID cambió de forma: {exc}. Se conserva el escenario publicado; "
                "revisar enso/cenepred_escenario.py.")
        return _carry(prev, today, "la lista de escenarios cambió de forma", log)
    listed = {"count": len(items), "selected": why, "next": brief(upcoming),
              "newest": brief(max(items, key=lambda s: int(s["id"]))), "listedAt": lst.retrieved_at,
              "listChannel": lst.channel}
    if why == "vencido":
        log.add("warning", SOURCE, "validate", "escenario-vencido",
                f"Ningún escenario de la lista del SIGRID está vigente ni por empezar: se muestra el N° {shown['id']}, "
                f"vigente hasta {shown['mes_fin_vigencia'][:7]}. Revisar {PAGE}.")
    url = TABLE_URL.format(id=shown["id"])
    try:
        resp = fetcher.get([url], archive=False, accept=("zip",))
    except FetchError as exc:
        same = prev and str(prev["scenario"].get("id")) == str(shown["id"])
        if not same:
            log.add("warning", SOURCE, "fetch", "escenario-newer-unread",
                    f"La lista del SIGRID da el escenario N° {shown['id']} ({shown['mes_inicio_vigencia'][:7]} a "
                    f"{shown['mes_fin_vigencia'][:7]}) pero su tabla no llegó ({exc}); se conserva el publicado.")
        else:
            log.add("warning", SOURCE, "fetch", "escenario-unreachable",
                    f"La tabla del escenario N° {shown['id']} no llegó ({exc}); se conserva la publicada, que es la misma.")
        return _carry(prev, today, f"la tabla del escenario N° {shown['id']} no llegó", log, listed)
    try:
        tables = read_tables(resp.body)
        check_coverage(tables)
    except FormatChanged as exc:
        log.add("error", SOURCE, "parse", "escenario-format",
                f"La tabla del escenario N° {shown['id']} ({url}) cambió de forma: {exc}. Se conserva el escenario "
                "publicado; revisar enso/cenepred_escenario.py.")
        return _carry(prev, today, f"la tabla del escenario N° {shown['id']} cambió de forma", log, listed)
    import hashlib

    doc = build(shown, tables, generated_by="enso.cenepred_escenario (actualización diaria)")
    doc.update({"checkedAt": today.isoformat(), "retrievedAt": resp.archived_at or resp.retrieved_at,
                "channel": resp.channel, "carried": False, "problem": None, "listed": listed,
                "tableSha256": hashlib.sha256(resp.body).hexdigest()})
    doc["_raw"] = resp.body  # para la copia archivada; no se publica en el JSON
    return doc


# --- Vigencia (panel «¿Qué tan recientes son estos datos?») ----------------------------------------------------------

def _month_start(ym: str) -> date:
    return date(int(ym[:4]), int(ym[5:7]), 1)


def _next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def freshness_item(doc: Optional[dict], today: date) -> dict:
    label = "Escenario de riesgo por lluvias del CENEPRED (por distrito)"
    if not doc or not doc.get("scenario"):
        return {"id": "escenario", "label": label, "state": "sin-dato", "source": SOURCE}
    sc = doc["scenario"]
    end = _next_month(_month_start(sc["until"]))  # día siguiente al fin de vigencia
    # El CENEPRED abre cada mes un escenario nuevo de tres meses: el siguiente se espera para el mes posterior al
    # inicio del mostrado (o, si el mostrado aún no empieza, cuando empiece).
    start = _month_start(sc["from"])
    due = start if sc["from"] > today.strftime("%Y-%m") else _next_month(start)
    expired = today >= end
    degraded = bool(doc.get("carried"))
    late = (today - due).days > GRACE_DAYS
    state = "vencido" if expired else "atrasado" if degraded or late else "al-dia"
    from_, until = sc["from"], sc["until"]
    item = {"id": "escenario", "label": label, "kind": "escenario", "observed": sc.get("prepared"),
            "observedKind": "month", "document": f"Escenario N° {sc.get('id')}, vigente de {from_} a {until}",
            "expectedNext": due.isoformat(), "state": state, "source": SOURCE, "institution": INSTITUTION,
            "retrievedAt": doc.get("retrievedAt"), "channel": doc.get("channel"), "carried": degraded,
            "url": doc.get("url") or PAGE, "validFrom": from_, "validUntil": until}
    notes = []
    if expired:
        notes.append(f"Su vigencia terminó en {until}; el CENEPRED no publicó uno nuevo o no se pudo leer.")
    if doc.get("seed"):
        notes.append("Es la copia incluida en el sitio: no se pudo consultar el SIGRID.")
    elif degraded and doc.get("problem"):
        notes.append(f"Se conserva el último leído: {doc['problem']}.")
    nxt = (doc.get("listed") or {}).get("next")
    if nxt:
        notes.append(f"El CENEPRED ya publicó el siguiente (N° {nxt['id']}, de {nxt['from']} a {nxt['until']}); "
                     "se mostrará cuando empiece su vigencia.")
    if notes:
        item["note"] = " ".join(notes)
    return item


# --- Datos para llevar ------------------------------------------------------------------------------------------------

def csv_text(doc: dict) -> str:
    """El escenario publicado como CSV, una fila por distrito, con los nombres del INEI (``data/ubigeo.json``), para
    un municipio, un colegio o un periodista. Las cifras son las del CENEPRED, sin cambios."""
    import csv
    import io

    try:
        ub = json.loads((Path(__file__).resolve().parent / "data" / "ubigeo.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ub = {}
    names = {k: {r["ubigeo"]: r["name"] for r in ub.get(k) or []} for k in ("departments", "provinces", "districts")}
    sc = doc.get("scenario") or {}
    levels = doc.get("levels") or RISK_LEVELS
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    cols = ["nivel", "personas", "viviendas", "establecimientos_salud", "instituciones_educativas", "vias_km"]
    w.writerow(["ubigeo", "departamento", "provincia", "distrito"] + [f"{c}_movimientos_en_masa" for c in cols]
               + [f"{c}_inundaciones" for c in cols] + ["escenario", "vigente_desde", "vigente_hasta", "elaborado",
                                                         "fuente"])
    for u, pair in sorted((doc.get("districts") or {}).items()):
        row = [u, names["departments"].get(u[:2], ""), names["provinces"].get(u[:4], ""), names["districts"].get(u, "")]
        for r in pair:
            row += ([levels[r[0]], *r[1:]] if r else [""] * len(cols))
        w.writerow(row + [sc.get("id", ""), sc.get("from", ""), sc.get("until", ""), sc.get("prepared", ""),
                          doc.get("table") or PAGE])
    return buf.getvalue()
