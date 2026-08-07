"""Descubrimiento y extracción determinista de documentos IMARPE/ENFEN.

El texto remoto siempre se trata como dato no confiable. Ninguna frase del
documento puede modificar el comportamiento del pipeline. Un valor crítico se
publica únicamente con fuente, página, período, unidad y evidencia textual.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse


class DocumentQuarantined(ValueError):
    """El activo o su extracción no satisfacen el contrato de publicación."""


ALERT_PATTERNS = (
    (r"Alerta de El Ni[ñn]o Costero", "Alerta de El Niño Costero"),
    (r"Vigilancia de El Ni[ñn]o Costero", "Vigilancia de El Niño Costero"),
    (r"Alerta de La Ni[ñn]a Coster[ao]", "Alerta de La Niña Costera"),
    (r"Vigilancia de La Ni[ñn]a Coster[ao]", "Vigilancia de La Niña Costera"),
    (r"(?:Estado[^.]{0,80})?No activo", "No activo"),
)

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

ENGLISH_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _plain_text(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", fragment,
                      flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _extract_alert(text: str) -> tuple[str | None, str | None]:
    found: list[tuple[str, str]] = []
    for pattern, label in ALERT_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            found.append((label, match.group(0)))
    labels = {label for label, _ in found}
    if len(labels) > 1:
        raise DocumentQuarantined("ambiguous ENFEN alert classifications")
    return found[0] if found else (None, None)


def parse_enfen_wordpress_posts(payload: str) -> dict[str, Any]:
    """Selecciona el comunicado oficial más reciente de la API WordPress."""
    try:
        posts = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DocumentQuarantined("invalid WordPress JSON") from exc
    if not isinstance(posts, list):
        raise DocumentQuarantined("WordPress response must be an array")
    candidates = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        title = _plain_text(str(post.get("title", {}).get("rendered", "")))
        content_html = str(post.get("content", {}).get("rendered", ""))
        content = _plain_text(content_html)
        if not re.search(r"COMUNICADO\s+OFICIAL\s+ENFEN", title, re.IGNORECASE):
            continue
        alert, evidence = _extract_alert(title + " " + content)
        if not alert:
            continue
        published = str(post.get("date", ""))[:10]
        try:
            date.fromisoformat(published)
        except ValueError:
            continue
        post_url = str(post.get("link", ""))
        if (urlparse(post_url).hostname or "").lower() != "enfen.imarpe.gob.pe":
            raise DocumentQuarantined("unexpected WordPress post domain")
        urls = []
        for raw in re.findall(r"href=[\"']([^\"']+)", content_html, re.IGNORECASE):
            url = html.unescape(raw)
            parsed = urlparse(url)
            if parsed.scheme == "https" and parsed.hostname == "enfen.imarpe.gob.pe" and "/download/" in parsed.path:
                urls.append(url)
        candidates.append({
            "post_id": post.get("id"),
            "publication_date": published,
            "modified_at": str(post.get("modified", "")),
            "alert": alert,
            "source_url": post_url,
            "document_urls": sorted(set(urls)),
            "evidence_text": evidence,
            "source_method": "wordpress_rest_json",
        })
    if not candidates:
        raise DocumentQuarantined("no valid official ENFEN communiqué found")
    return max(candidates, key=lambda item: (item["publication_date"], int(item["post_id"] or 0)))


def discover_latest_enfen_communique(fragment: str) -> str:
    """Descubre el comunicado más reciente desde el índice HTML oficial.

    Se usa únicamente como respaldo cuando la API REST oficial no entrega un
    contrato utilizable. La selección se basa en el número/año del comunicado,
    no en clases CSS ni en el orden visual de la página.
    """
    lower = fragment[:1500].lower()
    if "cloudflare" in lower or "just a moment" in lower or "bad gateway" in lower:
        raise DocumentQuarantined("ENFEN access/error page substituted for index")
    candidates: list[tuple[int, int, str]] = []
    for raw_url, raw_label in re.findall(
        r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        fragment,
        re.IGNORECASE | re.DOTALL,
    ):
        label = _plain_text(raw_label)
        match = re.search(
            r"COMUNICADO\s+OFICIAL\s+ENFEN\s+N(?:°|º|&deg;)?\s*(\d+)\s*[-–]\s*(20\d{2})",
            label,
            re.IGNORECASE,
        )
        if not match:
            continue
        url = html.unescape(raw_url)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "enfen.imarpe.gob.pe":
            continue
        if not re.fullmatch(
            r"/download/comunicado-oficial-enfen-n-\d+-20\d{2}/?", parsed.path,
            re.IGNORECASE,
        ):
            continue
        candidates.append((int(match.group(2)), int(match.group(1)), url))
    if not candidates:
        raise DocumentQuarantined("official ENFEN HTML index exposed no valid communiqué")
    return max(candidates)[2]


def parse_enfen_communique_html(fragment: str, *, source_url: str) -> dict[str, Any]:
    """Extrae estado, fecha y activo PDF desde la página oficial del comunicado."""
    parsed_source = urlparse(source_url)
    if parsed_source.scheme != "https" or parsed_source.hostname != "enfen.imarpe.gob.pe":
        raise DocumentQuarantined("unexpected ENFEN communiqué domain")
    if not re.fullmatch(
        r"/download/comunicado-oficial-enfen-n-\d+-20\d{2}/?", parsed_source.path,
        re.IGNORECASE,
    ):
        raise DocumentQuarantined("unexpected ENFEN communiqué path")
    text = _plain_text(fragment)
    title_match = re.search(
        r"COMUNICADO\s+OFICIAL\s+ENFEN\s+N(?:°|º)?\s*(\d+)\s*[-–]\s*(20\d{2})",
        text,
        re.IGNORECASE,
    )
    if not title_match:
        raise DocumentQuarantined("official ENFEN communiqué identity missing")
    alert, evidence = _extract_alert(text)
    if not alert:
        raise DocumentQuarantined("official ENFEN alert classification missing")

    publication_date: str | None = None
    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", fragment[:5000])
    if iso_match:
        try:
            publication_date = date.fromisoformat(iso_match.group(1)).isoformat()
        except ValueError:
            publication_date = None
    if not publication_date:
        date_match = re.search(
            r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[, ]+"
            r"(20\d{2})\b",
            text,
            re.IGNORECASE,
        )
        if date_match:
            publication_date = date(
                int(date_match.group(3)),
                ENGLISH_MONTHS[date_match.group(2).lower()[:3]],
                int(date_match.group(1)),
            ).isoformat()
    if not publication_date:
        raise DocumentQuarantined("official ENFEN publication date missing")

    document_urls = []
    for raw in re.findall(r"href=[\"']([^\"']+)", fragment, re.IGNORECASE):
        url = html.unescape(raw)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "enfen.imarpe.gob.pe":
            continue
        if parsed.path.lower().endswith(".pdf") or "wpdmdl=" in parsed.query.lower():
            document_urls.append(url)
    return {
        "post_id": None,
        "publication_date": publication_date,
        "modified_at": "",
        "alert": alert,
        "source_url": source_url,
        "document_urls": sorted(set(document_urls)),
        "evidence_text": evidence,
        "source_method": "official_html_document_page",
    }


def validate_pdf_payload(
    content: bytes,
    content_type: str,
    *,
    max_bytes: int = 25 * 1024 * 1024,
) -> dict[str, Any]:
    """Valida tamaño, MIME y firma antes de abrir un PDF no confiable."""
    if len(content) > max_bytes:
        raise DocumentQuarantined("PDF exceeds bounded response size")
    if "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
        raise DocumentQuarantined(f"unexpected PDF MIME: {content_type}")
    if not content.startswith(b"%PDF-"):
        raise DocumentQuarantined("PDF magic mismatch; possible HTML substitution")
    if b"%%EOF" not in content[-4096:]:
        raise DocumentQuarantined("truncated PDF missing EOF marker")
    return {
        "content_length": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "mime": content_type.split(";", 1)[0].strip().lower(),
    }


def extract_pdf_pages(content: bytes) -> list[str]:
    """Extrae texto nativo página por página; no usa OCR ni LLM."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content), strict=True)
    except Exception as exc:
        raise DocumentQuarantined(f"PDF cannot be opened completely: {exc}") from exc
    pages = [re.sub(r"\s+", " ", page.extract_text() or "").strip() for page in reader.pages]
    if not any(pages):
        raise DocumentQuarantined("PDF has no native text; OCR review required")
    return pages


def _month_period(month_name: str, year: str) -> str:
    month = MONTHS.get(month_name.lower())
    if not month:
        raise DocumentQuarantined(f"unknown Spanish month: {month_name}")
    return f"{int(year):04d}-{month:02d}"


def parse_official_enfen_pages(pages: list[str], *, source_url: str) -> dict[str, Any]:
    """Extrae alerta e ICEN solamente de afirmaciones explícitas y unívocas."""
    if urlparse(source_url).scheme != "https":
        raise DocumentQuarantined("document source must use HTTPS")
    joined = " ".join(pages)
    alert, alert_quote = _extract_alert(joined)
    alert_hits = []
    if alert:
        for index, page in enumerate(pages, start=1):
            if alert_quote and re.search(re.escape(alert_quote), page, re.IGNORECASE):
                alert_hits.append((index, alert_quote))
    icen_hits = []
    pattern = re.compile(
        r"(?:El\s+)?ICEN(?:\s+correspondiente)?\s+a\s+"
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
        r"\s+(?:de\s+)?(20\d{2})\s+(?:fue|es|alcanz[oó])\s+"
        r"([+\-−]?\d{1,2}(?:[,.]\d{1,3})?)\s*°?\s*C",
        re.IGNORECASE,
    )
    for page_no, page in enumerate(pages, start=1):
        for match in pattern.finditer(page):
            value = float(match.group(3).replace("−", "-").replace(",", "."))
            if not -8 <= value <= 8:
                raise DocumentQuarantined("ICEN outside physical plausibility range")
            icen_hits.append({
                "page": page_no,
                "quote": match.group(0),
                "period": _month_period(match.group(1), match.group(2)),
                "value": value,
            })
    if len(icen_hits) > 1:
        raise DocumentQuarantined("ambiguous ICEN values in official document")
    if not alert and not icen_hits:
        raise DocumentQuarantined("document has no publishable ENFEN fact")
    return {
        "alert": alert,
        "icen": icen_hits[0]["value"] if icen_hits else None,
        "icen_period": icen_hits[0]["period"] if icen_hits else None,
        "source_url": source_url,
        "evidence": {
            "alert": ({"page": alert_hits[0][0], "quote": alert_hits[0][1]} if alert_hits else None),
            "icen": icen_hits[0] if icen_hits else None,
        },
        "extraction_method": "native_pdf_text_deterministic_regex",
    }


def parse_siofen_bulletin_index(fragment: str, *, bulletin_type: str) -> list[dict[str, Any]]:
    """Descubre adjuntos PDF sin depender de selectores CSS cosméticos."""
    if bulletin_type not in {"BDO", "BS-TLP"}:
        raise ValueError("unsupported SIOFEN bulletin type")
    lower = fragment[:1000].lower()
    if "cloudflare" in lower or "just a moment" in lower or "bad gateway" in lower:
        raise DocumentQuarantined("SIOFEN access/error page substituted for index")
    assets = []
    seen = set()
    for raw in re.findall(r"(?:href|src)=[\"']([^\"']+\.pdf(?:\?[^\"']*)?)", fragment, re.IGNORECASE):
        url = html.unescape(raw)
        parsed = urlparse(url)
        expected_prefix = f"/img/productoArchivo/{bulletin_type}/"
        if parsed.scheme != "https" or parsed.hostname != "siofen-admin.imarpe.gob.pe":
            continue
        if expected_prefix not in parsed.path or url in seen:
            continue
        seen.add(url)
        item: dict[str, Any] = {"url": url, "bulletin_type": bulletin_type}
        if bulletin_type == "BDO":
            match = re.search(r"BOL_IMARPE_BDO_(20\d{2}-\d{2}-\d{2})\.pdf", parsed.path, re.IGNORECASE)
            if not match:
                continue
            item["publication_date"] = match.group(1)
        else:
            match = re.search(r"BOL_IMARPE_BS_TLP_(20\d{2})_N(?:%C2%B0|°)?(\d+)\.pdf", url, re.IGNORECASE)
            if not match:
                continue
            item["publication_year"] = int(match.group(1))
            item["issue"] = int(match.group(2))
        assets.append(item)
    if bulletin_type == "BDO":
        assets.sort(key=lambda item: item["publication_date"], reverse=True)
    else:
        assets.sort(key=lambda item: (item["publication_year"], item["issue"]), reverse=True)
    return assets


def parse_imarpe_bulletin_pages(
    pages: list[str], *, bulletin_type: str, source_url: str
) -> dict[str, Any]:
    """Extrae el rango costero explícito de un BDO/BS-TLP con trazabilidad.

    El rango es contexto de estaciones costeras, no un promedio regional ni
    un ICEN. Las tablas completas pueden añadirse cuando la disposición sea
    estable y las coordenadas/columnas pasen un contrato separado.
    """
    if bulletin_type not in {"BDO", "BS-TLP"}:
        raise ValueError("unsupported bulletin type")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme != "https" or parsed_url.hostname != "siofen-admin.imarpe.gob.pe":
        raise DocumentQuarantined("unexpected SIOFEN bulletin domain")
    joined = " ".join(pages)
    required_title = (
        r"BOLET[IÍ]N\s+DIARIO\s+OCEANOGR[AÁ]FICO" if bulletin_type == "BDO"
        else r"BOLET[IÍ]N\s+SEMANAL.{0,100}TEMPERATURA\s+SUPERFICIAL\s+DEL\s+MAR"
    )
    if not re.search(required_title, joined, re.IGNORECASE):
        raise DocumentQuarantined("bulletin identity/title mismatch")
    date_pattern = re.compile(
        r"(?:para\s+el\s+|del\s+)?(\d{1,2})\s+de\s+"
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
        r"\s+(?:de\s+)?(20\d{2})",
        re.IGNORECASE,
    )
    date_hits = []
    for page_no, page in enumerate(pages, start=1):
        for match in date_pattern.finditer(page):
            try:
                parsed_date = date(
                    int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1))
                ).isoformat()
            except (ValueError, KeyError):
                continue
            date_hits.append({"page": page_no, "quote": match.group(0), "period": parsed_date})
    if not date_hits:
        raise DocumentQuarantined("bulletin valid period is missing")
    # Prefer the date explicitly introduced as "para el"; otherwise use the
    # latest valid date in the bulletin, never the retrieval date.
    preferred = [hit for hit in date_hits if hit["quote"].lower().startswith("para el")]
    period_hit = max(preferred or date_hits, key=lambda hit: hit["period"])

    range_pattern = re.compile(
        r"(?:registraron\s+)?valores\s+de\s+TSM\s+entre\s+"
        r"([+\-−]?\d{1,2}[,.]\d+)\s*°\s*C\s*\(([^)]+)\)\s*,?\s*y\s+"
        r"([+\-−]?\d{1,2}[,.]\d+)\s*°\s*C\s*\(([^)]+)\)",
        re.IGNORECASE,
    )
    ranges = []
    for page_no, page in enumerate(pages, start=1):
        for match in range_pattern.finditer(page):
            lo = float(match.group(1).replace("−", "-").replace(",", "."))
            hi = float(match.group(3).replace("−", "-").replace(",", "."))
            if not (-2 <= lo <= 40 and -2 <= hi <= 40 and lo <= hi):
                raise DocumentQuarantined("invalid or reversed bulletin SST range")
            ranges.append({
                "page": page_no, "quote": match.group(0),
                "min": lo, "min_station": match.group(2).strip(),
                "max": hi, "max_station": match.group(4).strip(),
            })
    if len(ranges) != 1:
        raise DocumentQuarantined(
            "bulletin SST range missing or ambiguous" if not ranges
            else "multiple ambiguous bulletin SST ranges"
        )
    observed = ranges[0]
    return {
        "bulletin_type": bulletin_type,
        "valid_period": period_hit["period"],
        "sst_min": observed["min"],
        "sst_min_station": observed["min_station"],
        "sst_max": observed["max"],
        "sst_max_station": observed["max_station"],
        "units": "degC",
        "recommended_role": "RAPID_OBSERVATIONAL",
        "source_url": source_url,
        "evidence": {"period": period_hit, "sst_range": observed},
        "extraction_method": "native_pdf_text_deterministic_regex",
    }
