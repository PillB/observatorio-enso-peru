"""Parsers de fuentes peruanas: comunicados ENFEN e ICEN oficial (IGP)."""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Optional

from . import MONTHS_ES, FormatChanged, Parsed, check_series, fingerprint, period, trim_missing
from .cpc import html_to_text

# Estados del «Sistema de alerta ante El Niño Costero / La Niña Costera».
# Orden: de más a menos específico (los patrones se prueban en orden).
ENFEN_STATUSES = [
    (r"alerta\s+de\s+el\s+ni[ñn]o\s+coster[oa]", "Alerta de El Niño Costero", "alerta_nino", "alert"),
    (r"vigilancia\s+de\s+el\s+ni[ñn]o\s+coster[oa]", "Vigilancia de El Niño Costero", "vigilancia_nino", "watch"),
    (r"alerta\s+de\s+la\s+ni[ñn]a\s+coster[oa]", "Alerta de La Niña Costera", "alerta_nina", "alert"),
    (r"vigilancia\s+de\s+la\s+ni[ñn]a\s+coster[oa]", "Vigilancia de La Niña Costera", "vigilancia_nina", "watch"),
    (r"no\s+activo", "No activo", "no_activo", "ok"),
]

DATE_ES = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|se?tiembre|octubre|noviembre|diciembre)(?:\s+del?)?\s+(\d{4})\b",
    re.I,
)
NUMBER_RE = re.compile(r"COMUNICADO\s+OFICIAL\s+(?:DEL?\s+)?ENFEN\s+N\s*[°ºo.]*\s*(\d{1,2})\s*[-–]\s*(\d{4})", re.I)


def _date_es(s: str) -> Optional[str]:
    m = DATE_ES.search(s)
    if not m:
        return None
    month = MONTHS_ES.get(m.group(2).lower().replace("setiembre", "septiembre"), MONTHS_ES.get(m.group(2).lower()))
    try:
        return date(int(m.group(3)), month, int(m.group(1))).isoformat()
    except (TypeError, ValueError):
        return None


def normalize_status(fragment: str) -> Optional[dict]:
    low = re.sub(r"\s+", " ", fragment.lower())
    for pat, label, code, level in ENFEN_STATUSES:
        if re.search(pat, low):
            return {"label": label, "code": code, "level": level}
    return None


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _headline_summary(text: str, nm: re.Match) -> str:
    """Formato 2026: titular en mayúsculas seguido del párrafo principal.

    Se toma la primera línea en mayúsculas (cuatro o más palabras) después
    del número del comunicado y el texto que le sigue hasta completar dos
    oraciones; se quitan las llamadas de nota pegadas a las palabras.
    """
    lines = [l.strip() for l in text.splitlines()]
    flat_pos, start = 0, None
    for k, l in enumerate(lines):
        if start is None and NUMBER_RE.search(re.sub(r"\s+", " ", l)):
            start = k
            continue
        if start is not None and len(l.split()) >= 4 and l == l.upper() and re.search(r"[A-ZÁÉÍÓÚÑ]{3}", l):
            head = l.rstrip(" .").capitalize()
            for x in ("el niño", "la niña", "niño costero", "niña costera", "perú"):
                head = head.replace(x, x.title()).replace(x.capitalize(), x.title())
            rest = re.sub(r"\s+", " ", " ".join(lines[k + 1: k + 12]))
            rest = re.sub(r"(?<=[a-záéíóúñ)])\d+(?=[\s(.,]|$)", "", rest)
            rest = re.sub(r"\b(20\d\d)\d{1,2}(?=[\s(.,]|$)", r"\1", rest)
            # El texto del PDF a veces parte «del» y «al» («de l Mar»).
            rest = re.sub(r"\b([Dd]e|[Aa]) l (?=[A-Za-záéíóúñÁÉÍÓÚÑ])", r"\1l ", rest)
            sentences = re.findall(r".+?\.(?=\s|$)", rest)
            para = " ".join(x.strip() for x in sentences[:2])
            return re.sub(r"\s+([,.])", r"\1", f"{head}. {para}")[:700]
    return ""


def parse_enfen_communique(text: str, *, source: str = "") -> Parsed:
    """Extrae los campos de un comunicado oficial (texto de PDF o de HTML).

    Busca, por etiquetas y no por posición:
      * número y año: «COMUNICADO OFICIAL ENFEN N° 13-2025»;
      * fecha de emisión: la primera fecha en español junto al número
        (o «Callao, 13 de junio de 2019»);
      * estado: el texto que sigue a «Estado del sistema de alerta», con
        respaldo en frases como «mantiene el estado ... de “No Activo”»;
      * próximo comunicado: «próximo comunicado (oficial|ordinario) ... <fecha>»;
      * resumen ejecutivo: primer párrafo tras «RESUMEN EJECUTIVO».
    """
    flat = re.sub(r"\s+", " ", text)
    nm = NUMBER_RE.search(flat)
    if not nm:
        raise FormatChanged("enfen: no se encontró «COMUNICADO OFICIAL ENFEN N° NN-AAAA»")
    number, year = int(nm.group(1)), int(nm.group(2))
    around = flat[nm.end(): nm.end() + 220]
    issued = _date_es(around) or _date_es(flat[max(0, nm.start() - 300): nm.start()])
    cm = re.search(r"Callao,?\s+(\d{1,2}\s+de\s+\w+\s+(?:del?\s+)?\d{4})", flat, re.I)
    if not issued and cm:
        issued = _date_es(cm.group(1))

    status = None
    for sm in re.finditer(r"Estado\s+del\s+sistema\s+de\s+alerta[^:]{0,60}?:\s*(.{0,80})", flat, re.I):
        status = normalize_status(sm.group(1))
        if status:
            break
    if not status:
        # Desde la Nota Técnica ENFEN 02-2026 el estado va como titular, sin
        # etiqueta, justo después del número y la fecha («Alerta de El Niño
        # Costero¹»).
        status = normalize_status(flat[nm.end(): nm.end() + 160])
    if not status:
        for sm in re.finditer(r"(?:mantiene|cambia|activa|desactiva|modifica)[^.]{0,160}?(?:estado|sistema)[^.]{0,160}", flat, re.I):
            status = normalize_status(sm.group(0))
            if status:
                break
    if not status:
        raise FormatChanged("enfen: no se pudo identificar el estado del sistema de alerta")

    next_date = None
    for xm in re.finditer(r"(?:pr[oó]ximo|siguiente)\s+comunicado.{0,120}", flat, re.I):
        next_date = _date_es(xm.group(0))
        if next_date:
            break

    summary = ""
    rm = re.search(r"RESUMEN\s+EJECUTIVO\s+(.+?)(?=\s(?:Para\s+(?:este|el)|COMUNICADO\s+OFICIAL|Se\s+recomienda)|$)", flat, re.I)
    if rm:
        summary = rm.group(1).strip()[:700]
    else:
        body = flat[nm.end():]
        bm = re.search(r"(La\s+Comisi[oó]n\s+Multisectorial.+?\.)\s", body)
        summary = bm.group(1)[:500] if bm else ""
        if not summary:
            summary = _headline_summary(text, nm)

    warnings = []
    if not issued:
        warnings.append("enfen: fecha de emisión no encontrada")
    if issued and int(issued[:4]) not in (year, year + 1):
        warnings.append(f"enfen: fecha {issued} incoherente con el año del comunicado {year}")
    data = {
        "number": number, "year": year, "id": f"{number:02d}-{year}",
        "issued": issued, "status": status["label"], "status_code": status["code"],
        "level": status["level"], "next_issue": next_date, "summary": summary,
        "source": source,
    }
    return Parsed(data, fingerprint("enfen-comunicado", "RESUMEN EJECUTIVO" if rm else "sin-resumen"), warnings)


LISTING_RE = re.compile(
    r"href=[\"']([^\"']*comunicado-(oficial|extraordinario)-enfen-n-?(\d{1,2})-(\d{4})[^\"']*)[\"']", re.I
)


# Réplica de la Dirección de Hidrografía y Navegación (DHN), miembro del ENFEN:
# enlaces directos «/Archivos/oceanografia/enfen/comunicado-oficial/18-2026.pdf»
# (formato estable desde al menos 2022).
DHN_RE = re.compile(r"href=[\"']([^\"']*/comunicado-(oficial|extraordinario)/(\d{1,2})-(\d{4})\.pdf)[\"']", re.I)
DHN_BASE = "https://www.dhn.mil.pe"


def parse_enfen_listing(doc: str) -> Parsed:
    """Lista de comunicados en páginas de ENFEN (portal actual o antiguo).

    Reconoce los enlaces de descarga «comunicado-oficial-enfen-n-12-2026» y
    «comunicado-extraordinario-enfen-n-02-2025» del portal del ENFEN, y los
    PDF directos de la réplica de la DHN, sin depender del maquetado.
    Los oficiales van primero, del más reciente al más antiguo; los
    extraordinarios (numeración propia) van después, marcados con ``kind``.
    """
    seen = {}
    for rx in (LISTING_RE, DHN_RE):
        for m in rx.finditer(doc):
            url = m.group(1).replace("&#038;", "&").replace("&amp;", "&")
            if url.startswith("/"):
                url = DHN_BASE + url
            key = (m.group(2).lower(), int(m.group(4)), int(m.group(3)))
            seen.setdefault(key, url)
    if not seen:
        raise FormatChanged("enfen-listado: no hay enlaces a comunicados oficiales ni extraordinarios")
    items = []
    for kind in ("oficial", "extraordinario"):
        for (k, y, n), u in sorted(((k, v) for k, v in seen.items() if k[0] == kind), reverse=True):
            items.append({"year": y, "number": n, "kind": kind,
                          "id": f"{n:02d}-{y}" if kind == "oficial" else f"extraordinario {n:02d}-{y}", "url": u})
    return Parsed(items, fingerprint("enfen-listado", "comunicado-oficial-enfen-n", "comunicado-extraordinario-enfen-n"))


def parse_enfen_wp_posts(json_text: str) -> Parsed:
    """Respuesta de la API REST de WordPress del portal ENFEN."""
    import json

    posts = json.loads(json_text)
    if not isinstance(posts, list):
        raise FormatChanged("enfen-wp: la respuesta no es una lista de entradas")
    items = []
    for p in posts:
        title = html_to_text((p.get("title") or {}).get("rendered", ""))
        content = html_to_text((p.get("content") or {}).get("rendered", ""))
        m = NUMBER_RE.search(f"{title} {content}") or re.search(r"N\s*[°º]?\s*(\d{1,2})\s*[-–]\s*(\d{4})", title)
        if not m or "comunicado" not in (title + content[:300]).lower():
            continue
        items.append({
            "year": int(m.group(2)), "number": int(m.group(1)), "id": f"{int(m.group(1)):02d}-{m.group(2)}",
            "url": p.get("link", ""), "date": (p.get("date") or "")[:10], "text": f"{title}\n{content}",
        })
    items.sort(key=lambda x: (x["year"], x["number"]), reverse=True)
    return Parsed(items, fingerprint("enfen-wp", "title.rendered", "content.rendered"))


def parse_icen_txt(text: str) -> Parsed:
    """ICEN oficial publicado por el IGP («% yy mm ICEN»).

    El valor de un mes es la media de tres meses centrada en ese mes, por
    eso el último valor oficial suele ir dos meses detrás.
    """
    pts = []
    header = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("%"):
            header.append(line.lstrip("% ").strip())
            continue
        parts = line.split()
        if len(parts) < 3 or not re.fullmatch(r"\d{4}", parts[0]):
            continue
        try:
            y, m, v = int(parts[0]), int(parts[1]), float(parts[2])
        except ValueError:
            continue
        pts.append({"period": period(y, m), "value": None if v <= -99 else v})
    pts = trim_missing(pts)
    if not pts:
        raise FormatChanged("icen: sin filas «año mes valor»")
    warnings = check_series(pts, lo=-4.0, hi=6.0, name="icen-igp")
    version = next((h for h in header if "ICEN" in h), "")
    return Parsed(pts, fingerprint("icen-igp", version), warnings, {"header": header, "version": version})
