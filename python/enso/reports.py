"""Informes en texto libre de las instituciones peruanas: campos que ninguna API publica.

El comunicado oficial del ENFEN trae el estado del sistema de alerta (``feeds.peru``). Su informe técnico,
un PDF de unas 80 páginas que se publica con cada comunicado, trae además dos datos que no están en ningún
archivo estructurado:

* el **ICEN temporal** (ICENtmp) del último mes, un mes antes que el ICEN oficial del IGP, junto con el RONI
  y el ONI temporales (tabla «Valores del ICEN, RONI, ONI y sus categorías»);
* las **probabilidades mensuales** que el ENFEN estima para cada categoría (fría fuerte … cálida
  extraordinaria) en Niño 1+2 y Niño 3.4, y en algunos informes las de la magnitud del verano.

Del comunicado mismo se lee la **perspectiva**: la magnitud que el ENFEN espera en cada región y hasta
cuándo.

Cada valor sale con su procedencia: la URL del documento, su fecha, la página y el texto exacto de donde se
leyó (``evidence``). Antes de publicarse pasa por un esquema (``SCHEMAS``, un subconjunto de JSON Schema que
también sirve de formato de salida para un modelo de lenguaje) y por reglas de plausibilidad
(``validate_informe``): rangos físicos, meses consecutivos, columnas de probabilidad que suman 100, y
coherencia con el ICEN oficial del IGP. Lo que no las pasa no se publica; se conserva el último valor
bueno y queda una incidencia.

La lectura es determinista (expresiones regulares sobre el texto del PDF). Un modelo de lenguaje solo
entra cuando la lectura determinista falla y su resultado no se publica sin revisión (``llm_extract``).
"""

from __future__ import annotations

import io
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from .feeds import MONTHS_ES, FormatChanged
from .feeds.peru import DATE_ES, _date_es

# ---------------------------------------------------------------------------
# Esquemas (subconjunto de JSON Schema: type, enum, minimum, maximum, required, properties, items,
# pattern, minItems, maxItems). Son el contrato de lo publicado y el formato de salida pedido a un modelo.
# ---------------------------------------------------------------------------
CATEGORIES = ["fria_fuerte", "fria_moderada", "fria_debil", "neutro", "calida_debil", "calida_moderada",
              "calida_fuerte", "calida_muy_fuerte", "calida_extraordinaria"]
CATEGORY_ES = {"fria_fuerte": "Fría fuerte", "fria_moderada": "Fría moderada", "fria_debil": "Fría débil",
               "neutro": "Neutro", "calida_debil": "Cálida débil", "calida_moderada": "Cálida moderada",
               "calida_fuerte": "Cálida fuerte", "calida_muy_fuerte": "Cálida muy fuerte",
               "calida_extraordinaria": "Cálida extraordinaria"}
MAGNITUDES = ["debil", "moderada", "fuerte", "muy_fuerte", "extraordinaria"]
REGIONS = ["nino12", "nino34"]
_PERIOD = {"type": "string", "pattern": r"^\d{4}-(0[1-9]|1[0-2])$"}
_DAY = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
_INDEX = {"type": ["number", "null"], "minimum": -4.0, "maximum": 6.0}
_EVIDENCE = {"type": "object", "required": ["quote"], "properties": {
    "quote": {"type": "string", "minLength": 3}, "page": {"type": ["integer", "null"], "minimum": 1}}}
_ROW = {"type": "object", "required": ["period", "icen"], "properties": {
    "period": _PERIOD, "icen": _INDEX, "roni": _INDEX, "oni": _INDEX, "evidence": _EVIDENCE}}
_PCT = {"type": "integer", "minimum": 0, "maximum": 100}
_PROB = {"type": "object", "required": ["region", "months", "categories"], "properties": {
    "region": {"type": "string", "enum": REGIONS},
    "months": {"type": "array", "items": _PERIOD, "minItems": 3, "maxItems": 15},
    "categories": {"type": "object", "properties": {c: {"type": "array", "items": _PCT} for c in CATEGORIES}},
    "summer": {"type": ["object", "null"], "properties": {c: _PCT for c in CATEGORIES}},
    "evidence": _EVIDENCE}}
_SEASON = {"type": "object", "required": ["region", "season", "categories"], "properties": {
    "region": {"type": "string", "enum": REGIONS}, "season": {"type": "string", "minLength": 3},
    "categories": {"type": "object", "properties": {c: _PCT for c in CATEGORIES}}, "evidence": _EVIDENCE}}
SCHEMAS: dict[str, dict] = {
    "enfen-informe": {"type": "object", "required": ["number", "indices", "probabilities"], "properties": {
        "number": {"type": "integer", "minimum": 1, "maximum": 40},
        "dataTo": {"type": ["string", "null"], "pattern": _DAY["pattern"]},
        "indices": {"type": "object", "required": ["official", "provisional"], "properties": {
            "columns": {"type": "array", "items": {"type": "string", "enum": ["icen", "roni", "oni"]}},
            "official": {"type": "array", "items": _ROW, "minItems": 1},
            "provisional": {"type": "array", "items": _ROW}}},
        "probabilities": {"type": "array", "items": _PROB, "maxItems": 2},
        "seasonal": {"type": "array", "items": _SEASON, "maxItems": 2}}},
    "enfen-perspectiva": {"type": "array", "maxItems": 2, "items": {
        "type": "object", "required": ["region", "magnitude", "quote"], "properties": {
            "region": {"type": "string", "enum": REGIONS}, "phase": {"type": "string", "enum": ["calida", "fria"]},
            "magnitude": {"type": "string", "enum": MAGNITUDES},
            "until": {"type": ["string", "null"], "pattern": _PERIOD["pattern"]},
            "then": {"type": ["string", "null"], "enum": MAGNITUDES + [None]},
            "quote": {"type": "string", "minLength": 10}}}},
}


def check(schema: dict, value: Any, path: str = "$") -> list[str]:
    """Errores de ``value`` frente a ``schema`` (lista vacía si cumple)."""
    errs: list[str] = []
    types = schema.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else types
        ok = {"object": isinstance(value, dict), "array": isinstance(value, list),
              "string": isinstance(value, str), "null": value is None,
              "boolean": isinstance(value, bool),
              "integer": isinstance(value, int) and not isinstance(value, bool),
              "number": isinstance(value, (int, float)) and not isinstance(value, bool)}
        if not any(ok.get(t, False) for t in types):
            return [f"{path}: se esperaba {'/'.join(types)}"]
    if value is None:
        return errs
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: «{value}» no está entre los valores admitidos")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > {schema['maximum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: «{value[:40]}» no tiene el formato esperado")
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{path}: texto demasiado corto")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}: falta «{k}»")
        for k, sub in (schema.get("properties") or {}).items():
            if k in value:
                errs += check(sub, value[k], f"{path}.{k}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errs.append(f"{path}: menos de {schema['minItems']} elementos")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: más de {schema['maxItems']} elementos")
        if "items" in schema:
            for i, v in enumerate(value):
                errs += check(schema["items"], v, f"{path}[{i}]")
    return errs


# ---------------------------------------------------------------------------
# Texto del PDF con páginas
# ---------------------------------------------------------------------------
def pdf_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader

    return [(p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]


class Paged:
    """Texto de todas las páginas en una sola cadena, sabiendo en qué página cae cada posición."""

    def __init__(self, pages: list[str]):
        self.text = ""
        self.starts: list[int] = []
        for p in pages:
            self.starts.append(len(self.text))
            self.text += p + "\n\f"

    def page(self, pos: int) -> int:
        n = 0
        for i, s in enumerate(self.starts):
            if s <= pos:
                n = i
        return n + 1


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _plain(s: str) -> str:
    """Minúsculas sin tildes, para comparar etiquetas."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _num(s: str) -> float:
    return float(s.replace("–", "-").replace("−", "-").replace(" ", "").replace(",", "."))


# ---------------------------------------------------------------------------
# Enlace al informe técnico desde el comunicado
# ---------------------------------------------------------------------------
_URL_CHARS = re.compile(r"[\w\-/?=&.%:]+")


def informe_link(text: str) -> Optional[str]:
    """URL del informe técnico citado al final del comunicado.

    El PDF parte la URL en dos líneas («…al-13-de-octubre-\\nde-2026-2/?wpdmdl=2166»): una línea que termina en
    guion sigue en la siguiente. Se quitan los parámetros de visita (``refresh``, ``ind``)."""
    m = re.search(r"https?://\S*/download/informe-t[eé]cnico\S*", text, re.I)
    if not m:
        return None
    url, pos = m.group(0), m.end()
    while url.endswith("-"):
        rest = re.match(r"[ \t]*\n[ \t]*(\S+)", text[pos:]) or re.match(r"[ \t]+(\S+)", text[pos:])
        if not rest or not _URL_CHARS.fullmatch(rest.group(1)) or ("/" not in rest.group(1) and "-" not in rest.group(1)):
            break
        url += rest.group(1)
        pos += rest.end()
    url = re.sub(r"[&?](refresh|ind)=[^&]*", "", url).rstrip(".,;)")
    return url


INFORMES_PAGE = "https://enfen.imarpe.gob.pe/informes-tecnicos/"
_INFORME_HREF = re.compile(r"href=[\"'](https?://[^\"']*/download/informe-tecnico-enfen-ano-\d+-n-?(\d{1,2})-[^\"']*)[\"']", re.I)


def informe_links(html_text: str) -> dict[int, str]:
    """Enlaces de descarga del listado de informes técnicos del portal, por número de informe."""
    out: dict[int, str] = {}
    for m in _INFORME_HREF.finditer(html_text):
        url = re.sub(r"[&?](refresh|ind)=[^&]*", "", m.group(1).replace("&#038;", "&").replace("&amp;", "&"))
        out.setdefault(int(m.group(2)), url)
    return out


# ---------------------------------------------------------------------------
# Tabla de índices (ICEN, RONI, ONI y sus temporales)
# ---------------------------------------------------------------------------
_MON = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "sep": 9,
        "oct": 10, "nov": 11, "dic": 12}
_ROW_RE = re.compile(r"\b(ene|feb|mar|abr|may|jun|jul|ago|set|sep|oct|nov|dic)-(\d{2})\b", re.I)
_VAL_RE = re.compile(r"(?<![\w.,])([–−-]?)\s?(\d{1,2}[.,]\d{1,2})(?![\d])")
_INDEX_TITLE = re.compile(r"Tabla\s+\d+\.\s+Valores\s+del\s+(?:ICEN|ONI)\b", re.I)


def parse_index_table(doc: Paged) -> dict:
    m = _INDEX_TITLE.search(doc.text)
    if not m:
        raise FormatChanged("informe ENFEN: no se encontró la tabla «Valores del ICEN …»")
    end = re.search(r"\n\s*Fuente\s*:|Tabla\s+\d+\.", doc.text[m.end():])
    body = doc.text[m.end(): m.end() + (end.start() if end else 4000)]
    head = re.search(r"Mes\s+(ICEN.*?)\n", body) or re.search(r"Mes\s+(ICEN[^\n]*)", body)
    if not head:
        raise FormatChanged("informe ENFEN: la tabla de índices no tiene la fila de encabezado «Mes ICEN …»")
    columns = [c.lower() for c in re.findall(r"\b(ICEN|RONI|ONI)\b", head.group(1))]
    if not columns or columns[0] != "icen":
        raise FormatChanged(f"informe ENFEN: encabezado de índices inesperado «{_flat(head.group(1))[:80]}»")
    tmp_at = re.search(r"ICEN\s?tmp", body, re.I)
    parts = [(body[: tmp_at.start()] if tmp_at else body, 0, False)]
    if tmp_at:
        parts.append((body[tmp_at.end():], tmp_at.end(), True))
    official, provisional, problems = [], [], []
    for part, offset, is_tmp in parts:
        rows = list(_ROW_RE.finditer(part))
        for i, r in enumerate(rows):
            seg = part[r.end(): rows[i + 1].start() if i + 1 < len(rows) else len(part)]
            vals = [(-1 if sign else 1) * _num(v) for sign, v in _VAL_RE.findall(seg)]
            period = f"{2000 + int(r.group(2)):04d}-{_MON[r.group(1).lower()]:02d}"
            if len(vals) != len(columns):
                problems.append(f"fila {r.group(0)}: {len(vals)} valores para {len(columns)} columnas")
                continue
            row = {"period": period, **dict(zip(columns, vals)),
                   "evidence": {"quote": re.sub(r"(\s+(Mes|\d{1,3}))+$", "", _flat(r.group(0) + seg))[:160],
                                "page": doc.page(m.end() + offset + r.start())}}
            (provisional if is_tmp else official).append(row)
    if not official:
        raise FormatChanged("informe ENFEN: la tabla de índices no tiene filas legibles")
    return {"columns": columns, "official": official, "provisional": provisional, "problems": problems}


# ---------------------------------------------------------------------------
# Tablas de probabilidades
# ---------------------------------------------------------------------------
_CAT_RE = re.compile(r"\b(Fr[ií]a|C[aá]lida)\s+(muy\s+fuerte|extraordinari[oa]|fuerte|moderad[oa]|d[eé]bil)\b|\bNeutr[oa]\b",
                     re.I)
_SEASON_CAT_RE = re.compile(r"\b(La\s+Ni[ñn]a|El\s+Ni[ñn]o)\s+(muy\s+fuerte|extraordinari[oa]|fuerte|moderad[oa]|d[eé]bil)\b|\bNeutr[oa]\b",
                            re.I)
_MONTHS_RE = "|".join(sorted(MONTHS_ES, key=len, reverse=True))
_RANGE_RE = re.compile(rf"entre\s+({_MONTHS_RE})(?:\s+(?:de|del)\s+(\d{{4}}))?\s+y\s+({_MONTHS_RE})(?:\s+(?:de|del))?\s+(\d{{4}})",
                       re.I)


def _cat_code(m: re.Match) -> str:
    if not m.group(1):
        return "neutro"
    side = "fria" if _plain(m.group(1)).startswith("fria") else "calida"
    mag = _plain(re.sub(r"\s+", " ", m.group(2)))
    mag = {"muy fuerte": "muy_fuerte", "extraordinario": "extraordinaria", "extraordinaria": "extraordinaria",
           "moderado": "moderada", "moderada": "moderada"}.get(mag, mag)
    return f"{side}_{mag}"


def _season_code(m: re.Match) -> str:
    if not m.group(1):
        return "neutro"
    side = "calida" if "nino" in _plain(m.group(1)) else "fria"
    mag = _plain(re.sub(r"\s+", " ", m.group(2)))
    mag = {"muy fuerte": "muy_fuerte", "extraordinario": "extraordinaria", "moderado": "moderada"}.get(mag, mag)
    return f"{side}_{mag}"


def _region(title: str) -> Optional[str]:
    t = _flat(title)
    a, b = t.find("1+2"), t.find("3.4")
    if a < 0 and b < 0:
        return "nino34" if "central" in _plain(t) else "nino12" if "oriental" in _plain(t) else None
    return "nino12" if b < 0 or (0 <= a < b) else "nino34"


def _month_range(title: str) -> list[str]:
    m = _RANGE_RE.search(_flat(title))
    if not m:
        return []
    m1, y1, m2, y2 = MONTHS_ES[_plain(m.group(1))], m.group(2), MONTHS_ES[_plain(m.group(3))], int(m.group(4))
    y1 = int(y1) if y1 else (y2 if m1 <= m2 else y2 - 1)
    out, y, mo = [], y1, m1
    while (y, mo) <= (y2, m2) and len(out) < 24:
        out.append(f"{y:04d}-{mo:02d}")
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return out


def _table_body(doc: Paged, start: int) -> str:
    end = re.search(r"Tabla\s+\d+\.|Figura\s+\d+\.|\n\s*\d\.\d\.\s+Figuras", doc.text[start:])
    return doc.text[start: start + (end.start() if end else 3000)]


def parse_probability_tables(doc: Paged) -> tuple[list[dict], list[str]]:
    tables, problems = [], []
    for m in re.finditer(r"Tabla\s+\d+\.\s+Probabilidades\s+mensuales\s+estimadas", doc.text, re.I):
        title_end = re.search(r"\.\s*(?:\(|Fuente|\n)", doc.text[m.end(): m.end() + 600])
        title = doc.text[m.start(): m.end() + (title_end.end() if title_end else 300)]
        body = _table_body(doc, m.end())
        region, months = _region(title), _month_range(title)
        if not region or not months:
            problems.append(f"tabla de probabilidades sin región o meses legibles: «{_flat(title)[:120]}»")
            continue
        summer = bool(re.search(r"\bVERANO\b", body))
        cats = list(_CAT_RE.finditer(body))
        table: dict[str, Any] = {"region": region, "months": months, "categories": {}, "summer": None,
                                 "evidence": {"quote": re.split(r"\s*Fuente\b", _flat(title))[0].rstrip(" .")[:240],
                                              "page": doc.page(m.start())},
                                 "review": "revisar los valores" in _plain(_flat(title + body[:400]))}
        for i, c in enumerate(cats):
            seg = body[c.end(): cats[i + 1].start() if i + 1 < len(cats) else len(body)]
            seg = re.split(r"\[\[|\f", seg)[0]
            nums = [int(x) for x in re.findall(r"(?<![\d.,])(\d{1,3})(?![\d.,%])", seg)]
            code = _cat_code(c)
            want = len(months) + (1 if summer else 0)
            if len(nums) < want:
                problems.append(f"{region} {code}: {len(nums)} valores para {want} columnas")
                continue
            if code in table["categories"]:
                problems.append(f"{region} {code}: categoría repetida")
                continue
            table["categories"][code] = nums[: len(months)]
            if summer:
                table["summer"] = {**(table["summer"] or {}), code: nums[len(months)]}
        tables.append(table)
    return tables, problems


def parse_seasonal_tables(doc: Paged) -> list[dict]:
    out = []
    for m in re.finditer(r"Tabla\s+\d+\.\s+Probabilidades\s+estimadas\s+de\s+las\s+magnitudes", doc.text, re.I):
        body = _table_body(doc, m.end())
        title = body[:400]
        region = _region(title.split("Magnitud")[0])
        season = re.search(rf"({_MONTHS_RE})\s+(\d{{4}})\s*-\s*({_MONTHS_RE})\s+(\d{{4}})", _flat(body), re.I)
        cats = {}
        for c in _SEASON_CAT_RE.finditer(body):
            n = re.match(r"\s*(\d{1,3})\b", body[c.end():])
            if n:
                cats[_season_code(c)] = int(n.group(1))
        if region and cats:
            out.append({"region": region, "season": _flat(season.group(0)) if season else "",
                        "categories": cats, "evidence": {"quote": _flat(doc.text[m.start(): m.end() + 200])[:240],
                                                         "page": doc.page(m.start())}})
    return out


# ---------------------------------------------------------------------------
# Informe técnico completo
# ---------------------------------------------------------------------------
@dataclass
class Issue:
    severity: str  # warning | error
    code: str
    message: str


@dataclass
class Extraction:
    """Resultado de leer un informe: datos, de dónde salieron y qué no cuadró."""

    kind: str
    url: str
    data: dict
    method: str = "deterministic"
    issues: list[Issue] = field(default_factory=list)

    @property
    def publishable(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


def parse_informe(pages: list[str], url: str = "") -> Extraction:
    """Lee el informe técnico del ENFEN (texto por página)."""
    doc = Paged(pages)
    head = _flat(" ".join(pages[:2]))[:2000]
    nm = re.search(r"A[ÑN]O\s+\d+\s+N\s*[°º]\s*(\d{1,2})", head, re.I) or re.search(r"-n(\d{1,2})-", url)
    if not nm:
        raise FormatChanged("informe ENFEN: no se encontró el número («AÑO 12 N° 18»)")
    data: dict[str, Any] = {"number": int(nm.group(1)), "dataTo": _date_es(head)}
    issues: list[Issue] = []
    data["indices"] = parse_index_table(doc)
    for p in data["indices"].pop("problems"):
        issues.append(Issue("warning", "informe-index-row", p))
    data["probabilities"], problems = parse_probability_tables(doc)
    for p in problems:
        issues.append(Issue("warning", "informe-probability-row", p))
    data["seasonal"] = parse_seasonal_tables(doc)
    for e in check(SCHEMAS["enfen-informe"], data):
        issues.append(Issue("error", "informe-schema", e))
    return Extraction("enfen-informe", url, data, issues=issues)


def validate_informe(ext: Extraction, *, icen_official: Optional[list[dict]] = None,
                     today: Optional[date] = None, communique: Optional[dict] = None) -> Extraction:
    """Reglas de plausibilidad. Un error impide publicar esa parte; una advertencia se publica y se anota."""
    d, add = ext.data, ext.issues.append
    ind = d.get("indices") or {}
    rows = (ind.get("official") or []) + (ind.get("provisional") or [])
    periods = [r["period"] for r in rows]
    for a, b in zip(periods, periods[1:]):
        ya, ma = map(int, a.split("-"))
        if (ya * 12 + ma) + 1 != (lambda y, m: y * 12 + m)(*map(int, b.split("-"))):
            add(Issue("error", "informe-index-months", f"meses no consecutivos en la tabla de índices: {a} → {b}"))
            break
    off, tmp = ind.get("official") or [], ind.get("provisional") or []
    if not tmp:
        add(Issue("warning", "informe-no-provisional", "la tabla de índices no trae el ICEN temporal"))
    elif off and abs(tmp[0]["icen"] - off[-1]["icen"]) > 1.5:
        add(Issue("error", "informe-icen-jump",
                  f"ICEN temporal {tmp[0]['period']} = {tmp[0]['icen']} se aleja más de 1,5 °C del último oficial "
                  f"({off[-1]['period']} = {off[-1]['icen']}): queda para revisión"))
    if icen_official:
        igp = {p["period"]: p["value"] for p in icen_official if p.get("value") is not None}
        diffs = [(r["period"], r["icen"], igp[r["period"]]) for r in off if r["period"] in igp
                 and abs(r["icen"] - igp[r["period"]]) > 0.05]
        if diffs:
            add(Issue("warning", "informe-icen-mismatch", "el ICEN del informe difiere del archivo del IGP en "
                      + ", ".join(f"{p} ({a:+.2f} frente a {b:+.2f})" for p, a, b in diffs[:4])))
        if tmp and tmp[0]["period"] in igp:
            add(Issue("warning", "informe-provisional-superseded",
                      f"el IGP ya publicó el ICEN oficial de {tmp[0]['period']}: el temporal no se usa"))
    for t in d.get("probabilities") or []:
        bad = []
        for i, mth in enumerate(t["months"]):
            col = [v[i] for v in t["categories"].values() if i < len(v)]
            if col and not 98 <= sum(col) <= 102:
                bad.append(f"{mth}: {sum(col)} %")
        if len(t["categories"]) < 7:
            bad.append(f"solo {len(t['categories'])} categorías")
        if bad:
            add(Issue("error", "informe-probability-sum",
                      f"probabilidades de {t['region']} que no suman 100: " + "; ".join(bad[:4])))
            t["invalid"] = True
        if t.get("summer") and not 98 <= sum(t["summer"].values()) <= 102:
            t["summer"] = None
    for s in d.get("seasonal") or []:
        if not 98 <= sum(s["categories"].values()) <= 102:
            s["invalid"] = True
    if today and d.get("dataTo"):
        age = (today - date.fromisoformat(d["dataTo"])).days
        if age > 45:
            add(Issue("warning", "informe-old", f"el informe técnico más reciente es del {d['dataTo']} ({age} días)"))
    if communique and communique.get("number") and d.get("number") and communique["number"] != d["number"]:
        add(Issue("warning", "informe-number", f"el informe N° {d['number']} no corresponde al comunicado "
                  f"N° {communique['number']}"))
    return ext


# ---------------------------------------------------------------------------
# Perspectiva del comunicado
# ---------------------------------------------------------------------------
_MAG_RE = r"(extraordinari[oa]|muy\s+fuerte|fuerte|moderad[oa]|d[eé]bil)"
_OUTLOOK_RE = re.compile(
    rf"(?P<region>Ni[ñn]o\s*(?:1\s*\+\s*2|3[.,]4))[^.]{{0,260}}?magnitud\s+(?:de\s+)?{_MAG_RE}\d?"
    rf"(?P<rest>[^.]{{0,240}})", re.I)


def _mag(s: str) -> str:
    m = _plain(re.sub(r"\s+", " ", s))
    return {"extraordinario": "extraordinaria", "moderado": "moderada", "muy fuerte": "muy_fuerte"}.get(m, m)


def communique_outlook(text: str) -> list[dict]:
    """Magnitud esperada por región y hasta cuándo, con la oración de donde sale.

    «Frente a la costa peruana (región Niño 1+2) es más probable que calentamiento del mar (El Niño costero) se
    mantenga con una magnitud de extraordinaria hasta enero de 2027 (Figura 2), para luego disminuir a fuerte»."""
    flat = _flat(text)
    out: dict[str, dict] = {}
    for m in _OUTLOOK_RE.finditer(flat):
        region = "nino12" if "1" in re.sub(r"\s", "", m.group("region"))[4:6] or "+" in m.group("region") else "nino34"
        if region in out:
            continue
        rest = m.group("rest")
        until = None
        um = re.search(rf"hasta\s+(?:inicios\s+de(?:l)?\s+|fines\s+de(?:l)?\s+)?({_MONTHS_RE})\s*(?:de(?:l)?\s+)?(\d{{4}})", rest, re.I)
        if um:
            until = f"{int(um.group(2)):04d}-{MONTHS_ES[_plain(um.group(1))]:02d}"
        then = re.search(rf"(?:disminuir|reducir|bajar)\w*\s+a\s+{_MAG_RE}", rest, re.I)
        start = flat.rfind(". ", 0, m.start()) + 2 if flat.rfind(". ", 0, m.start()) >= 0 else m.start()
        sentence = flat[(flat.rfind(". ", 0, m.start()) + 2) if flat.rfind(". ", 0, m.start()) >= 0 else 0: m.end()]
        phase = "fria" if re.search(r"\bfr[ií]a|La\s+Ni[ñn]a", sentence, re.I) else "calida"
        out[region] = {"region": region, "phase": phase, "magnitude": _mag(m.group(2)), "until": until,
                       "then": _mag(then.group(1)) if then else None,
                       # Sin las llamadas de nota pegadas a las palabras («extraordinaria2»).
                       "quote": re.sub(r"(?<=[a-záéíóúñ])\d{1,2}(?=[\s(.,;]|$)", "", flat[start: m.end() + 1].strip())[:420]}
    res = list(out.values())
    if check(SCHEMAS["enfen-perspectiva"], res):
        return []
    return res


# ---------------------------------------------------------------------------
# Respaldo con un modelo de lenguaje (opcional, sin proveedor fijo)
# ---------------------------------------------------------------------------
LLM_URL_ENV = "ENSO_LLM_EXTRACT_URL"
LLM_TOKEN_ENV = "ENSO_LLM_EXTRACT_TOKEN"


def llm_extract(client, kind: str, text: str, *, url: str, published: Optional[str] = None,
                timeout: float = 120.0) -> Optional[dict]:
    """Pide la extracción a un servicio externo (p. ej. un flujo de n8n con un nodo AI Agent) y la valida.

    El servicio recibe ``{"kind", "schema", "text", "url", "published"}`` y devuelve ``{"data": …,
    "model": …, "evidence": {ruta: cita}}``. Solo se llama si ``ENSO_LLM_EXTRACT_URL`` está definida. El resultado nunca se publica
    directamente: vuelve como propuesta para revisión, con los errores de esquema que tenga."""
    endpoint = os.environ.get(LLM_URL_ENV)
    if not endpoint or client is None:
        return None
    headers = {"content-type": "application/json"}
    if os.environ.get(LLM_TOKEN_ENV):
        headers["authorization"] = f"Bearer {os.environ[LLM_TOKEN_ENV]}"
    body = {"kind": kind, "schema": SCHEMAS[kind], "text": text[:120_000], "url": url, "published": published}
    try:
        r = client.post(endpoint, content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                        headers=headers, timeout=timeout)
        r.raise_for_status()
        reply = r.json()
    except Exception as exc:  # noqa: BLE001 — el respaldo nunca detiene la corrida
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    data = reply.get("data") if isinstance(reply, dict) else None
    return {"ok": data is not None, "data": data, "model": (reply or {}).get("model"),
            "evidence": (reply or {}).get("evidence") if isinstance((reply or {}).get("evidence"), dict) else None,
            "schemaErrors": check(SCHEMAS[kind], data) if data is not None else ["sin «data»"]}


def compare(det: Optional[dict], llm: Optional[dict], keys: list[str]) -> list[str]:
    """Campos en que la lectura determinista y la del modelo no coinciden."""
    if not det or not llm:
        return []
    return [k for k in keys if det.get(k) != llm.get(k)]


# ---------------------------------------------------------------------------
# Publicación: lo que llega al sitio
# ---------------------------------------------------------------------------
def informe_summary(ext: Extraction) -> dict:
    """Lo que el sitio muestra del informe: el ICEN temporal y las probabilidades válidas, con su procedencia."""
    d = ext.data
    ind = d.get("indices") or {}
    blocked = {i.code for i in ext.issues if i.severity == "error"}
    tmp = None
    if ind.get("provisional") and not blocked & {"informe-icen-jump", "informe-index-months", "informe-schema"}:
        if not any(i.code == "informe-provisional-superseded" for i in ext.issues):
            tmp = ind["provisional"][0]
    probs = [t for t in d.get("probabilities") or [] if not t.get("invalid")]
    return {
        "number": d.get("number"), "dataTo": d.get("dataTo"), "url": ext.url, "method": ext.method,
        "icenProvisional": tmp, "lastOfficial": (ind.get("official") or [None])[-1],
        "probabilities": probs if "informe-schema" not in blocked else [],
        "seasonal": [s for s in d.get("seasonal") or [] if not s.get("invalid")],
        "issues": [{"severity": i.severity, "code": i.code, "message": i.message} for i in ext.issues],
    }


# ---------------------------------------------------------------------------
# Adquisición dentro de la corrida diaria
# ---------------------------------------------------------------------------
def acquire_informe(latest: Optional[dict], fetcher, previous_informe: Optional[dict], log, today: date,
                    icen_points: Optional[list[dict]] = None) -> Optional[dict]:
    """Informe técnico del comunicado vigente: se baja una vez por comunicado (pesa 10–20 MB) y se lee.

    Devuelve el resumen publicable (``informe_summary``) con ``retrievedAt`` y ``channel``. Si no se puede
    bajar o leer, o lo leído no pasa las reglas, se conserva el resumen anterior marcado ``carried`` y queda la
    incidencia; nunca se publica un valor que no pasó la validación."""
    from datetime import datetime, timezone

    from .fetch import FetchError

    if not latest:
        return previous_informe
    number = latest.get("number")
    if previous_informe and previous_informe.get("number") == number and not previous_informe.get("carried"):
        return previous_informe  # ya leído en una corrida anterior

    def keep(reason: str, severity: str = "error", stage: str = "parse") -> Optional[dict]:
        log.add(severity, "enfen-informe", stage, "informe-unread", reason[:1500])
        if previous_informe:
            return {**previous_informe, "carried": True,
                    "carriedReason": f"No se pudo leer el informe del comunicado {latest.get('id')}."}
        return None

    url = latest.get("informe_url")
    if not url:
        try:
            r = fetcher.get([INFORMES_PAGE], archive=False, accept=("html",))
            url = informe_links(r.text).get(number)
        except FetchError as exc:
            return keep(f"No se pudo bajar el listado de informes técnicos: {exc}", stage="fetch")
        if not url:
            return keep(f"El comunicado {latest.get('id')} no enlaza su informe técnico y el listado aún no lo trae.",
                        "warning", "fetch")
    try:
        r = fetcher.get([url], archive=False, accept=("pdf", "octet-stream", "html"))
        if r.body[:5] != b"%PDF-":
            m = re.search(r"href=[\"']([^\"']*wpdmdl=\d+[^\"']*)[\"']", r.text)
            if not m:
                return keep(f"La descarga del informe técnico no es un PDF ({url}).")
            r = fetcher.get([m.group(1).replace("&#038;", "&").replace("&amp;", "&")], archive=False,
                            accept=("pdf", "octet-stream"))
            if r.body[:5] != b"%PDF-":
                return keep(f"La descarga del informe técnico no es un PDF ({url}).")
        pages = pdf_pages(r.body)
    except FetchError as exc:
        return keep(f"No se pudo bajar el informe técnico {url}: {exc}", stage="fetch")
    except Exception as exc:  # noqa: BLE001 — un PDF dañado no detiene la corrida
        return keep(f"No se pudo leer el PDF del informe técnico {url}: {type(exc).__name__}: {exc}")
    try:
        ext = parse_informe(pages, url)
    except FormatChanged as exc:
        proposal = llm_extract(getattr(fetcher, "client", None), "enfen-informe", "\n\f".join(pages), url=url)
        res = keep(f"Cambió el formato del informe técnico ({exc}). Se conserva el último dato leído"
                   + ("; la lectura con el modelo de lenguaje queda para revisión." if proposal else "."))
        if res is not None and proposal:
            res["review"] = {"proposal": proposal, "reason": str(exc)[:300]}
        return res
    validate_informe(ext, icen_official=icen_points, today=today, communique=latest)
    for i in ext.issues:
        log.add(i.severity, "enfen-informe", "validate", i.code, i.message)
    summary = informe_summary(ext)
    summary.update({"retrievedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "channel": r.channel,
                    "communique": latest.get("id"), "pages": len(pages)})
    if not summary["icenProvisional"] and not summary["probabilities"] and previous_informe:
        return keep("El informe técnico se leyó pero ninguno de sus valores pasó la validación.")
    return summary
