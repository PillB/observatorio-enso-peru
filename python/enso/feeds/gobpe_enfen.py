"""Los comunicados oficiales y los informes técnicos del ENFEN en la plataforma del Estado (gob.pe): una ruta
oficial, pública y sin verificación humana que GitHub Actions sí alcanza.

El SENAMHI (miembro del ENFEN) publica cada comunicado y cada informe técnico como «publicación» en
https://www.gob.pe/institucion/senamhi/, el mismo día que el ENFEN (comunicado 20-2026 e informe N° 20: 13 de
noviembre de 2026), con el PDF en ``cdn.www.gob.pe/uploads/document/file/...``. Esos PDF son byte a byte los del
portal del ENFEN (los del 20-2026 tienen el mismo sha256 que las copias del recolector del Perú archivadas en la
rama data-archive). Hacía falta porque, desde noviembre de 2026, la réplica de la DHN manda cada
``/Archivos/...pdf`` a ``/human-check.php`` (Cloudflare Turnstile) y el portal del ENFEN y el repositorio del IMARPE
no responden fuera del Perú: sin esta ruta, el comunicado y el informe dependían solo del recolector del Perú.

Se lee una sola búsqueda en RSS (``LISTING_URL``: publicaciones del SENAMHI con «enfen», de la más reciente a la
más antigua; robots.txt de gob.pe solo prohíbe ``/admin/`` y las URL con ``sheet=``, y el del CDN solo
``/admin/``). Cada ítem trae el título («Comunicado Oficial ENFEN N°20 - 2026», «Informe Técnico del ENFEN
N°20-2026»), su página y, en ``<image>``, el PDF; si falta, se toma el primer PDF del CDN de la página del ítem.
El título solo elige el candidato: lo que se publica se valida igual que cualquier otra copia (que sea un PDF, el
número que trae el texto del comunicado y el periodo del informe). Una página de verificación antirobots en lugar
del RSS o del PDF se anota y nunca se evade.
"""

from __future__ import annotations

import html
import re
from email.utils import parsedate_to_datetime
from typing import Optional

from .imarpe_repo import Problem, cause

BASE = "https://www.gob.pe"
CDN = "https://cdn.www.gob.pe"
#: La búsqueda que lee el observatorio (y la que mide el registro de fuentes): publicaciones del SENAMHI que
#: nombran al ENFEN, la más reciente primero. 25 ítems: unos dos meses de comunicados e informes.
LISTING_URL = f"{BASE}/busquedas.rss?contenido[]=publicaciones&institucion[]=senamhi&term=enfen&sort_by=recent"
SOURCE = "gobpe-enfen"

COMMUNIQUE_TITLE = re.compile(r"\bComunicado\s+(?:Oficial\s+)?(?:del?\s+)?ENFEN\s+N\s*[°ºo.]*\s*(\d{1,2})\s*[-–]\s*(\d{4})\b",
                              re.I)
INFORME_TITLE = re.compile(r"\bInforme\s+T[ée]cnico\s+(?:del?\s+)?ENFEN\s+N\s*[°ºo.]*\s*(\d{1,2})\s*[-–]\s*(\d{4})\b", re.I)
_ITEM = re.compile(r"<item>(.*?)</item>", re.S)
_CDN_PDF = re.compile(r"https://cdn\.www\.gob\.pe/uploads/document/file/\d+/[^\"'<>\s?]+\.pdf", re.I)


def _tag(item: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", item, re.S)
    return html.unescape(m.group(1).strip()) if m else ""


def _published(item: str) -> Optional[str]:
    try:
        return parsedate_to_datetime(_tag(item, "pubDate")).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def parse_listing(text: str) -> list[dict]:
    """Comunicados oficiales e informes técnicos del RSS de gob.pe, en su orden: ``kind`` («comunicado» o
    «informe»), ``year``, ``number``, ``title``, ``page``, ``pdf`` (o ``None``) y ``published``. ``ValueError`` si
    la respuesta no es el RSS de la búsqueda (una búsqueda sin resultados igual lo es)."""
    if "<rss" not in text[:500] or "<channel>" not in text:
        raise ValueError("gob.pe: la búsqueda no devolvió su RSS")
    out = []
    for it in _ITEM.findall(text):
        title = re.sub(r"\s+", " ", _tag(it, "title"))
        if "extraordinari" in title.lower():
            continue  # otra numeración: el observatorio sigue la de los comunicados oficiales
        for kind, rx in (("comunicado", COMMUNIQUE_TITLE), ("informe", INFORME_TITLE)):
            m = rx.search(title)
            if m:
                pdf = _tag(it, "image")
                out.append({"kind": kind, "year": int(m.group(2)), "number": int(m.group(1)), "title": title,
                            "page": _tag(it, "link"), "pdf": pdf if _CDN_PDF.fullmatch(pdf) else None,
                            "published": _published(it)})
                break
    return out


def _cause(exc) -> Problem:
    """``imarpe_repo.cause`` y, si el ``Fetcher`` descartó una página de verificación (``class: challenge``),
    «verificación antirobots»: no es un corte de red y no se evade."""
    if any(a.get("class") == "challenge" for a in getattr(exc, "attempts", []) or []):
        return Problem("verificación antirobots")
    return cause(exc)


def is_gobpe(url: str) -> bool:
    """La URL es de gob.pe o de su CDN: una dirección oficial más del documento (canal «mirror», no «direct»)."""
    return bool(re.match(r"https://(cdn\.)?www\.gob\.pe/", url or ""))


def _note(problems: Optional[list], what: str, detail: str = "") -> None:
    if problems is not None and what not in problems:
        problems.append(Problem(what, detail) if detail else what)


def listing(fetcher, problems: Optional[list] = None, seen: Optional[list] = None) -> list[dict]:
    """``parse_listing`` del RSS, una vez por ``fetcher`` (lo piden el comunicado y el informe de la misma corrida).
    ``seen`` recibe ``(canal, archived_at)`` de la respuesta: así se sabe si el listado se leyó en vivo."""
    from ..fetch import FetchError, block_page

    cached = getattr(fetcher, "_gobpe_enfen", None)
    if cached is None:
        cached = {"items": [], "problem": None, "channel": None}
        try:
            r = fetcher.get([LISTING_URL], archive=False, accept=("xml", "rss", "html"))
            if block_page(r.body):
                cached["problem"] = ("verificación antirobots", "")
            else:
                cached["items"] = parse_listing(r.text)
                cached["channel"] = (r.channel, r.archived_at)
        except FetchError as exc:
            p = _cause(exc)
            cached["problem"] = (str(p), getattr(p, "detail", ""))
        except ValueError:
            cached["problem"] = ("formato", "")
        try:
            fetcher._gobpe_enfen = cached
        except AttributeError:
            pass
    if cached["problem"]:
        _note(problems, *cached["problem"])
    if seen is not None and cached["channel"]:
        seen.append(cached["channel"])
    return list(cached["items"])


def communiques(fetcher, problems: Optional[list] = None, seen: Optional[list] = None) -> list[dict]:
    """Comunicados oficiales publicados en gob.pe, en el formato del listado del ENFEN (``url``: su PDF del CDN o,
    sin él, la página del ítem)."""
    return [{"year": i["year"], "number": i["number"], "kind": "oficial", "id": f"{i['number']:02d}-{i['year']}",
             "url": i["pdf"] or i["page"], "gobpe": i["page"], **({"published": i["published"]} if i["published"] else {})}
            for i in listing(fetcher, problems, seen) if i["kind"] == "comunicado"]


def informes(fetcher, problems: Optional[list] = None) -> list[dict]:
    """Informes técnicos publicados en gob.pe, en el formato de ``reports.informe_entries`` (sin fecha de corte:
    ``pick_informe`` toma el de número más alto del año y la validación descarta uno de otro periodo)."""
    return [{"url": i["pdf"] or i["page"], "year": i["year"], "n": i["number"], "dataTo": None, "page": i["page"]}
            for i in listing(fetcher, problems) if i["kind"] == "informe"]


def _pdf(fetcher, item: dict, problems: Optional[list]):
    """El PDF del ítem (``Response`` con canal «mirror» y ``page``: la página del ítem en gob.pe) o ``None``."""
    from ..fetch import FetchError, block_page

    urls = [item["pdf"]] if item.get("pdf") else []
    if not urls and item.get("page"):
        try:
            page = fetcher.get([item["page"]], archive=False, accept=("html",))
            urls = list(dict.fromkeys(_CDN_PDF.findall(page.text)))[:1]
        except FetchError as exc:
            _note(problems, str(_cause(exc)))
            return None
    for url in urls:
        try:
            r = fetcher.get([url], archive=False, accept=("pdf", "octet-stream"))
        except FetchError as exc:
            p = _cause(exc)
            _note(problems, str(p), getattr(p, "detail", ""))
            continue
        if r.body[:5] != b"%PDF-":
            _note(problems, "verificación antirobots" if block_page(r.body) else "formato")
            continue
        if r.channel == "direct":
            r.channel = "mirror"  # otra dirección oficial del mismo documento
        r.page = item.get("page")
        return r
    return None


def communique_pdf(fetcher, year: int, number: int, problems: Optional[list] = None):
    """El PDF del comunicado oficial N° ``number``-``year`` si gob.pe lo lista con ese número exacto y el texto del PDF
    lo confirma: un ítem con otro archivo adjunto (en 2023, «Comunicado ENFEN N° 15» traía el informe técnico) no tapa
    las rutas siguientes."""
    from .peru import NUMBER_RE, pdf_text

    for i in listing(fetcher, problems):
        if i["kind"] == "comunicado" and (i["year"], i["number"]) == (year, number):
            got = _pdf(fetcher, i, problems)
            if got is None:
                continue
            try:
                m = NUMBER_RE.search(re.sub(r"\s+", " ", pdf_text(got.body)[:4000]))
            except Exception:  # noqa: BLE001 — un PDF que no se lee lo descarta el lector, no este módulo
                return got
            if m and (int(m.group(2)), int(m.group(1))) == (year, number):
                return got
            _note(problems, "otro documento")
    return None


def informe_pdf(fetcher, year: int, number: int, problems: Optional[list] = None):
    """El PDF del informe técnico N° ``number`` de ``year`` si gob.pe lo lista con ese número exacto."""
    for i in listing(fetcher, problems):
        if i["kind"] == "informe" and (i["year"], i["number"]) == (year, number):
            got = _pdf(fetcher, i, problems)
            if got:
                return got
    return None


def log_problems(log, problems: list, what: str) -> None:
    """Una advertencia por causa mientras dure: ``gobpe-unreachable`` (red, HTTP o una verificación antirobots, que
    no se evade) o ``gobpe-format`` (respondió otra cosa que el RSS o el PDF)."""
    for p in problems:
        detail = getattr(p, "detail", "")
        if p == "otro documento":
            log.add("warning", SOURCE, "validate", "gobpe-format",
                    f"gob.pe lista {what} con un PDF que no es el comunicado del título: no se usa.")
            continue
        hint = (" gob.pe empezó a pedir verificación humana: no se evade; quedan la réplica de la DHN y las copias del "
                "recolector del Perú." if p == "verificación antirobots" else
                " Revisar python/enso/feeds/gobpe_enfen.py (LISTING_URL y parse_listing)." if p == "formato" else "")
        log.add("warning", SOURCE, "fetch", "gobpe-format" if p == "formato" else "gobpe-unreachable",
                f"gob.pe (publicaciones del SENAMHI) no sirvió {what} ({p}{f': {detail}' if detail else ''}).{hint}")
