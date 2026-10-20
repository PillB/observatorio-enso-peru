"""Parsers de productos de texto de NOAA/CPC y NOAA/PSL."""

from __future__ import annotations

import html as html_mod
import re
from datetime import date
from typing import Optional

from . import (
    FLOAT, MON3, MONTHS_EN, FormatChanged, Parsed, check_series, fingerprint,
    norm_missing, period, trim_missing,
)

SEASON_CENTER = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}

SECTION_WORDS = ("ORIGINAL", "ANOMALY", "STANDARDIZED")


# ---------------------------------------------------------------------------
# Matrices año × 12 meses (soi, tahiti, darwin, wpac850, cpac850, epac850)
# ---------------------------------------------------------------------------
def parse_year_matrix(text: str, *, lo: float, hi: float, name: str) -> Parsed:
    """Parsea archivos CPC con una o varias secciones «AÑO + 12 valores».

    Devuelve ``data = {sección: [ {period, value} ]}``. Las secciones se
    identifican por las palabras ORIGINAL / ANOMALY / STANDARDIZED en las
    líneas de encabezado, de modo que el orden puede cambiar sin romper el
    parseo. Los valores concatenados («-3.3-999.9») se separan por regex.
    """
    sections: dict[str, list[dict]] = {}
    headers: list[str] = []
    current = None
    title_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()
        words = [w for w in SECTION_WORDS if re.search(rf"\b{w}\b", upper)]
        if words and not re.match(r"^\d{4}", line):
            current = words[0].lower()
            # El mismo nombre puede repetirse (p. ej. dos tablas «ANOMALY»).
            base, k = current, 2
            while current in sections:
                current = f"{base}_{k}"
                k += 1
            sections[current] = []
            headers.append(current)
            continue
        m = re.match(r"^(\d{4})(.*)$", line)
        if not m:
            if not current:
                title_lines.append(line)
            continue
        if current is None:
            current = "data"
            sections[current] = []
            headers.append(current)
        year = int(m.group(1))
        vals = FLOAT.findall(m.group(2))
        if not 1 <= len(vals) <= 12:
            continue
        for i, v in enumerate(vals):
            sections[current].append({
                "period": period(year, i + 1),
                "value": norm_missing(float(v), -999.0),
            })
    if not sections:
        raise FormatChanged(f"{name}: no se encontraron filas AÑO + meses")
    warnings: list[str] = []
    out = {}
    for key, pts in sections.items():
        pts = trim_missing(pts)
        if not pts:
            continue
        warnings += check_series(pts, lo=lo, hi=hi, name=f"{name}/{key}")
        out[key] = pts
    fp = fingerprint(name, "|".join(headers), " ".join(title_lines[:2]))
    return Parsed(out, fp, warnings, {"sections": headers, "title": " ".join(title_lines[:2])})


# ---------------------------------------------------------------------------
# RONI / ONI (temporadas de 3 meses)
# ---------------------------------------------------------------------------
def parse_seasonal(text: str, *, name: str = "roni") -> Parsed:
    """Parsea RONI.ascii.txt u oni.ascii.txt.

    La columna de anomalía se localiza por el nombre «ANOM» en la cabecera
    (en ONI hay además una columna TOTAL). El periodo publicado es el mes
    central de la temporada (DJF → enero).
    """
    header = None
    pts: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if parts[0].upper() in ("SEAS", "SEASON"):
            header = [p.upper() for p in parts]
            continue
        if parts[0].upper() not in SEASON_CENTER or len(parts) < 3:
            continue
        idx = header.index("ANOM") if header and "ANOM" in header else len(parts) - 1
        try:
            yr = int(parts[1])
            v = float(parts[idx])
        except (ValueError, IndexError):
            continue
        center = SEASON_CENTER[parts[0].upper()]
        y = yr
        # NDJ: el mes central (diciembre) pertenece al año indicado.
        pts.append({"period": period(y, center), "value": norm_missing(v, -99.0),
                    "season": parts[0].upper()})
    if header is None:
        raise FormatChanged(f"{name}: falta la cabecera SEAS/YR/ANOM")
    pts = trim_missing(pts)
    warnings = check_series(pts, lo=-4.5, hi=4.5, name=name)
    return Parsed(pts, fingerprint(name, " ".join(header)), warnings, {"header": header})


# ---------------------------------------------------------------------------
# Tablas mensuales de regiones Niño (ersst5.nino.mth.91-20.ascii, sstoi.indices)
# ---------------------------------------------------------------------------
REGION_ALIASES = {
    "NINO1+2": "nino12", "NINO12": "nino12", "NINO3": "nino3",
    "NINO4": "nino4", "NINO3.4": "nino34", "NINO34": "nino34",
}


def parse_nino_monthly(text: str, *, name: str) -> Parsed:
    """Tabla «YR MON NINO1+2 ANOM NINO3 ANOM ...».

    El orden de las columnas difiere entre productos (en sstoi y ERSST
    Niño 4 va antes que Niño 3.4), por eso se mapean por nombre: cada
    columna «ANOM» pertenece a la región inmediatamente anterior.
    """
    cols: Optional[list[str]] = None
    out: dict[str, list[dict]] = {}
    sst: dict[str, list[dict]] = {}
    for raw in text.splitlines():
        parts = raw.split()
        if not parts:
            continue
        if parts[0].upper() in ("YR", "YEAR"):
            cols = [p.upper() for p in parts]
            continue
        if cols is None or not re.fullmatch(r"\d{4}", parts[0]):
            continue
        if len(parts) != len(cols):
            continue
        y, mth = int(parts[0]), int(parts[1])
        region = None
        for c, v in zip(cols[2:], parts[2:]):
            val = norm_missing(float(v), -99.0)
            if c in REGION_ALIASES:
                region = REGION_ALIASES[c]
                sst.setdefault(region, []).append({"period": period(y, mth), "value": val})
            elif c == "ANOM" and region:
                out.setdefault(region, []).append({"period": period(y, mth), "value": val})
    if not cols or "nino12" not in out or "nino34" not in out:
        raise FormatChanged(f"{name}: no se reconocen las columnas de regiones Niño")
    warnings: list[str] = []
    for k in list(out):
        out[k] = trim_missing(out[k])
        warnings += check_series(out[k], lo=-6.0, hi=7.0, name=f"{name}/{k}")
    for k in list(sst):
        sst[k] = trim_missing(sst[k])
    return Parsed({"anom": out, "sst": sst}, fingerprint(name, " ".join(cols)), warnings, {"columns": cols})


# ---------------------------------------------------------------------------
# Semanal OISST (wksst9120.for)
# ---------------------------------------------------------------------------
WEEK_RE = re.compile(r"^\s*(\d{1,2})([A-Za-z]{3})(\d{4})\s+(.*)$")


def parse_weekly(text: str, *, name: str = "wksst") -> Parsed:
    """Índices semanales de TSM (semana centrada en miércoles).

    Devuelve por región una lista de {date, sst, anom}. La cabecera indica
    el orden de regiones; si falta, se asume el orden histórico
    Niño1+2, Niño3, Niño3.4, Niño4. La línea «Weekly SST data starts...»
    no se usa para nada estructural.
    """
    order = ["nino12", "nino3", "nino34", "nino4"]
    head = ""
    base = ""
    out: dict[str, list[dict]] = {r: [] for r in order}
    for raw in text.splitlines():
        u = raw.upper()
        if "NINO" in u and not WEEK_RE.match(raw):
            found = re.findall(r"NINO\s*(1\+2|3\.4|34|3|4)", u)
            if len(found) >= 4:
                order = [REGION_ALIASES["NINO" + f.replace(" ", "")] for f in found[:4]]
                head = " ".join(found)
                out = {r: [] for r in order}
            continue
        if "STARTS" in u:
            base = raw.strip()
            continue
        m = WEEK_RE.match(raw)
        if not m:
            continue
        d, mon, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        if mon not in MON3:
            continue
        vals = re.findall(r"-?\d+\.\d", m.group(4))
        if len(vals) < 8:
            continue
        iso = date(y, MON3[mon], d).isoformat()
        for i, region in enumerate(order):
            s, a = float(vals[2 * i]), float(vals[2 * i + 1])
            if s < -50 or a < -50:
                continue
            out[region].append({"date": iso, "sst": s, "anom": a})
    if not out.get("nino12") or not out.get("nino34"):
        raise FormatChanged(f"{name}: no se reconocen filas semanales")
    warnings = []
    for region, pts in out.items():
        dates = [p["date"] for p in pts]
        if dates != sorted(dates) or len(set(dates)) != len(dates):
            raise FormatChanged(f"{name}/{region}: fechas desordenadas o duplicadas")
        for p in pts:
            if not (-6 <= p["anom"] <= 8 and 10 <= p["sst"] <= 35):
                warnings.append(f"{name}/{region}: valor implausible {p}")
    return Parsed(out, fingerprint(name, head, "weekly"), warnings, {"base": base, "regions": order})


# ---------------------------------------------------------------------------
# PSL «long» CSV
# ---------------------------------------------------------------------------
def parse_psl_csv(text: str, *, name: str) -> Parsed:
    pts = []
    header = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(\d{4})-(\d{1,2})(?:-\d{1,2})?\s*,\s*(-?\d+(?:\.\d+)?)", line)
        if not m:
            if not pts and not header:
                header = line
            continue
        v = norm_missing(float(m.group(3)), -99.0)
        pts.append({"period": period(int(m.group(1)), int(m.group(2))), "value": v})
    pts = trim_missing(pts)
    warnings = check_series(pts, lo=-6.0, hi=7.0, name=name)
    return Parsed(pts, fingerprint(name, header.split("missing")[0].strip()), warnings, {"header": header})


# ---------------------------------------------------------------------------
# ENSO Diagnostic Discussion (HTML)
# ---------------------------------------------------------------------------
NOAA_STATUSES = [
    ("final el niño advisory", "Final El Niño Advisory", "final_nino"),
    ("final la niña advisory", "Final La Niña Advisory", "final_nina"),
    ("el niño advisory", "El Niño Advisory", "nino_advisory"),
    ("la niña advisory", "La Niña Advisory", "nina_advisory"),
    ("el niño watch", "El Niño Watch", "nino_watch"),
    ("la niña watch", "La Niña Watch", "nina_watch"),
    ("not active", "Not Active", "not_active"),
]

DATE_EN = re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b", re.I)
DATE_EN_US = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b", re.I)


def html_to_text(doc: str) -> str:
    doc = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", doc)
    doc = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", doc)
    doc = re.sub(r"<[^>]+>", " ", doc)
    doc = html_mod.unescape(doc).replace("\xa0", " ")
    doc = re.sub(r"[ \t]+", " ", doc)
    return re.sub(r"\n\s*\n+", "\n", doc).strip()


def _date_en(s: str) -> Optional[str]:
    m = DATE_EN.search(s)
    if m:
        return date(int(m.group(3)), MONTHS_EN[m.group(2).lower()], int(m.group(1))).isoformat()
    m = DATE_EN_US.search(s)
    if m:
        return date(int(m.group(3)), MONTHS_EN[m.group(1).lower()], int(m.group(2))).isoformat()
    return None


def parse_enso_discussion(doc: str) -> Parsed:
    """Extrae estado, fecha, sinopsis y próxima emisión del boletín mensual."""
    text = re.sub(r"\s+", " ", html_to_text(doc))
    m = re.search(r"Alert System Status\s*:?\s*(.{3,120}?)\s*Synopsis", text, re.I)
    if not m:
        raise FormatChanged("ensodisc: no se encontró «ENSO Alert System Status»")
    raw_status = m.group(1).strip(" .;:")
    low = raw_status.lower().replace("nino", "niño").replace("nina", "niña")
    statuses = [(label, code) for key, label, code in NOAA_STATUSES if key in low]
    if not statuses:
        raise FormatChanged(f"ensodisc: estado no reconocido «{raw_status}»")
    # Puede haber dos estados simultáneos («Final La Niña Advisory / El Niño Watch»).
    seen, labels, codes = set(), [], []
    for label, code in statuses:
        if any(label in other and label != other for other, _ in statuses):
            continue
        if label not in seen:
            seen.add(label)
            labels.append(label)
            codes.append(code)
    head = text[: m.start()]
    issued = None
    im = re.search(r"issued by.{0,80}?(\d{1,2}\s+\w+\s+\d{4})", head, re.I)
    issued = _date_en(im.group(1)) if im else _date_en(head[-200:])
    sm = re.search(r"Synopsis\s*:\s*(.+?)(?:\s{2,}|\[Fig|$)", text[m.end() - 9:], re.I)
    synopsis = sm.group(1).strip() if sm else ""
    synopsis = re.split(r"(?<=[.!?])\s", synopsis, maxsplit=1)[0] if len(synopsis) > 400 else synopsis
    nm = re.search(r"next ENSO Diagnostics? Discussion is scheduled for\s+(.{6,40}?)\.", text, re.I)
    next_issue = _date_en(nm.group(1)) if nm else None
    values = {}
    for region, pat in (("nino34", r"([+-]?\d\.\d)\s*°?C?\s*in\s*Niño-?3\.4"),
                        ("nino3", r"([+-]?\d\.\d)\s*°?C?\s*in\s*Niño-?3(?!\.)"),
                        ("nino12", r"([+-]?\d\.\d)\s*°?C?\s*in\s*Niño-?1\+2"),
                        ("nino4", r"([+-]?\d\.\d)\s*°?C?\s*in\s*Niño-?4")):
        vm = re.search(pat, text, re.I)
        if vm:
            values[region] = float(vm.group(1))
    warnings = [] if issued else ["ensodisc: no se pudo leer la fecha de emisión"]
    data = {
        "status": " / ".join(labels), "codes": codes, "raw_status": raw_status,
        "issued": issued, "synopsis": synopsis, "next_issue": next_issue,
        "weekly_values_in_text": values,
    }
    return Parsed(data, fingerprint("ensodisc", "Alert System Status", "Synopsis"), warnings)
