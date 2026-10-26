"""Repositorio institucional del IMARPE (DSpace 8, https://repositorio.imarpe.gob.pe): una ruta oficial y sin
verificación humana para los documentos del ENFEN.

El IMARPE (miembro del ENFEN) deposita cada comunicado oficial y cada informe técnico, unos días después de su
publicación (el comunicado 18-2026, emitido el 16 de octubre, entró el 19). A diferencia de la réplica de la DHN,
su API REST no pide verificación humana; pero, como el portal del ENFEN, no responde a GitHub Actions (las
incidencias dicen «conexión»). El recolector del Perú (``tools.peru_collector.imarpe_repository``) baja las mismas
búsquedas, paquetes y PDF, con las URL exactas de este módulo (``search_url``, ``communique_search_url``,
``informe_search_url``, ``bundles_url`` y la de cada PDF), y el ``Fetcher`` las toma de esa copia cuando la red no
llega. robots.txt prohíbe la búsqueda de la interfaz (``/search``), no la API (``/server/api``).

El servidor envía solo su certificado, sin el intermedio de Sectigo: ``enso.fetch.ssl_context`` lo agrega.

Es el único cliente del repositorio: lo usan el comunicado y el informe técnico (``enso.observatory``,
``enso.reports``) y el boletín BS-OBP (``imarpe_bsobp``), y puede usarlo cualquier otro lector con su propia
búsqueda (``search``). Todo pasa por el ``Fetcher`` compartido (plan, tiempo y copias de los recolectores). Lo que
se baja de aquí se valida igual que cualquier otra copia: el número y el periodo del documento, y que sea un PDF.
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


def cause(exc) -> str:
    """Causa corta de una falla del repositorio, para la incidencia: «tls» (el certificado no se pudo verificar:
    revisar ``enso/data/ca-intermedios.pem``), «http-<código>», «conexión» o «formato» (respondió otra cosa)."""
    if isinstance(exc, ValueError):
        return "formato"
    errors = [str(a.get("error", "")) for a in getattr(exc, "attempts", []) or []]
    if any("CERTIFICATE_VERIFY_FAILED" in e or "SSLError" in e or "certificate" in e.lower() for e in errors):
        return "tls"
    codes = [a["status"] for a in getattr(exc, "attempts", []) or [] if isinstance(a.get("status"), int)]
    if codes:
        return f"http-{codes[-1]}"
    return "conexión"


def _note(problems: Optional[list], what: str) -> None:
    if problems is not None and what not in problems:
        problems.append(what)


def _get_json(fetcher, url: str, problems: Optional[list] = None) -> Optional[dict]:
    """JSON de la API. Toda falla vuelve ``None`` y deja su causa en ``problems`` (si se pasa): el que llama la
    convierte en incidencia, para que una ruta caída no pase en silencio."""
    from ..fetch import FetchError

    try:
        r = fetcher.get([url], archive=False, accept=("json",))
        data = json.loads(r.text)
    except (FetchError, ValueError) as exc:
        _note(problems, cause(exc))
        return None
    if not isinstance(data, dict):
        _note(problems, "formato")
        return None
    return data


def _meta(item: dict, key: str) -> Optional[str]:
    vals = (item.get("metadata") or {}).get(key) or []
    return vals[0].get("value") if vals and isinstance(vals[0], dict) else None


def search_url(query: str, size: int = 10) -> str:
    """URL de la búsqueda de la API (la que pide ``search``): el registro de fuentes y la sonda usan la misma."""
    params = urlencode({"query": query, "dsoType": "ITEM", "size": size, "sort": "dc.date.issued,DESC"})
    return f"{API}/discover/search/objects?{params}"


#: Búsquedas que hacen los lectores del ENFEN (comunicados e informes técnicos), con su tamaño.
COMMUNIQUE_QUERY = '"Comunicado Oficial ENFEN"'
INFORME_QUERY = '"Informe Técnico ENFEN"'


def listing_urls() -> list[str]:
    """Las URL de listado que el observatorio pide al repositorio (``communiques`` e ``informes``), para el
    registro de fuentes y el recolector del Perú."""
    return [search_url(COMMUNIQUE_QUERY, 6), search_url(INFORME_QUERY, 4)]


def communique_id(title: str) -> Optional[tuple[int, int]]:
    """(año, número) del comunicado oficial que nombra el título de un ítem; ``None`` si no es uno."""
    m = COMMUNIQUE_TITLE.search(title)
    return (int(m.group(2)), int(m.group(1))) if m else None


def informe_id(title: str) -> Optional[tuple[int, int]]:
    """(año, número) del informe técnico que nombra el título de un ítem; ``None`` si no es uno."""
    m = INFORME_TITLE.search(title)
    return (int(m.group(3)), int(m.group(2))) if m else None


def communique_search_url(year: int, number: int) -> str:
    """La búsqueda con que ``communique_pdf`` encuentra un comunicado (el recolector del Perú pide la misma)."""
    return search_url(f"{COMMUNIQUE_QUERY} {number:02d}-{year}", 5)


def informe_search_url(year: int, number: int) -> str:
    """La búsqueda con que ``informe_pdf`` encuentra un informe técnico (el recolector del Perú pide la misma)."""
    return search_url(f"{INFORME_QUERY} N°{number}, {year}", 5)


def bundles_url(uuid: str) -> str:
    """Los paquetes de archivos de un ítem, con sus archivos (``pdfs``)."""
    return f"{API}/core/items/{uuid}/bundles?embed=bitstreams"


def parse_search(data: dict) -> list[dict]:
    """Los ítems de una respuesta de la búsqueda: uuid, título, fecha y su página. ``KeyError``/``TypeError`` si
    la respuesta no tiene la forma de la búsqueda de DSpace (una búsqueda sin resultados igual la tiene)."""
    out = []
    for o in data["_embedded"]["searchResult"]["_embedded"]["objects"]:
        it = (o.get("_embedded") or {}).get("indexableObject") or {}
        if not it.get("uuid"):
            continue
        handle = it.get("handle")
        out.append({"uuid": it["uuid"], "title": _meta(it, "dc.title") or "", "issued": _meta(it, "dc.date.issued"),
                    "page": f"{BASE}/handle/{handle}" if handle else f"{BASE}/items/{it['uuid']}"})
    return out


def parse_bundles(data: dict) -> list[dict]:
    """Los PDF del paquete ORIGINAL de una respuesta de ``bundles_url``: nombre, tamaño y URL del contenido.
    ``KeyError``/``TypeError`` si no tiene la forma de DSpace."""
    out = []
    for b in data["_embedded"]["bundles"]:
        if b.get("name") != "ORIGINAL":
            continue
        for x in (((b.get("_embedded") or {}).get("bitstreams") or {}).get("_embedded") or {}).get("bitstreams") or []:
            href = ((x.get("_links") or {}).get("content") or {}).get("href")
            if href and (x.get("name") or "").lower().endswith(".pdf"):
                out.append({"name": x["name"], "size": x.get("sizeBytes"), "url": href})
    return out


def search(fetcher, query: str, size: int = 10, problems: Optional[list] = None, url: Optional[str] = None) -> list[dict]:
    """Ítems más recientes (por fecha de emisión) que responden a ``query`` (o a la búsqueda ``url``): uuid,
    título, fecha y su página."""
    data = _get_json(fetcher, url or search_url(query, size), problems)
    if data is None:
        return []
    try:
        return parse_search(data)
    except (KeyError, TypeError, AttributeError):
        # 200 con otro JSON: la API cambió de forma. Una búsqueda sin resultados igual trae esta ruta.
        _note(problems, "formato")
        return []


def pdfs(fetcher, uuid: str, problems: Optional[list] = None) -> list[dict]:
    """Archivos PDF del ítem (paquete ORIGINAL): nombre, tamaño y URL del contenido."""
    data = _get_json(fetcher, bundles_url(uuid), problems)
    if data is None:
        return []
    try:
        return parse_bundles(data)
    except (KeyError, TypeError, AttributeError):
        _note(problems, "formato")
        return []


def fetch_pdf(fetcher, url: str, problems: Optional[list] = None):
    """El PDF (``Response`` con canal «mirror»: otra dirección oficial) o ``None`` si no es un PDF."""
    from ..fetch import FetchError

    try:
        r = fetcher.get([url], archive=False, accept=("pdf", "octet-stream"))
    except FetchError as exc:
        _note(problems, cause(exc))
        return None
    if r.body[:5] != b"%PDF-":
        _note(problems, "formato")
        return None
    if r.channel == "direct":
        r.channel = "mirror"
    return r


def communiques(fetcher, size: int = 6, problems: Optional[list] = None) -> list[dict]:
    """Comunicados oficiales depositados, del más reciente al más antiguo, en el formato del listado del ENFEN."""
    out = []
    for it in search(fetcher, COMMUNIQUE_QUERY, size, problems):
        got = communique_id(it["title"])
        if got:
            y, n = got
            out.append({"year": y, "number": n, "kind": "oficial", "id": f"{n:02d}-{y}", "url": it["page"],
                        "repository": it["uuid"], "issued": it["issued"]})
    return out


def communique_pdf(fetcher, year: int, number: int, problems: Optional[list] = None):
    """El PDF del comunicado N° ``number``-``year``, solo si el título del ítem es exactamente ese número."""
    for it in search(fetcher, "", problems=problems, url=communique_search_url(year, number)):
        if communique_id(it["title"]) == (year, number):
            for f in pdfs(fetcher, it["uuid"], problems):
                got = fetch_pdf(fetcher, f["url"], problems)
                if got:
                    got.page = it["page"]
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


def informes(fetcher, size: int = 4, problems: Optional[list] = None) -> list[dict]:
    """Informes técnicos depositados, con la URL de su PDF y la fecha de corte que trae el nombre del archivo, en
    el formato de ``reports.informe_entries`` (``year``, ``n``, ``dataTo``, ``url``)."""
    out = []
    for it in search(fetcher, INFORME_QUERY, size, problems):
        got = informe_id(it["title"])
        if not got:
            continue
        for f in pdfs(fetcher, it["uuid"], problems)[:1]:
            out.append({"url": f["url"], "year": got[0], "n": got[1], "dataTo": _data_to(f["name"]),
                        "page": it["page"]})
    return out


def informe_pdf(fetcher, year: int, number: int, problems: Optional[list] = None):
    """El PDF del informe técnico N° ``number`` de ``year``, solo si el título es exactamente ese número."""
    for it in search(fetcher, "", problems=problems, url=informe_search_url(year, number)):
        if informe_id(it["title"]) == (year, number):
            for f in pdfs(fetcher, it["uuid"], problems):
                got = fetch_pdf(fetcher, f["url"], problems)
                if got:
                    got.page = it["page"]
                    return got
    return None


def log_problems(log, problems: list, what: str) -> None:
    """Una advertencia por causa mientras dure (``repository-unreachable`` o ``repository-format``): la incidencia
    queda abierta hasta que el repositorio vuelva a responder bien."""
    for p in problems:
        code = "repository-format" if p == "formato" else "repository-unreachable"
        hint = (" Revisar la cadena con `openssl s_client -showcerts -connect repositorio.imarpe.gob.pe:443` y "
                "actualizar python/enso/data/ca-intermedios.pem." if p == "tls" else
                " La API respondió algo que no es la búsqueda de DSpace: revisar python/enso/feeds/imarpe_repo.py."
                if p == "formato" else "")
        log.add("warning", "imarpe-repositorio", "fetch", code,
                f"El repositorio del IMARPE no sirvió {what} ({p}).{hint}")
