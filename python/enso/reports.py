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
coherencia con el ICEN oficial del IGP. Lo que no las pasa no se publica y queda una incidencia; si no se
pudo leer nada, se conserva el informe anterior marcado como arrastrado.

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

from .feeds import MONTHS_ES, FormatChanged, imarpe_repo
from .feeds.peru import DATE_ES, _date_es, download_button

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
#: Posición de la termoclina costera (isoterma de 15 °C frente a Paita y Chicama) frente a su climatología, tal
#: como la describe el texto del informe: más somera (por encima), normal o más profunda (por debajo).
THERMOCLINE_STATES = ["somera", "somera_normal", "normal", "normal_profunda", "profunda"]
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
    "region": {"type": "string", "enum": REGIONS}, "season": {"type": ["string", "null"], "minLength": 3},
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
        "seasonal": {"type": "array", "items": _SEASON, "maxItems": 2},
        "thermocline": {"type": ["object", "null"], "properties": {
            "state": {"type": ["string", "null"], "enum": THERMOCLINE_STATES + [None]},
            "evidence": {"type": ["object", "null"], "properties": _EVIDENCE["properties"]},
            "subsurface": {"type": ["object", "null"], "required": ["anomaly", "quote"], "properties": {
                "anomaly": {"type": "number", "minimum": -12, "maximum": 14},
                "layer": {"type": ["string", "null"]}, "isotherms": {"type": ["string", "null"],
                                                                     "enum": ["profundizacion", "ascenso", None]},
                "quote": {"type": "string", "minLength": 10}, "page": {"type": ["integer", "null"], "minimum": 1}}}}}}},
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
#: Réplica de la Dirección de Hidrografía y Navegación: responde fuera del Perú, como la de los comunicados.
DHN_INFORMES_PAGE = "https://www.dhn.mil.pe/portal/informe-tecnico-enfen"
DHN_INFORME = "https://www.dhn.mil.pe/Archivos/oceanografia/enfen/informe-tecnico/{n:02d}-{year}.pdf"
_INFORME_HREF = re.compile(r"href=[\"'](https?://[^\"']*/download/informe-tecnico-enfen-ano-(\d+)-n-?(\d{1,2})-[^\"']*)[\"']",
                           re.I)
_SLUG = re.compile(r"informe-tecnico-enfen-ano-(\d+)-n-?(\d{1,2})(?:-al-(\d{1,2})-de-([a-z]+)-de-?(\d{4}))?", re.I)
#: Días entre el corte de datos del informe y la emisión de su comunicado: 0 a 5 en 2024–2026; los comunicados
#: salen cada dos semanas, así que el informe del comunicado anterior queda fuera.
INFORME_LAG_DAYS = 10
_DHN_HREF = re.compile(r"/informe-tecnico/(\d{1,2})-(\d{4})\.pdf", re.I)


def _dhn_ref(url: str) -> Optional[dict]:
    """Año y número de un PDF de la réplica de la DHN (``informe-tecnico/18-2026.pdf``)."""
    m = re.search(r"/informe-tecnico/(\d{1,2})-(\d{4})\.pdf$", url or "")
    return {"year": int(m.group(2)), "n": int(m.group(1))} if m else None


def informe_ref(url: str) -> Optional[dict]:
    """Año, número y fecha de corte de un informe a partir de su URL de descarga en el portal del ENFEN.

    El «AÑO» del informe cuenta desde 2014 (AÑO 12 = 2026)."""
    m = _SLUG.search(url or "")
    if not m:
        return None
    ref = {"url": url, "year": 2014 + int(m.group(1)), "n": int(m.group(2)), "dataTo": None}
    if m.group(3) and _plain(m.group(4)) in MONTHS_ES:
        try:
            ref["dataTo"] = date(int(m.group(5)), MONTHS_ES[_plain(m.group(4))], int(m.group(3))).isoformat()
        except ValueError:
            pass
    return ref


def informe_entries(html_text: str) -> list[dict]:
    """Informes del listado del portal del ENFEN (``informe_ref`` de cada enlace), sin repetir URL."""
    out, seen = [], set()
    for m in _INFORME_HREF.finditer(html_text):
        url = re.sub(r"[&?](refresh|ind)=[^&]*", "", m.group(1).replace("&#038;", "&").replace("&amp;", "&"))
        if url not in seen and (ref := informe_ref(url)):
            seen.add(url)
            out.append(ref)
    return out


def dhn_entries(html_text: str) -> list[dict]:
    """Informes de la réplica de la DHN (``NN-AAAA.pdf``), sin fecha de corte."""
    found = {(int(y), int(n)) for n, y in _DHN_HREF.findall(html_text)}
    return [{"url": DHN_INFORME.format(n=n, year=y), "year": y, "n": n, "dataTo": None} for y, n in sorted(found)]


def pick_informe(entries: list[dict], communique: dict) -> Optional[dict]:
    """El informe técnico de un comunicado. El número no sirve (2025: comunicado 05 → informe N° 06; 2022 va
    uno atrás), así que se elige por fecha: el de corte más reciente hasta tres días después de la emisión y
    no más de ``INFORME_LAG_DAYS`` antes. Sin fechas (réplica de la DHN), el de número más alto del año del comunicado; la
    validación descarta después uno de otro periodo."""
    issued = communique.get("issued")
    if issued and any(e.get("dataTo") for e in entries):
        d0 = date.fromisoformat(issued)
        fit = [e for e in entries if e.get("dataTo") and -3 <= (d0 - date.fromisoformat(e["dataTo"])).days <= INFORME_LAG_DAYS]
        return max(fit, key=lambda e: e["dataTo"]) if fit else None
    year = communique.get("year") or (int(issued[:4]) if issued else None)
    same = [e for e in entries if e["year"] == year]
    return max(same, key=lambda e: e["n"]) if same else None


def mirrors(url: str) -> list[str]:
    """URL del informe y su copia en la réplica de la DHN (mismo número y año)."""
    ref = informe_ref(url)
    out = [url]
    if ref and "dhn.mil.pe" not in url:
        out.append(DHN_INFORME.format(n=ref["n"], year=ref["year"]))
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
_RANGE_RE = re.compile(rf"entre\s+({_MONTHS_RE})(?:(?:\s+(?:de|del))?\s+(\d{{4}}))?\s+(?:y|a|hasta)\s+({_MONTHS_RE})(?:\s+(?:de|del))?\s+(\d{{4}})",
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
        season = (re.search(rf"({_MONTHS_RE})(?:\s+del?)?\s+(\d{{4}})\s*(?:[-–—]|\s(?:a|al|hasta)\s)\s*({_MONTHS_RE})"
                            rf"(?:\s+del?)?\s+(\d{{4}})", _flat(body), re.I)
                  or re.search(r"verano\s+(?:del?\s+)?\d{4}(?:\s*[-–—/]\s*\d{2,4})?", _flat(title), re.I))
        cats = {}
        for c in _SEASON_CAT_RE.finditer(body):
            n = re.match(r"\s*(\d{1,3})\b", body[c.end():])
            if n:
                cats[_season_code(c)] = int(n.group(1))
        if region and cats:
            out.append({"region": region, "season": _flat(season.group(0)) if season else None,
                        "categories": cats, "evidence": {"quote": _flat(doc.text[m.start(): m.end() + 200])[:240],
                                                         "page": doc.page(m.start())}})
    return out


# ---------------------------------------------------------------------------
# Termoclina costera y temperatura subsuperficial (texto de «Condiciones oceánicas … locales»)
# ---------------------------------------------------------------------------
#: Frases que no describen lo observado: pronósticos, modelos y perspectivas.
_NOT_OBSERVED = re.compile(r"pron[oó]stico|se esper|se prev[eé]|se proyecta|continuar[ií]a|podr[ií]a|"
                           r"perspectiva|modelo|simula|se mantendr[ií]a|ser[ií]a\b", re.I)
#: Lugares que no son la costa peruana (el informe también describe Galápagos y el Pacífico ecuatorial).
_NOT_COAST = re.compile(r"Gal[aá]pagos|ecuatorial|occidental|Ni[nñ]o\s*3|Rossby", re.I)
_COAST = re.compile(r"Paita|Chicama|Talara|Tumbes|Chimbote|Callao|Pisco|Ilo|San Juan|costa|litoral|mn\b|millas", re.I)
#: (estado, patrón): el primero que aparece en la frase gana; las posiciones explícitas van antes que las tendencias.
_STATE_RULES = [
    ("normal_profunda", r"(rango\s+)?normal\s+a\s+ligeramente\s+m[aá]s\s+profund"),
    ("somera_normal", r"(rango\s+)?normal\s+a\s+ligeramente\s+m[aá]s\s+somer|ligeramente\s+por\s+encima\s+de\s+(lo\s+normal|su)"),
    ("somera", r"por\s+encima\s+de\s+(su|la)\s+(posici[oó]n\s+)?climatol|m[aá]s\s+somer[ao]\s+(de|que)\s+lo\s+normal|"
               r"menor\s+profundidad\s+(de|que)\s+lo\s+normal"),
    ("profunda", r"por\s+debajo\s+(de\s+)?(su|la)\s+(posici[oó]n\s+)?climatol|m[aá]s\s+profund[ao]\s+(de|que)\s+lo\s+normal|"
                 r"mayor\s+profundidad\s+(de|que)\s+lo\s+normal"),
    ("normal", r"(dentro\s+de(l)?\s+(su\s+)?rango\s+(normal|climatol)|posici[oó]n\s+normal|en\s+su\s+posici[oó]n\s+climatol)"),
]
_ANOM = re.compile(r"hasta\s+([+\-−–]?\s?\d+(?:,\d+)?)\s*°\s*C", re.I)
_LAYER = re.compile(r"(?:en\s+los\s+primeros|sobre\s+los|por\s+encima\s+de\s+los|por\s+debajo\s+de\s+los|entre\s+(?:los\s+)?\d+\s+y|"
                    r"alrededor\s+de\s+los|cercanas?\s+a)\s*\d+(?:\s*y\s*\d+)?\s*m\b|capa\s+superior\s*\(0\s*[–-]\s*\d+\s*m\)", re.I)


def _sentences(doc: Paged, start: int = 0, end: Optional[int] = None):
    """Frases del texto (posición, frase aplanada). Un punto seguido de mayúscula corta la frase; uno decimal no."""
    text = doc.text[start:end]
    pos = 0
    for m in re.finditer(r"(?<!\d)\.(?=\s+[A-ZÁÉÍÓÚÑ\d(])|\n\f", text):
        yield start + pos, _flat(text[pos:m.end()])
        pos = m.end()
    if pos < len(text):
        yield start + pos, _flat(text[pos:])


def _local_section(doc: Paged) -> tuple[int, int]:
    """Desde «Condiciones oceánicas y atmosféricas locales» (o la primera mención de Paita) hasta las
    perspectivas; si no se reconocen, todo el texto antes de las figuras."""
    t = doc.text
    a = re.search(r"Condiciones\s+oce[aá]nicas\s+y\s+atmosf[eé]ricas\s+locales", t, re.I) or re.search(r"Paita", t)
    start = a.start() if a else 0
    b = re.search(r"\n\s*(Perspectivas|PERSPECTIVAS|Anexo|ANEXO|Figura\s+1\b)", t[start:])
    return start, start + b.start() if b else len(t)


def parse_thermocline(doc: Paged) -> Optional[dict]:
    """Termoclina costera frente a su climatología y la anomalía subsuperficial más intensa observada.

    El informe da la profundidad de la isoterma de 15 °C (indicadora de la termoclina) solo en sus figuras; en el
    texto la describe por comparación con su climatología («se mantuvo por encima de su posición climatológica
    dentro de las 100 millas», «en el rango normal a ligeramente más profunda»). Se toma esa frase tal cual, sin
    convertirla en metros. Solo cuentan frases de lo observado frente a la costa peruana, no pronósticos."""
    start, end = _local_section(doc)
    state = evidence = None
    sub = None
    for pos, sent in _sentences(doc, start, end):
        if _NOT_OBSERVED.search(sent) or _NOT_COAST.search(sent):
            continue
        low = _plain(sent)
        # La isoterma de 15 °C solo se usa frente a la costa; una frase sobre la oxiclina que menciona la termoclina
        # («A diferencia de la termoclina, la oxiclina …») describe la oxiclina.
        if (state is None and "oxiclina" not in low
                and ("isoterma de 15" in low or ("termoclina" in low and _COAST.search(sent)))):
            for code, pat in _STATE_RULES:
                if re.search(pat, sent, re.I):
                    state, evidence = code, {"quote": sent[:600], "page": doc.page(pos)}
                    break
        subsurface = ("subsuperficial" in low or "columna de agua" in low or "isotermas" in low
                      or ("anomal" in low and _LAYER.search(sent)))
        if subsurface and _COAST.search(sent):
            vals = []
            for m in _ANOM.finditer(sent):
                try:
                    vals.append((_num(m.group(1)), m))
                except ValueError:
                    continue
            if not vals:
                continue
            v, m = max(vals, key=lambda x: abs(x[0]))
            if sub is not None and abs(v) <= abs(sub["anomaly"]):
                continue
            after = _LAYER.search(sent, m.end()) or _LAYER.search(sent)
            iso = ("profundizacion" if re.search(r"profundiz\w*\s+(de\s+)?las\s+isotermas", sent, re.I) else
                   "ascenso" if re.search(r"(ascenso|somerizaci[oó]n|superficializaci[oó]n)\s+de\s+las\s+isotermas", sent, re.I)
                   else None)
            sub = {"anomaly": v, "layer": _flat(after.group(0)) if after else None, "isotherms": iso,
                   "quote": sent[:600], "page": doc.page(pos)}
    if state is None and sub is None:
        return None
    return {"state": state, "evidence": evidence, "subsurface": sub}


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
    data["thermocline"] = parse_thermocline(doc)
    for e in check(SCHEMAS["enfen-informe"], data):
        # Un error de esquema bloquea solo la parte donde está: una tabla estacional mal leída no retiene el
        # ICEN temporal ni las probabilidades mensuales.
        part = re.match(r"\$\.(probabilities|seasonal)\[(\d+)\]", e)
        if e.startswith("$.thermocline"):
            data["thermocline"] = None
            issues.append(Issue("error", "informe-schema-thermocline", e))
        elif part:
            data[part.group(1)][int(part.group(2))]["invalid"] = True
            issues.append(Issue("error", f"informe-schema-{part.group(1)}", e))
        else:
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
    if d.get("dataTo"):
        ref = _mindex(d["dataTo"][:7])
        if tmp and not 0 <= ref - _mindex(tmp[0]["period"]) <= 2:
            add(Issue("error", "informe-period-provisional", f"el ICEN temporal es de {tmp[0]['period']} y el informe tiene "
                      f"datos al {d['dataTo']}: el periodo no encaja"))
        for t in d.get("probabilities") or []:
            if not -1 <= _mindex(t["months"][0]) - ref <= 3:
                add(Issue("error", "informe-period-probabilities", f"las probabilidades de {t['region']} empiezan en "
                          f"{t['months'][0]} y el informe tiene datos al {d['dataTo']}: el periodo no encaja"))
                t["invalid"] = True
        # El número del informe no sigue al del comunicado (2025: comunicado 05 → informe N° 06): se compara la
        # fecha. Un informe técnico sale con su comunicado, con datos de los días anteriores.
        issued = (communique or {}).get("issued")
        if issued:
            lag = (date.fromisoformat(issued) - date.fromisoformat(d["dataTo"])).days
            if not -3 <= lag <= INFORME_LAG_DAYS:
                add(Issue("error", "informe-other-communique",
                          f"el informe N° {d.get('number')} tiene datos al {d['dataTo']} y el comunicado "
                          f"{communique.get('id')} es del {issued}: no es su informe técnico"))
    return ext


def _mindex(period: str) -> int:
    y, m = map(int, period[:7].split("-"))
    return y * 12 + m


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


def _phase(clause: str, status: Optional[str], before: str = "") -> str:
    """Fase de la perspectiva según el sujeto de la oración (entre la región y «magnitud» o, si ahí no hay, justo
    antes de la región: «La Niña (región Niño 3.4) se mantendría…»), no según cualquier mención de La Niña en el
    texto: el nombre del sistema de alerta («… El Niño costero y La Niña costera») y las transiciones («para
    luego … condiciones frías») no cuentan. Sin sujeto, decide el estado de alerta."""
    for part in (clause, before):
        got = _subject_phase(part)
        if got:
            return got
    return "fria" if "la nina" in _plain(status or "") else "calida"


def _subject_phase(clause: str) -> Optional[str]:
    c = _plain(clause)
    cold = re.search(r"la nina|\bfri[ao]s?\b|enfriamiento|anomalias negativas", c)
    warm = re.search(r"el nino|\bcalid[ao]s?\b|calentamiento|anomalias positivas", c)
    if cold and not warm:
        return "fria"
    if warm and not cold:
        return "calida"
    if cold and warm:
        return "fria" if cold.start() > warm.start() else "calida"  # el sujeto más cercano a «magnitud»
    return None


def communique_outlook(text: str, status: Optional[str] = None) -> list[dict]:
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
        dot = flat.rfind(". ", 0, m.start())
        start = dot + 2 if dot >= 0 else 0  # desde el principio de la oración (o del texto)
        clause = flat[m.start(): m.start(2)]
        # Lo que va antes de la región en la misma oración, desde la última coma o «mientras que» (que separa la
        # otra región): ahí puede estar el sujeto.
        before = flat[max(start, m.start() - 120): m.start()]
        before = re.split(r"[,;:]|mientras\s+que", before)[-1]
        phase = _phase(clause, status, before)
        out[region] = {"region": region, "phase": phase, "magnitude": _mag(m.group(2)), "until": until,
                       "then": _mag(then.group(1)) if then else None,
                       # Sin las llamadas de nota pegadas a las palabras («extraordinaria2»).
                       "quote": re.sub(r"(?<=[a-záéíóúñ])\d{1,2}(?=[\s(.,;]|$)", "", flat[start: m.end() + 1].strip())[:420]}
    res = list(out.values())
    if check(SCHEMAS["enfen-perspectiva"], res):
        return []
    return res


_MAG_WORDING_RE = re.compile(
    r"\b(?:magnitud|categor[ií]a|evento|condiciones\s+(?:c[aá]lidas|fr[ií]as))\b\W+(?:\w+\W+){0,3}?"
    r"(?:extraordinari|muy\s+fuerte|fuerte|moderad|d[eé]bil)", re.I)
_REGION_RE = re.compile(r"Ni[ñn]o\s*(1\s*\+\s*2|3[.,]4)", re.I)


def outlook_unread(text: str, outlook: list[dict]) -> list[str]:
    """Regiones de las que el comunicado habla con una magnitud esperada y que ``communique_outlook`` no leyó.

    Cada oración con una magnitud («magnitud fuerte», «categoría extraordinaria», «evento muy fuerte»,
    «condiciones cálidas moderadas») cuenta para las regiones que nombra; si no nombra ninguna, cuenta como
    «general» y solo falta si no se leyó ninguna región. Así una región reformulada no pasa sin aviso."""
    read = {o["region"] for o in outlook or []}
    want: set[str] = set()
    for sentence in re.split(r"(?<=\.)\s+", _flat(text)):
        if not _MAG_WORDING_RE.search(sentence):
            continue
        regions = {"nino12" if "+" in m.group(1) else "nino34" for m in _REGION_RE.finditer(sentence)}
        want |= regions or {"general"}
    missing = sorted(want - read - {"general"})
    if "general" in want and not read and not missing:
        missing = ["general"]
    return missing


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
        # Nunca el texto de la excepción: el de httpx lleva la URL del webhook, que es secreta y esto se publica.
        return {"ok": False, "transport": True, "error": _llm_error(exc)}
    reply = reply if isinstance(reply, dict) else {}
    data = reply.get("data")
    return {"ok": data is not None, "data": data, "model": reply.get("model"),
            "evidence": reply.get("evidence") if isinstance(reply.get("evidence"), dict) else None,
            "schemaErrors": check(SCHEMAS[kind], data) if data is not None else ["sin «data»"]}


def _llm_error(exc: Exception) -> str:
    """Motivo publicable de una falla del servicio: tipo y código HTTP, sin URL ni texto de la respuesta."""
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        return f"el servicio respondió HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "el servicio no respondió a tiempo"
    if isinstance(exc, httpx.TransportError):
        return "no se pudo conectar con el servicio"
    if isinstance(exc, ValueError):
        return "el servicio no respondió JSON"
    return f"falla del servicio ({type(exc).__name__})"


def llm_unavailable(log, proposal: Optional[dict]) -> None:
    """Incidencia propia si el extractor con modelo de lenguaje no respondió (servicio caído, token vencido):
    sin ella la falla se confunde con «no pudo leer el documento»."""
    if proposal and not proposal.get("ok") and proposal.get("transport"):
        log.add("warning", "llm-extract", "fetch", "llm-extract-unavailable",
                f"El extractor con modelo de lenguaje no respondió: {proposal.get('error')}. Revisar el flujo de n8n y "
                "los secretos ENSO_LLM_EXTRACT_URL y ENSO_LLM_EXTRACT_TOKEN.")


def reusable_review(prior: Optional[dict], url: str) -> Optional[dict]:
    """La propuesta guardada para ese mismo PDF, si sirve: una falla de transporte (503, plazo) se reintenta en la
    corrida siguiente; una respuesta del modelo (válida o con errores de esquema) no se vuelve a pedir."""
    if not prior or prior.get("url") != url:
        return None
    return None if (prior.get("proposal") or {}).get("transport") else prior


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
    if ind.get("provisional") and not blocked & {"informe-icen-jump", "informe-index-months", "informe-schema",
                                                  "informe-period-provisional", "informe-other-communique"}:
        if not any(i.code == "informe-provisional-superseded" for i in ext.issues):
            tmp = ind["provisional"][0]
    probs = [t for t in d.get("probabilities") or [] if not t.get("invalid")]
    return {
        "number": d.get("number"), "dataTo": d.get("dataTo"), "url": ext.url, "method": ext.method,
        "icenProvisional": tmp, "lastOfficial": (ind.get("official") or [None])[-1],
        "probabilities": probs if not blocked & {"informe-schema", "informe-other-communique"} else [],
        "seasonal": [s for s in d.get("seasonal") or [] if not s.get("invalid")],
        "thermocline": d.get("thermocline") if not blocked & {"informe-schema-thermocline",
                                                               "informe-other-communique"} else None,
        "issues": [{"severity": i.severity, "code": i.code, "message": i.message} for i in ext.issues],
    }


# ---------------------------------------------------------------------------
# Adquisición dentro de la corrida diaria
# ---------------------------------------------------------------------------
def _informe_pdf(fetcher, url: str, FetchError, archive_prefix, problems: Optional[list] = None):
    """El PDF del informe o ``None``. Solo vale un cuerpo que empiece con ``%PDF-``: una página de verificación
    humana (la DHN la sirve a GitHub Actions y a n8n) o de error no se lee y no corta la búsqueda.

    Orden (el documentado): el portal y la réplica de la DHN con las copias de los recolectores; el repositorio
    del IMARPE (oficial, alcanzable desde Actions); y solo al final el Internet Archive. ``problems`` recibe la
    causa si el repositorio falla."""
    from .observatory import archived_copy

    def pdf(r):
        return r if r is not None and r.body[:5] == b"%PDF-" else None

    accept = ("pdf", "octet-stream")
    try:
        got = pdf(fetcher.get(mirrors(url), archive=False, accept=accept))
        if got:
            return got
    except FetchError:
        pass
    link = None
    if "/download/" in url:
        # La URL puede ser la página de descarga del portal (HTML) que enlaza el PDF.
        try:
            page = fetcher.get([url], archive=False, accept=("html",))
            link = download_button(page.text, url)
            if link:
                got = pdf(fetcher.get([link], archive=False, accept=accept))
                if got:
                    return got
        except FetchError:
            pass
    ref = informe_ref(url) or _dhn_ref(url)
    if ref and "repositorio.imarpe.gob.pe" not in url:
        # El mismo informe (número y año) en el repositorio del IMARPE, alcanzable desde Actions.
        got = pdf(imarpe_repo.informe_pdf(fetcher, ref["year"], ref["n"], problems))
        if got:
            return got
    got = pdf(archived_copy(fetcher, mirrors(url) + ([link] if link else []), accept))
    if got:
        return got
    if "/download/" in url:
        # El Internet Archive guarda la descarga con el parámetro wpdmdl, que no se conoce de antemano.
        got = pdf(archive_prefix(fetcher, url.split("?")[0]))
        if got:
            return got
        try:
            page = fetcher.get([url], archive=True, accept=("html",))
            link = download_button(page.text, url)
            if link:
                return pdf(fetcher.get([link], archive=True, accept=accept))
        except FetchError:
            pass
    return None


def acquire_informe(latest: Optional[dict], fetcher, previous_informe: Optional[dict], log, today: date,
                    icen_points: Optional[list[dict]] = None, documents: Optional[list] = None,
                    needs=None) -> Optional[dict]:
    """Informe técnico del comunicado vigente (``_acquire_informe``). Además, en cada corrida:

    - vuelve a anotar las incidencias de validación (``error``) del informe publicado, aunque se reutilice sin
      leerlo de nuevo: lo que no se publica sigue sin publicarse, así que su issue sigue abierto;
    - anota si el repositorio del IMARPE falló en esta corrida."""
    repo_problems: list = []
    try:
        out = _acquire_informe(latest, fetcher, previous_informe, log, today, icen_points, documents, needs,
                               repo_problems)
    finally:
        imarpe_repo.log_problems(log, repo_problems, "los informes técnicos del ENFEN")
    reused = bool(out and previous_informe and out.get("issues") and out.get("issues") is previous_informe.get("issues"))
    if reused:  # sin lectura nueva: las incidencias del informe publicado siguen vigentes
        for i in out["issues"]:
            if i.get("severity") == "error":
                log.add("error", "enfen-informe", "validate", i["code"], i["message"])
    return out


def _acquire_informe(latest: Optional[dict], fetcher, previous_informe: Optional[dict], log, today: date,
                     icen_points: Optional[list[dict]], documents: Optional[list], needs,
                     repo_problems: list) -> Optional[dict]:
    """Informe técnico del comunicado vigente: se baja una vez por comunicado (pesa 10–20 MB) y se lee.

    Rutas, en orden: el portal del ENFEN (no responde desde GitHub Actions ni desde n8n), la réplica de la DHN,
    las copias del recolector del Perú y el Internet Archive. Devuelve el resumen publicable
    (``informe_summary``) con ``retrievedAt``, ``channel`` y ``archive`` (la copia del PDF, que se agrega a
    ``documents``). Si no se puede bajar o leer, o nada de lo leído pasa las reglas, se conserva el resumen
    anterior marcado ``carried`` y queda la incidencia. Si solo falla una parte (una región, el ICEN
    temporal), esa parte no se publica y queda su incidencia. Nunca se publica un valor que no pasó la
    validación.

    ``needs`` (``manual.ManualNeeds``): si ninguna ruta da el PDF, el informe queda pendiente de subirse a mano en
    la consola de documentos; la copia subida se busca con la misma URL (o con ``manual://enfen-informe/<id>``
    si no se conoce la URL) y se valida igual que cualquier otra."""
    from datetime import datetime, timezone

    from . import archive, manual
    from .fetch import FetchError, archive_prefix

    def need(urls: list[str], reason: str, problem: Optional[str] = None) -> None:
        if needs is not None:
            needs.add(f"informe-{cid}", "informe", f"Informe técnico del ENFEN del comunicado N° {cid}",
                      urls + [manual.key("enfen-informe", cid)], [u for u in urls if "/download/" in u] + urls
                      + [INFORMES_PAGE, DHN_INFORMES_PAGE], reason,
                      expect={"communique": cid, "issued": latest.get("issued")}, problem=problem)

    if not latest:
        return previous_informe
    cid = latest.get("id")
    if previous_informe and previous_informe.get("communique") == cid and not previous_informe.get("carried"):
        return previous_informe  # ya leído en una corrida anterior

    def keep(reason: str, severity: str = "error", stage: str = "parse", review: Optional[dict] = None) -> Optional[dict]:
        have = bool(previous_informe and (previous_informe.get("probabilities") or previous_informe.get("icenProvisional")
                                          or previous_informe.get("lastOfficial")))
        note = " Se conserva el último informe leído." if have else ""
        if review:
            proposal = review["proposal"]
            if proposal.get("ok"):
                note += " La lectura con el modelo de lenguaje queda para revisión."
            elif proposal.get("transport"):
                note += f" El modelo de lenguaje no respondió ({proposal.get('error')})."
                llm_unavailable(log, proposal)
            else:
                note += " El modelo de lenguaje tampoco dio una lectura válida."
        log.add(severity, "enfen-informe", stage, "informe-unread", (reason + note)[:1500])
        prior = (previous_informe or {}).get("review")
        if review is None and prior and prior.get("communique") == cid:
            review = prior  # una falla de descarga posterior no borra la propuesta ya hecha para este comunicado
        base = {k: v for k, v in (previous_informe or {}).items() if k not in ("review", "carriedReason")}
        if not base and not review:
            return None
        return {**base, "carried": True, **({} if base else {"communique": None}),
                "carriedReason": f"No se pudo leer el informe del comunicado {cid}.", **({"review": review} if review else {})}

    url = latest.get("informe_url")
    hit, r = None, None
    if not url:
        try:
            r = fetcher.get([INFORMES_PAGE], archive=True, accept=("html",))
            hit = pick_informe(informe_entries(r.text), latest)
        except FetchError:
            hit = None
        if hit is None:
            # El repositorio del IMARPE: responde a GitHub Actions y el nombre del PDF trae la fecha de corte.
            try:
                hit = pick_informe(imarpe_repo.informes(fetcher, problems=repo_problems), latest)
            except Exception:  # noqa: BLE001 — una ruta más nunca detiene la corrida
                hit = None
        if hit is None:
            try:
                r = fetcher.get([DHN_INFORMES_PAGE], archive=False, accept=("html",))
                hit = pick_informe(dhn_entries(r.text), latest)
            except FetchError:
                hit = None
        if hit is None:
            # Sin la URL del informe solo sirve una copia subida a mano con la clave del comunicado.
            r = fetcher.copy(manual.key("enfen-informe", cid), ("pdf",)) if hasattr(fetcher, "copy") else None
            if r is None or r.body[:5] != b"%PDF-":
                need([], "Ningún listado de informes respondió (el portal del ENFEN no responde fuera del Perú).")
                return keep(f"El comunicado {cid} no enlaza su informe técnico y los listados del portal y de la DHN "
                            "no lo traen (o no respondieron).", "warning", "fetch")
            # La procedencia publicada es el listado oficial, no la clave interna; el ancla la hace única por
            # comunicado, para que el informe de este no se reutilice para el siguiente.
            url = f"{INFORMES_PAGE}#comunicado-{cid}"
            hit = {"url": url, "copy": r}
        url = hit["url"]
    # El comunicado nuevo cita el mismo informe: se reutiliza sin bajarlo. Solo si la URL es segura: la cita el
    # comunicado o el listado la eligió por su fecha de corte. Un número tomado de la réplica de la DHN sin fecha
    # puede ser el informe anterior (la DHN se atrasa): ese se baja y se valida.
    trusted = latest.get("informe_url") == url or bool((hit or {}).get("dataTo"))
    if trusted and previous_informe and previous_informe.get("url") == url and not previous_informe.get("carried"):
        return {**previous_informe, "communique": cid}
    try:
        r = (hit or {}).get("copy") or _informe_pdf(fetcher, url, FetchError, archive_prefix, repo_problems)
        if r is None:
            need(mirrors(url) + [url], "La réplica de la DHN pide verificación humana a los servidores automáticos "
                 "y las demás rutas no dieron el PDF." if any("dhn.mil.pe" in m for m in mirrors(url))
                 else "Ninguna ruta automática dio el PDF.")
            return keep(f"No se pudo bajar el informe técnico {url}: el portal, la réplica de la DHN (que puede "
                        "pedir verificación humana), las copias de los recolectores y el Internet Archive no "
                        "dieron el PDF.", "warning", "fetch")
        pages = pdf_pages(r.body)
    except FetchError as exc:
        need(mirrors(url) + [url], manual.reason_from(exc.attempts, "Ninguna ruta automática dio el PDF."))
        return keep(f"No se pudo bajar el informe técnico {url} (portal, réplica de la DHN, copias y archivo): {exc}",
                    "warning", "fetch")
    except Exception as exc:  # noqa: BLE001 — un PDF dañado no detiene la corrida
        need(mirrors(url) + [url], "El PDF que se obtuvo no se pudo leer.",
             f"{type(exc).__name__}: {exc}" if r is not None and r.channel == "relay-manual" else None)
        return keep(f"No se pudo leer el PDF del informe técnico {url}: {type(exc).__name__}: {exc}")
    try:
        ext = parse_informe(pages, url)
    except FormatChanged as exc:
        if r.channel == "relay-manual":
            need(mirrors(url) + [url], "La copia subida no se pudo leer.", f"Formato no reconocido: {exc}")
        review = reusable_review((previous_informe or {}).get("review"), url)  # mismo PDF: no se repite la consulta
        if review is None:
            proposal = llm_extract(getattr(fetcher, "client", None), "enfen-informe", "\n\f".join(pages), url=url)
            review = {"proposal": proposal, "reason": str(exc)[:300], "url": url, "communique": cid} if proposal else None
        return keep(f"Cambió el formato del informe técnico ({exc}).", review=review)
    validate_informe(ext, icen_official=icen_points, today=today, communique=latest)
    other = next((i for i in ext.issues if i.code == "informe-other-communique"), None)
    if other is None:
        for i in ext.issues:
            log.add(i.severity, "enfen-informe", "validate", i.code, i.message)
    summary = informe_summary(ext)
    if "repositorio.imarpe.gob.pe" in r.url:
        # La dirección oficial que sí sirvió el PDF (la página del ítem), además de la del portal.
        page = getattr(r, "page", None) or (hit or {}).get("page")
        if page:
            summary["repositoryUrl"] = page
        if r.channel == "direct":
            r.channel = "mirror"
    summary.update({"retrievedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "channel": r.channel,
                    "communique": cid, "pages": len(pages),
                    "archive": archive.source_path("enfen-comunicados", r.body)})
    manual_copy = r.channel == "relay-manual"
    if manual_copy and needs is not None:
        needs.mark_used(f"informe-{cid}", f"Informe técnico del ENFEN del comunicado N° {cid}", url, r.archived_at)
    if other is not None:
        # Lo esperable mientras la réplica se atrasa: una advertencia (no degrada la publicación), sin archivar el
        # PDF de otro periodo en cada corrida.
        if manual_copy:
            if needs is not None:
                needs.used.pop()
            need(mirrors(url) + [url], "La copia subida es de otro periodo.",
                 f"El PDF subido es el informe N° {ext.data.get('number')}, no el del comunicado {cid}.")
        return keep(f"El informe N° {ext.data.get('number')} no es el del comunicado {cid}: {other.message}",
                    "warning", "validate")
    if not summary["icenProvisional"] and not summary["probabilities"] and previous_informe:
        return keep("El informe técnico se leyó pero ninguno de sus valores pasó la validación.")
    if documents is not None:
        documents.append(r.body)  # solo el PDF aceptado se archiva
    return summary
