"""Repositorio institucional del IMARPE (DSpace 8, https://repositorio.imarpe.gob.pe): una ruta oficial y sin
verificación humana para los documentos del ENFEN.

El IMARPE (miembro del ENFEN) deposita cada comunicado oficial y cada informe técnico, unos días después de su
publicación (el comunicado 18-2026, emitido el 16 de octubre, entró el 19). A diferencia del portal del ENFEN (que no
responde fuera del Perú) y de la réplica de la DHN (que pide verificación humana a los servidores), su API REST
responde a GitHub Actions. robots.txt prohíbe la búsqueda de la interfaz (``/search``), no la API (``/server/api``).

El servidor envía solo su certificado, sin el intermedio de Sectigo: ``enso.fetch.ssl_context`` lo agrega.

Es el único cliente del repositorio: lo usan el comunicado y el informe técnico (``enso.observatory``,
``enso.reports``) y puede usarlo cualquier otro lector con su propia búsqueda (``search``). Todo pasa por el
``Fetcher`` compartido (plan, tiempo y copias de los recolectores). Lo que se baja de aquí se valida igual que
cualquier otra copia: el número y el periodo del documento, y que sea un PDF.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional
from urllib.parse import urlencode

from . import MONTHS_ES

BASE = "https://repositorio.imarpe.gob.pe"
API = f"{BASE}/server/api"

COMMUNIQUE_TITLE = re.compile(r"Comunicado\s+Oficial\s+ENFEN\s+N\s*[°º.]*\s*(\d{1,2})\s*[-–]\s*(\d{4})", re.I)
INFORME_TITLE = re.compile(r"Informe\s+T[ée]cnico\s+ENFEN\s+A[ñn]o\s+(\d{1,2})\s+N\s*[°º.]*\s*(\d{1,2})\s*,\s*(\d{4})", re.I)
# «Informe Tecnico ENFEN Año 12 N°18 al 13 octubre 2026.pdf»: la fecha de corte de datos.
_DATA_TO = re.compile(r"\bal\s+(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)\s+(?:de\s+)?(\d{4})", re.I)


def _get_json(fetcher, url: str) -> Optional[dict]:
    from ..fetch import FetchError

    try:
        r = fetcher.get([url], archive=False, accept=("json",))
        data = json.loads(r.text)
    except (FetchError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _meta(item: dict, key: str) -> Optional[str]:
    vals = (item.get("metadata") or {}).get(key) or []
    return vals[0].get("value") if vals and isinstance(vals[0], dict) else None


def search(fetcher, query: str, size: int = 10) -> list[dict]:
    """Ítems más recientes (por fecha de emisión) que responden a ``query``: uuid, título, fecha y su página."""
    params = urlencode({"query": query, "dsoType": "ITEM", "size": size, "sort": "dc.date.issued,DESC"})
    data = _get_json(fetcher, f"{API}/discover/search/objects?{params}")
    try:
        objs = data["_embedded"]["searchResult"]["_embedded"]["objects"]
    except (KeyError, TypeError):
        return []
    out = []
    for o in objs:
        it = (o.get("_embedded") or {}).get("indexableObject") or {}
        if not it.get("uuid"):
            continue
        handle = it.get("handle")
        out.append({"uuid": it["uuid"], "title": _meta(it, "dc.title") or "", "issued": _meta(it, "dc.date.issued"),
                    "page": f"{BASE}/handle/{handle}" if handle else f"{BASE}/items/{it['uuid']}"})
    return out


def pdfs(fetcher, uuid: str) -> list[dict]:
    """Archivos PDF del ítem (paquete ORIGINAL): nombre, tamaño y URL del contenido."""
    data = _get_json(fetcher, f"{API}/core/items/{uuid}/bundles?embed=bitstreams")
    out = []
    try:
        bundles = data["_embedded"]["bundles"]
    except (KeyError, TypeError):
        return out
    for b in bundles:
        if b.get("name") != "ORIGINAL":
            continue
        for x in (((b.get("_embedded") or {}).get("bitstreams") or {}).get("_embedded") or {}).get("bitstreams") or []:
            href = ((x.get("_links") or {}).get("content") or {}).get("href")
            if href and (x.get("name") or "").lower().endswith(".pdf"):
                out.append({"name": x["name"], "size": x.get("sizeBytes"), "url": href})
    return out


def fetch_pdf(fetcher, url: str):
    """El PDF (``Response`` con canal «mirror»: otra dirección oficial) o ``None`` si no es un PDF."""
    from ..fetch import FetchError

    try:
        r = fetcher.get([url], archive=False, accept=("pdf", "octet-stream"))
    except FetchError:
        return None
    if r.body[:5] != b"%PDF-":
        return None
    if r.channel == "direct":
        r.channel = "mirror"
    return r


def communiques(fetcher, size: int = 6) -> list[dict]:
    """Comunicados oficiales depositados, del más reciente al más antiguo, en el formato del listado del ENFEN."""
    out = []
    for it in search(fetcher, '"Comunicado Oficial ENFEN"', size):
        m = COMMUNIQUE_TITLE.search(it["title"])
        if m:
            n, y = int(m.group(1)), int(m.group(2))
            out.append({"year": y, "number": n, "kind": "oficial", "id": f"{n:02d}-{y}", "url": it["page"],
                        "repository": it["uuid"], "issued": it["issued"]})
    return out


def communique_pdf(fetcher, year: int, number: int):
    """El PDF del comunicado N° ``number``-``year``, solo si el título del ítem es exactamente ese número."""
    for it in search(fetcher, f'"Comunicado Oficial ENFEN" {number:02d}-{year}', 5):
        m = COMMUNIQUE_TITLE.search(it["title"])
        if m and (int(m.group(2)), int(m.group(1))) == (year, number):
            for f in pdfs(fetcher, it["uuid"]):
                got = fetch_pdf(fetcher, f["url"])
                if got:
                    return got
    return None


def _data_to(name: str) -> Optional[str]:
    m = _DATA_TO.search(name)
    month = MONTHS_ES.get(m.group(2).lower().replace("é", "e")) if m else None
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1))).isoformat()
    except ValueError:
        return None


def informes(fetcher, size: int = 4) -> list[dict]:
    """Informes técnicos depositados, con la URL de su PDF y la fecha de corte que trae el nombre del archivo, en
    el formato de ``reports.informe_entries`` (``year``, ``n``, ``dataTo``, ``url``)."""
    out = []
    for it in search(fetcher, '"Informe Técnico ENFEN"', size):
        m = INFORME_TITLE.search(it["title"])
        if not m:
            continue
        for f in pdfs(fetcher, it["uuid"])[:1]:
            out.append({"url": f["url"], "year": int(m.group(3)), "n": int(m.group(2)), "dataTo": _data_to(f["name"]),
                        "page": it["page"]})
    return out


def informe_pdf(fetcher, year: int, number: int):
    """El PDF del informe técnico N° ``number`` de ``year``, solo si el título es exactamente ese número."""
    for it in search(fetcher, f'"Informe Técnico ENFEN" N°{number}, {year}', 5):
        m = INFORME_TITLE.search(it["title"])
        if m and (int(m.group(3)), int(m.group(2))) == (year, number):
            for f in pdfs(fetcher, it["uuid"]):
                got = fetch_pdf(fetcher, f["url"])
                if got:
                    return got
    return None
