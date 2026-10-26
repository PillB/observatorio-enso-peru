"""Boletín Semanal Oceanográfico y Biológico-Pesquero del IMARPE (BS-OBP): anomalía subsuperficial frente a
Paita y Chicama, con su cita.

El IMARPE publica el boletín cada semana (domingo) en su repositorio institucional
(repositorio.imarpe.gob.pe, DSpace). El resumen de la primera página describe la columna de agua frente a la
costa norte con la plataforma que la midió: los puntos fijos a 7 mn de Paita y 15 mn de Chicama, las secciones
del monitoreo bio-oceanográfico, los perfiladores Argo o un crucero. No hay serie numérica: el valor está en
la frase («persistieron anomalías superiores a +8 °C (Paita) y +7 °C (Chicama), por encima de los 100 m»), y
la profundidad de la isoterma de 15 °C (la termoclina costera del IMARPE y el ENFEN) solo a veces.

Se toma lo que dice el texto, sin convertirlo en D20 ni aplicarle los umbrales de la GRD: la anomalía más
intensa que el resumen atribuye a cada lugar, la capa, la plataforma y la cita con su página. Una semana sin
frase sobre la columna de agua frente a esos lugares es normal (el muestreo no es semanal) y se publica como
«sin dato subsuperficial esta semana», no como error.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from ..reports import Paged, _flat, _num, _plain, check

SITES = ("Paita", "Chicama")
#: Días sin un boletín nuevo en el repositorio después de los cuales se avisa (se publica cada domingo).
OVERDUE_DAYS = 12

TITLE_RE = re.compile(r"Bolet[ií]n\s+Semanal\s+Oceanogr[aá]fico\s+y\s+Biol[oó]gico\s*-?\s*Pesquero", re.I)
_HEAD = re.compile(r"A[ñn]o\s+(\d+)\s*,\s*N\s*[°º]\s*(\d{1,2})\s+Semana\s+(\d{1,2})\s*:\s*([^\n]{5,70})", re.I)

_VALUE = re.compile(r"(?<![\w,])([+\-−–]\s?\d+(?:,\d+)?)\s*°\s*C")
_SITE = re.compile(r"\b(" + "|".join(SITES) + r")\b")
_DEPTH = re.compile(r"\b\d{2,3}\s*m\b(?!\w|/)")
_LAYER = re.compile(r"(?:por\s+encima\s+de\s+los|sobre\s+los|en\s+los\s+primeros|hasta\s+los|por\s+debajo\s+de\s+los|"
                    r"debajo\s+de\s+los|entre\s+(?:los\s+)?\d+\s+y|a\s+los\s+~?|espesor\s+(?:cercano\s+a|de)\s+)\s*\d+(?:\s*[-–]\s*\d+)?\s*m\b",
                    re.I)
_SUBSURFACE = re.compile(r"subsuperficial|sub-superficial|columna\s+de\s+agua|profundidad|isoterma|termoclina|"
                         r"perfilador|puntos?\s+fijos?|estaci[oó]n(es)?\s+fijas?|secci[oó]n", re.I)
#: Frases que no son observaciones de la columna de agua: superficie, pronóstico, nivel del mar, viento.
_SKIP = re.compile(r"\bTSM\b|superficial(es)?\s+del\s+mar|nivel\s+del\s+mar|\bANM\b|viento|\bVV\b|se\s+prev[eé]|"
                   r"pronostic|ola\s+de\s+calor|\bOCM\b|^(Figura|Estructura|Variaci[oó]n|Diagrama|Distribuci[oó]n)", re.I)
_PLATFORMS = [
    ("estacion_fija", r"puntos?\s+fijos?|estaci[oó]n(es)?\s+fijas?"),
    ("argo", r"perfilador|\bargo\b"),
    ("glider", r"glider|planeador"),
    ("boya", r"\bboya"),
    ("seccion", r"secci[oó]n|secciones|monitoreo|crucero|\bBIC\b|embarcaci[oó]n|in\s+situ"),
]
_ISO15 = re.compile(r"isoterma\s+de\s+15\s*°\s*C[^.;]{0,80}?(?:(?:alcanz\w+|lleg\w+|ubic\w+|a)\s+(?:los\s+)?(\d{2,3})\s*m"
                    r"|desde\s+(?:los\s+)?(\d{2,3})\s+(?:a|hasta)\s+(?:los\s+)?(\d{2,3})\s*m)", re.I)

SCHEMA = {
    "type": "object",
    "required": ["number", "week", "period", "sites"],
    "properties": {
        "number": {"type": "integer", "minimum": 1, "maximum": 53},
        "week": {"type": "integer", "minimum": 1, "maximum": 53},
        "period": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "sites": {"type": "object"},
    },
}
SITE_SCHEMA = {
    "type": "object",
    "required": ["anomaly", "quote", "page"],
    "properties": {
        "anomaly": {"type": "number", "minimum": -8, "maximum": 14},
        "depth": {"type": ["number", "null"], "minimum": 0, "maximum": 600},
        "page": {"type": "integer", "minimum": 1, "maximum": 40},
    },
}

_MONTHS = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                       "septiembre", "octubre", "noviembre", "diciembre"), 1)}
_MONTHS["setiembre"] = 9


def _week_end(text: str) -> Optional[str]:
    """Último día de «Semana 42: 12 - 18 de octubre de 2026» (o «28 de septiembre - 4 de octubre de 2026»)."""
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+(?:del?\s+)?(\d{4})\s*$", _flat(text), re.I)
    if not m or _plain(m.group(2)) not in _MONTHS:
        return None
    try:
        return date(int(m.group(3)), _MONTHS[_plain(m.group(2))], int(m.group(1))).isoformat()
    except ValueError:
        return None


def _paragraphs(doc: Paged):
    """Viñetas «»» del resumen (posición, texto aplanado). Sin viñetas, el texto antes de la primera figura."""
    t = doc.text
    end = re.search(r"\n\s*Figura\s+1\b", t)
    t = t[:end.start()] if end else t
    marks = [m.start() for m in re.finditer(r"»", t)] or [0]
    for a, b in zip(marks, marks[1:] + [len(t)]):
        yield a, t[a:b]


def _sentences(pos: int, text: str):
    p = 0
    for m in re.finditer(r"(?<!\d)\.(?=\s+[A-ZÁÉÍÓÚÑ»(])|;\s", text):
        yield pos + p, _flat(text[p:m.end()])
        p = m.end()
    if p < len(text):
        yield pos + p, _flat(text[p:])


def _platform(text: str) -> Optional[str]:
    for code, pat in _PLATFORMS:
        if re.search(pat, text, re.I):
            return code
    return None


#: Otros lugares de la costa: una cláusula que los nombra no se atribuye a Paita o Chicama.
_OTHER = re.compile(r"Punta\s+La\s+Negra|Bermejo|Talara|Tumbes|Chimbote|Huarmey|Huacho|Callao|Pisco|San\s+Jos[eé]|"
                    r"San\s+Juan|Chala|Atico|Camaná|Ilo|Huanchaco|Salaverry|Sechura|Lobos|Malabrigo|Mórrope", re.I)


def _clauses(sent: str):
    """Trozos de una frase que hablan de un solo lugar: se corta en «, mientras que», «; », «por otro lado», etc."""
    parts = re.split(r",?\s+mientras\s+que,?|,\s+en\s+cambio,?|,\s+y\s+(?=frente|en\s)|,\s+(?=en\s+(?:"
                     + "|".join(SITES) + r")\b)|\bpor\s+debajo\b|\bpor\s+otro\s+lado\b", sent)
    return [c for c in parts if c and c.strip()]


def _assign(sent: str) -> dict[str, tuple[float, re.Match, str]]:
    """Cada lugar con el valor de anomalía más intenso que la frase le atribuye sin ambigüedad: el lugar entre
    paréntesis tras el valor («+8 °C (Paita)»), o la cláusula que nombra solo a Paita y/o Chicama, sin otro lugar
    de la costa ni un tramo («desde Chicama a Huarmey»). Lo demás se deja: mejor sin dato que un valor ajeno."""
    out: dict[str, tuple[float, re.Match, str]] = {}

    def put(site: str, v: float, m: re.Match, clause: str) -> None:
        if site not in out or abs(v) > abs(out[site][0]):
            out[site] = (v, m, clause)

    for clause in _clauses(sent):
        sites_here = set(_SITE.findall(clause))
        tramo = re.search(r"\b(desde|entre)\s+(" + "|".join(SITES) + r")\s+(a|y|hasta)\s+(?!(" + "|".join(SITES)
                          + r")\b)", clause)
        for m in _VALUE.finditer(clause):
            try:
                v = _num(m.group(1))
            except ValueError:
                continue
            # «+8 °C (Paita)» o «+8 °C frente a Paita»: el lugar justo después del valor.
            names = "|".join(SITES)
            paren = re.match(r"\s*(?:\(|frente\s+a\s+|en\s+)(" + names + r")\b(?:\s*\([^)]*\))?(?:\s+y\s+(" + names
                             + r")\b)?", clause[m.end():])
            if paren:
                for site in filter(None, paren.groups()):
                    put(site, v, m, clause)
            elif sites_here and not _OTHER.search(clause) and not tramo \
                    and not re.search(r"\(\s*(?:" + "|".join(SITES) + r")\s*\)", clause):
                for site in sites_here:
                    put(site, v, m, clause)
    return out


def _platform_near(sents: list[str], i: int) -> Optional[str]:
    """La plataforma de la frase; si no la dice, la de la frase anterior más cercana del mismo párrafo."""
    for j in range(i, -1, -1):
        p = _platform(sents[j])
        if p:
            return p
    return None


def parse(pages: list[str]) -> dict:
    """Número, semana, fecha de cierre y, por lugar, la anomalía subsuperficial con capa, plataforma y cita."""
    doc = Paged(pages)
    h = _HEAD.search(pages[0] if pages else "")
    if not h:
        raise ValueError("no se reconoce la cabecera «Año …, N° … Semana …» del boletín")
    period = _week_end(h.group(4))
    if not period:
        raise ValueError(f"no se reconoce la fecha de la semana: {h.group(4)!r}")
    sites: dict[str, dict] = {}
    iso15: Optional[dict] = None
    for ppos, para in _paragraphs(doc):
        sents = list(_sentences(ppos, para))
        for i, (pos, sent) in enumerate(sents):
            if _SKIP.search(sent) and not re.search(r"subsuperficial|columna\s+de\s+agua", sent, re.I):
                continue
            if not (_SUBSURFACE.search(sent) or _LAYER.search(sent)) or not _DEPTH.search(sent):
                continue
            mi = _ISO15.search(sent)
            # La isoterma de 15 °C se atribuye al último lugar nombrado antes de ella, si es Paita o Chicama
            # («… frente a Chimbote donde la isoterma de 15 °C alcanzó los 250 m» no cuenta).
            before = [x.group(0) for x in re.finditer(_SITE.pattern + "|" + _OTHER.pattern, sent[:mi.start()], re.I)] \
                if mi else []
            if mi and iso15 is None and before and before[-1] in SITES:
                nums = [int(g) for g in mi.groups() if g]
                iso15 = {"site": before[-1], "depth": nums[-1], "from": nums[0] if len(nums) == 2 else None,
                         "quote": sent[:600], "page": doc.page(pos)}
            for site, (v, m, clause) in _assign(sent).items():
                if site in sites and abs(v) <= abs(sites[site]["anomaly"]):
                    continue
                layer = _LAYER.search(clause, m.end()) or _LAYER.search(clause) or _LAYER.search(sent)
                depth = float(re.findall(r"\d+", layer.group(0))[-1]) if layer else None
                # «… sobre los 150 m y 100 m, respectivamente»: cada lugar con su profundidad, en el orden en que se nombran.
                order = list(dict.fromkeys(_SITE.findall(sent)))
                resp = re.findall(r"(\d{2,3})\s*m\b", clause[m.end():]) if "respectivamente" in clause else []
                if len(order) > 1 and len(resp) >= len(order):
                    depth = float(resp[order.index(site)])
                    layer_text = (re.sub(r"\d+(?=\s*m\b)", resp[order.index(site)], _flat(layer.group(0)), count=1)
                                  if layer else f"hasta los {resp[order.index(site)]} m")
                else:
                    layer_text = _flat(layer.group(0)) if layer else None
                sites[site] = {"anomaly": v, "layer": layer_text, "depth": depth,
                               "platform": _platform_near([x for _, x in sents], i), "quote": sent[:600],
                               "page": doc.page(pos)}
    data = {"number": int(h.group(2)), "week": int(h.group(3)), "period": period, "volume": int(h.group(1)),
            "sites": sites, "isotherm15": iso15}
    errs = check(SCHEMA, data)
    for s, v in sites.items():
        errs += check(SITE_SCHEMA, v, f"$.sites.{s}")
    if errs:
        raise ValueError("; ".join(errs))
    return data


def overdue(last_issued: Optional[str], today: date) -> bool:
    """¿Pasaron más de ``OVERDUE_DAYS`` desde el último boletín en el repositorio?"""
    if not last_issued:
        return True
    try:
        return today - date.fromisoformat(last_issued[:10]) > timedelta(days=OVERDUE_DAYS)
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# Lectura diaria desde el repositorio del IMARPE
# ---------------------------------------------------------------------------
SOURCE = "imarpe-bsobp"
QUERY = '"Boletín Semanal Oceanográfico y Biológico"'
#: Boletines leídos que se conservan (un año).
KEEP = 53
#: Boletines nuevos que se bajan por corrida (≈5 MB cada uno); el resto queda para la siguiente.
MAX_NEW = 2
SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "imarpe-bsobp-history.json"
_TITLE_NUM = re.compile(r"N\s*[°º]\s*(\d{1,2})\s*,\s*(\d{4})")


def doc_id(year: int, number: int) -> str:
    return f"imarpe-bsobp-{year}-{number:02d}"


def manual_key(year: int, number: int) -> str:
    """URL sintética con que la consola guarda el PDF cuando el repositorio no da su dirección."""
    from .. import manual

    return manual.key(SOURCE, f"{year}-{number:02d}")


def _listed(fetcher, problems: Optional[list] = None) -> list[dict]:
    from . import imarpe_repo

    out = []
    for it in imarpe_repo.search(fetcher, QUERY, 8, problems):
        m = _TITLE_NUM.search(it["title"])
        if TITLE_RE.search(it["title"]) and m:
            out.append({**it, "number": int(m.group(1)), "year": int(m.group(2))})
    return out


def _read(fetcher, item: dict) -> tuple[Optional[dict], Optional[str], Optional[str]]:
    """(lectura, url del PDF, problema). La lectura lleva la cita, la página del ítem y por dónde llegó."""
    from ..reports import pdf_pages
    from . import imarpe_repo

    files = imarpe_repo.pdfs(fetcher, item["uuid"])
    if files:
        url = files[0]["url"]
        resp = imarpe_repo.fetch_pdf(fetcher, url)
        if resp is None:
            return None, url, "el PDF no se pudo bajar (o no era un PDF)"
    else:
        # Sin la URL del PDF (el ítem no la da o el repositorio no respondió): la copia que una persona haya
        # subido en la consola con la clave sintética del boletín.
        url = manual_key(item["year"], item["number"])
        resp = fetcher.copy(url, ("pdf",)) if hasattr(fetcher, "copy") else None
        if resp is None or resp.body[:5] != b"%PDF-":
            return None, url, "el repositorio no dio la dirección del PDF del boletín"
    try:
        data = parse(pdf_pages(resp.body))
    except Exception as exc:  # noqa: BLE001 — un PDF dañado o con otro formato
        return None, url, f"el PDF no se pudo leer: {type(exc).__name__}: {exc}"[:300]
    if (int(data["period"][:4]) not in (item["year"], item["year"] + 1)) or data["number"] != item["number"]:
        return None, url, (f"el PDF dice N° {data['number']} ({data['period']}) y el repositorio "
                           f"N° {item['number']}-{item['year']}")
    data.update({"year": item["year"], "title": item["title"], "issued": item["issued"], "page": item["page"],
                 "url": None if url.startswith("manual://") else url, "channel": resp.channel,
                 "retrievedAt": resp.archived_at or None})
    return data, url, None


def load_seed() -> list[dict]:
    try:
        return json.loads(SEED_PATH.read_text(encoding="utf-8"))["bulletins"]
    except (OSError, ValueError, KeyError):
        return []


def _envelope(today: date) -> dict:
    return {"version": 1, "source": SOURCE, "institution": "IMARPE",
            "product": "Boletín Semanal Oceanográfico y Biológico-Pesquero (BS-OBP)",
            "docs": "https://repositorio.imarpe.gob.pe", "checkedAt": today.isoformat(),
            "note": ("Anomalía térmica subsuperficial que el resumen del boletín atribuye a Paita y Chicama, tal como "
                     "la escribe el IMARPE, con la plataforma que la midió. No es el D20 y no se le aplican sus umbrales."),
            "pending": []}


def from_seed(today: date) -> dict:
    """Sin red (pruebas con fixtures): los boletines ya leídos que trae el repositorio."""
    return {**_envelope(today), "bulletins": load_seed()[:KEEP], "lastListed": None}


def acquire(fetcher, previous: Optional[dict], log, today: date, needs=None) -> dict:
    """Lee los boletines nuevos del repositorio y devuelve lo que se publica en ``imarpe-bsobp.json``.

    Avisos al administrador (incidencias → issue de GitHub, que llega por correo; se cierra solo):
    - ``bsobp-unreadable``: un boletín listado que no se pudo bajar o leer. Además queda en la consola de
      documentos (``needs``) con su página, para subir el PDF a mano si el repositorio no lo entrega.
    - ``bsobp-overdue``: más de ``OVERDUE_DAYS`` días sin un boletín nuevo en el repositorio.
    - ``bsobp-unreachable``: el repositorio no respondió (se conserva lo anterior).
    Una semana sin frase sobre Paita o Chicama no avisa: es normal."""
    prev = previous if isinstance(previous, dict) else {}
    bulletins = list(prev.get("bulletins") or load_seed())
    have = {(b.get("year"), b.get("number")) for b in bulletins}
    problems: list = []
    listed = _listed(fetcher, problems)
    out = _envelope(today)
    if not listed:
        why = "; ".join(f"{p}: {p.detail}" if getattr(p, "detail", "") else str(p) for p in problems)
        log.add("warning", SOURCE, "fetch", "bsobp-unreachable",
                f"El repositorio del IMARPE no listó boletines semanales{f' ({why})' if why else ''}; se conservan "
                "los ya leídos.")
        out.update({"bulletins": bulletins[:KEEP], "lastListed": prev.get("lastListed")})
        return out
    out["lastListed"] = {k: listed[0][k] for k in ("number", "year", "issued", "page", "title")}
    new = [it for it in listed if (it["year"], it["number"]) not in have]
    for it in new[:MAX_NEW]:
        data, url, problem = _read(fetcher, it)
        if data:
            bulletins.append(data)
            if data.get("channel") == "relay-manual" and needs is not None:
                needs.mark_used(doc_id(it["year"], it["number"]), it["title"], url, data.get("retrievedAt"))
            continue
        label = f"Boletín semanal IMARPE N° {it['number']}-{it['year']}"
        out["pending"].append({"number": it["number"], "year": it["year"], "page": it["page"], "problem": problem})
        log.add("warning", SOURCE, "fetch", "bsobp-unreadable",
                f"{label} ({it['page']}): {problem}. Si el repositorio no lo entrega, abrir la página, bajar el PDF "
                "y subirlo en la consola de documentos; la actualización siguiente lo lee.")
        if needs is not None:
            needs.add(doc_id(it["year"], it["number"]), "imarpe-bsobp", label, [url], [it["page"]],
                      "El repositorio del IMARPE listó el boletín pero el PDF no se pudo bajar o leer.",
                      expect={"number": it["number"], "year": it["year"]}, problem=problem)
    bulletins.sort(key=lambda b: (b.get("period") or ""), reverse=True)
    out["bulletins"] = bulletins[:KEEP]
    if overdue(listed[0].get("issued"), today):
        log.add("warning", SOURCE, "fetch", "bsobp-overdue",
                f"El último boletín semanal en el repositorio del IMARPE es el N° {listed[0]['number']}-"
                f"{listed[0]['year']} ({listed[0].get('issued')}); se publica cada semana. Revisar "
                f"{listed[0]['page']} o el portal del IMARPE.")
    return out
