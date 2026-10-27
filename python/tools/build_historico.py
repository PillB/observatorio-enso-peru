"""Construye el catálogo histórico de desastres y lo publica para la pestaña «Memoria de desastres».

Pasos (todos reproducibles; ``docs/memoria-desastres.md``):

1. Descarga cada fuente de ``data/historico/fuentes.json`` a una caché local (``--cache``) y comprueba
   su SHA-256. Si la fuente cambió, se avisa y no se sigue sin ``--aceptar-cambios`` (que actualiza el
   manifiesto): así un cambio silencioso de la fuente no altera el catálogo publicado.
2. Lee cada fuente con su lector (``enso.historico.desinventar`` para 1970-2015,
   ``enso.historico.fuentes`` para el SINPAD desde 2016, IDMC 2019-2026 y NASA, registros curados en
   ``data/historico/curado/*.yaml``) y normaliza todo a ``enso.historico.esquema.COLUMNS``. Las capas de
   contexto (INGEMMET, ANA, establecimientos de salud) no son eventos: se resumen por distrito.
3. Ubica cada registro en su UBIGEO vigente y le asigna la fase ENSO del mes (ICEN y ONI).
3b. Une a esas filas los reportes del COEN, los desbordes de lagunas glaciares, las notas de prensa y las páginas de
   periódicos antiguos digitalizados que cuentan el mismo evento (``enso.historico.enlace.link``, en el orden de
   ``LINK_ORDER``: suman su enlace y, del COEN, las cifras de daños); los que no corresponden a ninguna quedan como
   filas propias. Junta las declaratorias de
   emergencia (El Peruano), las evaluaciones técnicas del peligro (INGEMMET, IGP), el inventario de peligros con
   fecha (INGEMMET) y los llamamientos de la Cruz Roja para los indicadores de prevención (``enlace.prevention``).
4. Escribe:
   * ``public/assets/historico/eventos.zip``: el catálogo completo en ``eventos.csv``, con las 13 columnas
     del equipo de prevención primero (UTF-8 con BOM para que Excel lea las tildes).
   * ``public/assets/historico/eventos.json``: versión compacta para el navegador.
   * ``public/assets/historico/detalle/<departamento>.json``: descripción, lugar y fuente de cada registro,
     que el sitio pide solo al abrir un área.
   * ``public/assets/historico/resumen.json``: cobertura, fuentes, calendario ENSO, nombres y atributos
     de cada área.
   * ``public/assets/historico/contexto.json`` y ``data/historico/contexto-distrito.csv``: peligro
     identificado hoy en cada distrito (zonas críticas, puntos críticos de ríos y quebradas) junto con
     su historial.
   * ``data/historico/indicadores-<nivel>.csv``: los indicadores de recurrencia por área.
   * ``public/assets/historico/prevencion.json`` y ``data/historico/prevencion-distrito.csv``: declaratorias,
     evaluaciones y eventos ocurridos cuando el peligro ya se conocía, por distrito y por año.
   Los CSV de ``data/historico/`` se copian también en ``public/assets/historico/`` para descargarlos
   desde el sitio.

Uso:
    python -m tools.build_historico                      # con la caché en ~/.cache/enso-historico
    python -m tools.build_historico --aceptar-cambios    # tras revisar un cambio de una fuente
    python -m tools.build_historico --cache A --cache B  # busca cada archivo en varias cachés
    python -m tools.build_historico --parcial            # usa lo bajado de una cosecha larga que sigue a medias
    python -m tools.build_historico --indices-al-dia D   # con el ICEN y el ONI de hoy (si no, los de las pruebas)
    python -m tools.build_historico --desde-catalogo     # solo recalcula indicadores, validación y diccionario
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx
import yaml

from enso.fetch import ssl_context
from enso.historico import cosecha as C, desinventar, enlace, esquema as E, fuentes as F
from enso.historico.enso import GREAT, NAMED, PIRCC_2017_URL, EnsoCalendar
from enso.historico import validacion as V
from enso.historico.indicadores import by_area, nino_hydro_years, nino_hydro_years_any, peak_icen
from enso.historico.registro import make
from enso.historico.territorio import Territory
from enso.observatory import csv_safe
from enso.reach import Robots, public_peru

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "historico"
MANIFEST = DATA / "fuentes.json"
CURATED = DATA / "curado"
OUT = ROOT / "public" / "assets" / "historico"
FIX = ROOT / "python" / "tests" / "fixtures" / "sources"
CACHE = Path.home() / ".cache" / "enso-historico"
REPO = "github.com/PillB/observatorio-enso-peru"
UA = {"User-Agent": f"observatorio-enso-peru (catalogo historico; https://{REPO})"}  # solo ASCII
#: Índices ENSO vigentes (los mismos que lee el observatorio, ``enso.observatory``) y su copia en las pruebas.
INDICES = {"icen": ("http://met.igp.gob.pe/datos/ICEN.txt", FIX / "igp-icen.txt"),  # por https no responde
           "oni": ("https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt", FIX / "cpc-oni.txt")}

#: Lectores de eventos: (archivo descargado, territorio, calendario, contador de descartes) → filas.
READERS = {
    "desinventar": lambda path, t, c, sk: desinventar.records(desinventar.read_export(path), t, c),
    "sinpad": lambda path, t, c, sk: F.sinpad(json.loads(path.read_text(encoding="utf-8")), t, c, skipped=sk),
    "sinpad-api": lambda path, t, c, sk: F.sinpad_api(json.loads(path.read_text(encoding="utf-8")), t, c, skipped=sk),
    "idmc-idu": lambda path, t, c, sk: F.idmc_idu(path.read_text(encoding="utf-8"), t, c, skipped=sk),
    "idmc-eventos": lambda path, t, c, sk: F.idmc_events(path.read_text(encoding="utf-8"), t, c, skipped=sk),
    "nasa-glc": lambda path, t, c, sk: F.glc(json.loads(path.read_text(encoding="utf-8")), t, c, skipped=sk),
}
#: Candidatos de la segunda ronda (``enso.historico.cosecha``): no se suman tal cual, se unen a las filas que
#: cuentan el mismo evento (``enlace.link``) o quedan como filas propias.
CANDIDATES = {
    "coen": lambda path, t, c, sk, src: C.coen(json.loads(path.read_text(encoding="utf-8")), t, c, skipped=sk),
    "prensa": lambda path, t, c, sk, src: C.press(json.loads(path.read_text(encoding="utf-8")), t, c, outlet=src["medio"],
                                               departments=src.get("departamentos"), skipped=sk),
    "glof": lambda path, t, c, sk, src: C.glof(C.ods_rows(path.read_bytes()), t, c, url=src["pagina"], skipped=sk),
    "hemeroteca": lambda path, t, c, sk, src: C.hemeroteca(json.loads(path.read_text(encoding="utf-8")), t, c,
                                                           archive=src["medio"], skipped=sk),
}
#: Orden de la unión: el COEN y los GLOF antes que la prensa, para que una nota corrobore lo que solo ellos registran;
#: los periódicos antiguos al final (sus páginas reimprimen el mismo cable: la primera queda, las demás corroboran).
LINK_ORDER = ("coen", "glof", "prensa", "hemeroteca")
#: Evidencia para los indicadores de prevención: declaratorias de emergencia y evaluaciones del peligro.
EVIDENCE = {
    "decretos": lambda doc, t, src: C.decrees(doc, t),
    "evaluaciones-dspace": lambda doc, t, src: C.evaluations_dspace(doc, t, src.get("institucion", "INGEMMET")),
    "evaluaciones-geocatmin": lambda doc, t, src: C.evaluations_geocatmin(doc, t, src["url"]),
    "evaluaciones-oai": lambda doc, t, src: C.evaluations_oai(doc, t, src.get("institucion", "IGP")),
    "inventario-fechado": lambda doc, t, src: C.inventory_dated(doc, t, src["url"]),
    "llamamientos": lambda doc, t, src: C.appeals(doc),
}
#: En qué lista de evidencia va cada lector (las demás son evaluaciones del peligro).
EVIDENCE_KIND = {"decretos": "decretos", "llamamientos": "llamamientos"}
#: Capas de contexto por distrito.
CONTEXT = {
    "ingemmet-inventario": F.ingemmet_inventory, "ingemmet-criticas": F.ingemmet_critical,
    "ana-puntos": F.ana_points, "ipress-2023": F.ipress_2023,
}

#: Columnas compactas de eventos.json (en este orden).
WEB_COLS = ["Date", "DangerType", "Ubigeo", "TipoEvento", "FaseENSO", "Origen", "Confianza",
            "Muertos", "Afectados", "Viviendas", "i"]


# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_atomic(path: Path, data) -> None:
    """Escribe ``path`` de una vez (un archivo temporal al lado y ``os.replace``): una descarga cortada en medio de
    una escritura (la cosecha de GitHub Actions corta las suyas al vencer su plazo) no deja un archivo a medias, que
    al retomarla no se podría leer."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    os.replace(tmp, path)


def arcgis_dump(url: str, fields: str = "*", geometry: bool = True, where: str = "1=1", delay: float = 0.5) -> bytes:
    """Todos los elementos de una capa de ArcGIS REST (MapServer o FeatureServer) como JSON canónico:
    pide los OBJECTID y luego bloques de 1 000 por rango, ordena y serializa con claves ordenadas, para
    que el SHA-256 solo cambie si cambian los datos."""
    import time

    def get(c: httpx.Client, path: str, **params) -> dict:
        r = c.get(url + path, params={"f": "json", **params})
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise SystemExit(f"{url}: {d['error']}")
        return d

    with httpx.Client(follow_redirects=True, timeout=180, headers=UA, verify=ssl_context()) as c:
        meta = get(c, "")
        oid = next(f["name"] for f in meta["fields"] if f["type"] == "esriFieldTypeOID")
        ids = sorted(get(c, "/query", where=where, returnIdsOnly="true")["objectIds"] or [])
        feats = []
        for i in range(0, len(ids), 1000):
            a, b = ids[i], ids[min(i + 999, len(ids) - 1)]
            d = get(c, "/query", where=f"({where}) AND {oid}>={a} AND {oid}<={b}", outFields=fields, outSR="4326",
                    returnGeometry="true" if geometry else "false")
            feats += d["features"]
            time.sleep(delay)
    if len(feats) != len(ids):
        raise SystemExit(f"{url}: se esperaban {len(ids)} elementos y llegaron {len(feats)}")
    feats.sort(key=lambda f: f["attributes"][oid])
    return json.dumps({"source": url, "where": where, "features": feats}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def idmc_api(src: dict, delay: float = 1.0) -> bytes:
    """Filas del Perú de la API del IDMC, como CSV con columnas y filas ordenadas (el SHA-256 solo cambia si
    cambian los datos). La clave (``client_id``) se lee de ``IDMC_CLIENT_ID`` y nunca se guarda ni se muestra:
    va en la consulta, así que los errores no citan la URL."""
    import time

    key = os.environ.get("IDMC_CLIENT_ID", "").strip()
    if not key:
        raise SystemExit(f"{src['id']}: falta la variable IDMC_CLIENT_ID. {src['clave']}")
    rows: list[dict] = []
    url: Optional[str] = src["url"]
    params: Optional[dict] = {"client_id": key, **src.get("parametros", {})}
    with httpx.Client(follow_redirects=True, timeout=300, headers=UA, verify=ssl_context()) as c:
        while url:
            try:
                r = c.get(url, params=params)
            except httpx.HTTPError as e:
                raise SystemExit(f"{src['id']}: la API del IDMC no respondió ({type(e).__name__})") from None
            if r.status_code != 200:
                raise SystemExit(f"{src['id']}: la API del IDMC respondió HTTP {r.status_code}")
            d = r.json()
            page = d.get("results", []) if isinstance(d, dict) else d
            rows += [x for x in page if (x.get("iso3") or "PER") == "PER"]
            # La página siguiente ya trae todos los parámetros (también la clave).
            url, params = (d.get("next"), None) if isinstance(d, dict) else (None, None)
            if url:
                time.sleep(delay)
    if not rows:
        raise SystemExit(f"{src['id']}: la API del IDMC no devolvió filas del Perú")
    cols = sorted({k for x in rows for k in x})
    text = lambda v: "" if v is None else str(v)  # noqa: E731
    rows.sort(key=lambda x: [text(x.get(k)) for k in ("id", "start_date", "event_name", *cols)])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    w.writerows([text(x.get(k)) for k in cols] for x in rows)
    return buf.getvalue().encode("utf-8")


def _months(start: date, end: date):
    """(primer día, último día) de cada mes entre ``start`` y ``end``, recortados a ese intervalo."""
    a = start
    while a <= end:
        nxt = date(a.year + a.month // 12, a.month % 12 + 1, 1)
        yield a, min(end, nxt - timedelta(days=1))
        a = nxt


def sinpad_api(src: dict, parts: Path, delay: float = 5.0, until: Optional[date] = None) -> bytes:
    """Emergencias del portal público del SINPAD (INDECI) desde ``parametros.desde``, mes por mes y en
    páginas de 100 (lo más que ofrece el portal), como JSON canónico ordenado por código: el SHA-256 solo
    cambia si cambian los datos.

    Son unas 1 400 páginas, así que cada mes terminado se guarda en ``parts`` y una descarga cortada sigue
    donde quedó (con la misma fecha de corte). Las páginas van de la emergencia más nueva a la más vieja:
    una registrada mientras se pagina solo repite una fila, que se descarta. Si a un mes le faltan filas
    respecto del total que anunció, se pide de nuevo una vez y, si siguen faltando, se detiene."""
    import time

    p = src.get("parametros", {})
    size = int(p.get("pageSize", 100))
    parts.mkdir(parents=True, exist_ok=True)
    state = parts / "corte.json"
    if state.exists():
        end = date.fromisoformat(json.loads(state.read_text(encoding="utf-8"))["hasta"])
    else:
        end = until or datetime.now(F.LIMA).date()
        write_atomic(state, json.dumps({"hasta": end.isoformat()}))
    start = date.fromisoformat(p.get("desde", "2019-01-01"))
    last = [0.0]

    def get(c: httpx.Client, params: dict) -> dict:
        for attempt in range(4):
            time.sleep(max(0.0, last[0] + delay * (1 + 2 * attempt) - time.monotonic()))
            last[0] = time.monotonic()
            try:
                r = c.get(src["url"], params=params)
            except httpx.HTTPError as e:
                why = type(e).__name__
            else:
                if r.status_code != 200:
                    why = f"HTTP {r.status_code}"
                    if r.status_code != 429 and r.status_code < 500:
                        break
                else:
                    try:
                        d = r.json()
                    except ValueError:
                        why = "una página que no es JSON (¿verificación antirobots?)"
                        break  # no se insiste ante una verificación
                    if d.get("status") == 200:
                        return d["data"]
                    why = f"estado {d.get('status')}"
            print(f"  {src['id']}: {why}, se reintenta", file=sys.stderr)
        raise SystemExit(f"{src['id']}: el SINPAD respondió {why} a {params}")

    items: dict[int, dict] = {}
    with httpx.Client(follow_redirects=True, timeout=120, headers=UA, verify=ssl_context()) as c:
        for a, b in _months(start, end):
            part = parts / f"{a:%Y-%m}.json"
            if part.exists():
                got = {x["codigoSinpad"]: x for x in json.loads(part.read_text(encoding="utf-8"))}
            else:
                for _ in range(2):
                    got, page, pages, total = {}, 1, 1, None
                    while page <= pages:
                        d = get(c, {"fechaInicio": f"{a:%d/%m/%Y}", "fechaFin": f"{b:%d/%m/%Y}",
                                    "pageNumber": page, "pageSize": size})
                        total = d["page"]["totalElements"] if total is None else total
                        pages = d["page"]["totalPages"]
                        got.update((x["codigoSinpad"], x) for x in d["items"])
                        page += 1
                    if len(got) >= total:
                        break
                else:
                    raise SystemExit(f"{src['id']}: {a:%Y-%m} anunció {total} emergencias y llegaron {len(got)}")
                write_atomic(part, json.dumps(list(got.values()), ensure_ascii=False))
                print(f"  {src['id']}: {a:%Y-%m}: {len(got)} emergencias", file=sys.stderr)
            items.update(got)
    out = json.dumps({"source": src["url"], "desde": start.isoformat(), "hasta": end.isoformat(),
                      "items": [items[k] for k in sorted(items)]},
                     ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return out


OAI = "{http://www.openarchives.org/OAI/2.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"


def oai_pmh(src: dict, delay: float = 5.0) -> bytes:
    """Metadatos Dublin Core de un repositorio institucional (OAI-PMH ``ListRecords``, con el ``set`` y el
    ``metadataPrefix`` de ``parametros``), página por página con su ``resumptionToken``, como JSON canónico
    ordenado por identificador. Los registros borrados no se guardan. Un documento que declara entidades XML
    no se lee (riesgo de expansión), igual que en ``enso.feedparse``."""
    import time
    from xml.etree import ElementTree as ET

    p = dict(src.get("parametros", {}))
    params = {"verb": "ListRecords", "metadataPrefix": p.pop("metadataPrefix", "oai_dc"), **p}
    records: dict[str, dict] = {}
    last = [0.0]
    with httpx.Client(follow_redirects=True, timeout=180, headers=UA, verify=ssl_context()) as c:
        while True:
            for attempt in range(4):
                time.sleep(max(0.0, last[0] + delay * (1 + 2 * attempt) - time.monotonic()))
                last[0] = time.monotonic()
                try:
                    r = c.get(src["url"], params=params)
                except httpx.HTTPError as e:
                    why = type(e).__name__
                    continue
                why = f"HTTP {r.status_code}"
                if r.status_code == 200 or (r.status_code != 429 and r.status_code < 500):
                    break
                print(f"  {src['id']}: {why}, se reintenta", file=sys.stderr)
            if r.status_code != 200:
                raise SystemExit(f"{src['id']}: el repositorio respondió {why}")
            if b"<!ENTITY" in r.content[:4096] or b"<OAI-PMH" not in r.content[:4096]:
                raise SystemExit(f"{src['id']}: la respuesta no es un documento OAI-PMH")
            root = ET.fromstring(r.content)
            err = root.find(f"{OAI}error")
            if err is not None:
                if err.get("code") == "noRecordsMatch":
                    break
                raise SystemExit(f"{src['id']}: error OAI-PMH {err.get('code')}: {err.text}")
            lst = root.find(f"{OAI}ListRecords")
            for rec in lst.findall(f"{OAI}record"):
                h = rec.find(f"{OAI}header")
                ident = h.findtext(f"{OAI}identifier")
                if h.get("status") == "deleted":
                    records.pop(ident, None)
                    continue
                dc: dict[str, list] = defaultdict(list)
                md = rec.find(f"{OAI}metadata")
                for el in (md.iter() if md is not None else ()):
                    if el.tag.startswith(DC) and (el.text or "").strip():
                        dc[el.tag[len(DC):]].append(el.text.strip())
                records[ident] = {"id": ident, "datestamp": h.findtext(f"{OAI}datestamp"),
                                  "sets": sorted(s.text for s in h.findall(f"{OAI}setSpec")), "dc": dict(sorted(dc.items()))}
            token = lst.find(f"{OAI}resumptionToken")
            print(f"  {src['id']}: {len(records)} registros", file=sys.stderr)
            if token is None or not (token.text or "").strip():
                break
            params = {"verb": "ListRecords", "resumptionToken": token.text.strip()}
    return json.dumps({"source": src["url"], "parametros": src.get("parametros", {}),
                       "records": [records[k] for k in sorted(records)]},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def dspace_items(src: dict, parts: Path, delay: float = 5.0) -> bytes:
    """Metadatos completos de cada ítem de una colección de un repositorio DSpace 6 (JSPUI), para cuando su
    OAI-PMH no sirve (el del INGEMMET responde «noRecordsMatch» desde la segunda página): primero la lista de
    la colección por fecha (``…/browse?type=dateissued``, de 100 en 100) y después la ficha completa de cada
    ítem (``?mode=full``), una por pedido. Cada ficha leída se guarda en ``parts`` y una descarga cortada sigue
    donde quedó. Devuelve JSON canónico ordenado por handle."""
    import html as H
    import re
    import time

    base = src["url"].rstrip("/")
    root = "{0.scheme}://{0.netloc}".format(urlsplit(base))
    parts.mkdir(parents=True, exist_ok=True)
    last = [0.0]

    def get(c: httpx.Client, url: str) -> str:
        for attempt in range(4):
            time.sleep(max(0.0, last[0] + delay * (1 + 2 * attempt) - time.monotonic()))
            last[0] = time.monotonic()
            try:
                r = c.get(url)
            except httpx.HTTPError as e:
                why = type(e).__name__
                continue
            why = f"HTTP {r.status_code}"
            if r.status_code == 200 and "<html" in r.text[:2000].lower():
                return r.text
            if r.status_code != 429 and r.status_code < 500:
                break
            print(f"  {src['id']}: {why}, se reintenta", file=sys.stderr)
        raise SystemExit(f"{src['id']}: {url} respondió {why}")

    listing = parts / "lista.json"
    with httpx.Client(follow_redirects=True, timeout=120, headers=UA, verify=ssl_context()) as c:
        if listing.exists():
            handles = json.loads(listing.read_text(encoding="utf-8"))
        else:
            handles, offset, total = [], 0, None
            while total is None or offset < total:
                t = get(c, f"{base}/browse?type=dateissued&sort_by=2&order=ASC&rpp=100&offset={offset}")
                m = re.search(r"(?:Showing results|Mostrando resultados) \d+ (?:to|a) \d+ (?:of|de) (\d+)", t)
                total = int(m.group(1)) if m else 0
                found = dict.fromkeys(re.findall(r'<a href="(/handle/[\d.]+/\d+)">', t))  # el título de cada fila
                handles += [h for h in found if h not in handles]
                offset += 100
                print(f"  {src['id']}: lista {len(handles)} de {total}", file=sys.stderr)
            write_atomic(listing, json.dumps(handles))
        field = re.compile(r'<label class="metadataFieldLabel">([a-z.]+)(?: <span>[^<]*</span>)?</label>'
                           r'<div class="metadataFieldValue">(.*?)</div></div>', re.S)
        for i, h in enumerate(handles):
            part = parts / (h.rsplit("/", 1)[1] + ".json")
            if part.exists():
                continue
            t = get(c, f"{root}{h}?mode=full")
            md: dict[str, list] = defaultdict(list)
            for k, v in field.findall(t):
                v = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", v))).strip()
                if v:
                    md[k].append(v)
            pdfs = sorted(set(re.findall(r'href="(/bitstream/[^"]+\.pdf)', t, re.I)))
            write_atomic(part, json.dumps({"handle": h, "url": root + h, "pdf": [root + p for p in pdfs], "dc": md},
                                          ensure_ascii=False))
            if i % 50 == 0:
                print(f"  {src['id']}: ficha {i + 1} de {len(handles)}", file=sys.stderr)
    return dspace_assemble(parts, base)


def dspace_assemble(parts: Path, base: str) -> bytes:
    """El JSON de ``dspace_items`` con las fichas que hay en ``parts`` (sin red), también a medias."""
    items = [json.loads(f.read_text(encoding="utf-8")) for f in parts.glob("*.json") if f.stem.isdigit()]
    return json.dumps({"source": base.rstrip("/"), "items": sorted(items, key=lambda x: int(x["handle"].rsplit("/", 1)[1]))},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


#: Peligros de origen climático en el título de un reporte del COEN (sin tildes, en mayúsculas). Lo demás
#: (incendio urbano, sismo, accidente, derrame…) no se descarga.
COEN_CLIMATE = re.compile(
    r"LLUVIA|PRECIPITACION|INUNDACION|HUAICO|HUAYCO|ALUD|ALUVION|AVALANCHA|DESLIZAMIENTO|DERRUMBE|DESPRENDIMIENTO|"
    r"CAIDA DE ROCA|MOVIMIENTO EN MASA|REPTACION|DESBORDE|CRECIDA|EROSION|OLEAJE|MARETAZO|MAREJADA|VIENTO|"
    r"VENDAVAL|TORMENTA|TEMPESTAD|TEMPORAL|GRANIZ|NEVADA|HELADA|FRIAJE|BAJAS TEMPERATURAS|DESCENSO DE TEMPERATURA|"
    r"OLA DE CALOR|SEQUIA|DEFICIT HIDRICO|INCENDIO FORESTAL|QUEBRADA|COLAPSO DE (?:VIVIENDA|PUENTE|DEFENSA)")


def _plain(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", s.upper()) if unicodedata.category(c) != "Mn")


def pdf_text(content: bytes, timeout: int = 60) -> str:
    """Texto de un PDF con ``pdftotext -layout`` (poppler), en un directorio temporal propio que se borra; el PDF
    es de un tercero y no se ejecuta nada de él. Vacío si no se puede leer."""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "doc.pdf"
        pdf.write_bytes(content)
        try:
            r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True,
                               timeout=timeout, cwd=tmp)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""


#: Palabras con que se buscan notas sobre peligros climáticos en los medios (la búsqueda de WordPress recorre
#: título y cuerpo; el lector se queda con lo que el titular confirma).
NEWS_TERMS = ["huaico", "huayco", "inundación", "inundaciones", "desborde", "deslizamiento", "derrumbe", "aluvión",
              "activación de quebrada", "lluvias intensas", "precipitaciones", "crecida del río", "oleaje anómalo",
              "maretazo", "helada", "friaje", "nevada", "granizada", "sequía", "déficit hídrico", "incendio forestal",
              "vientos fuertes", "damnificados", "estado de emergencia", "Niño costero", "Fenómeno El Niño", "ciclón Yaku"]


def wp_rest(src: dict, parts: Path, delay: float = 5.0) -> bytes:
    """Notas de un medio con WordPress (``src["url"]`` = su ``/wp-json/wp/v2/posts``) que responden a ``NEWS_TERMS`` (o a
    ``parametros.terminos``), por su API REST pública (``/wp-json/wp/v2/posts?search=``, 100 por página): id,
    fecha, enlace, titular y un extracto. Solo metadatos y un extracto corto, con enlace a la nota (derecho de
    cita, D. Leg. 822, art. 44). Cada término terminado se guarda en ``parts`` y una descarga cortada sigue con el
    siguiente. JSON canónico ordenado por id."""
    import html as H
    import time

    p = src.get("parametros", {})
    api = src["url"]  # …/wp-json/wp/v2/posts
    parts.mkdir(parents=True, exist_ok=True)
    last = [0.0]
    with httpx.Client(follow_redirects=True, timeout=60, headers=UA, verify=ssl_context()) as c:
        for term in p.get("terminos", NEWS_TERMS):
            part = parts / _wp_part(term)
            if part.exists():
                continue
            got, errors = [], []
            page, pages = 1, 1
            while page <= pages:
                params = {"search": term, "per_page": 100, "page": page, "orderby": "date", "order": "asc",
                          "_fields": "id,date,link,title,excerpt"}
                for attempt in range(3):
                    time.sleep(max(0.0, last[0] + delay * (1 + 2 * attempt) - time.monotonic()))
                    last[0] = time.monotonic()
                    try:
                        r = c.get(api, params=params)
                    except httpx.HTTPError as e:
                        r, why = None, type(e).__name__
                        continue
                    why = f"HTTP {r.status_code}"
                    if r.status_code == 200 or (r.status_code != 429 and r.status_code < 500):
                        break
                if r is None or r.status_code != 200:
                    errors.append(f"{term} p. {page}: {why}")
                    break
                try:
                    items = r.json()
                except ValueError:
                    errors.append(f"{term} p. {page}: respuesta que no es JSON (¿verificación antirobots?)")
                    break
                if not isinstance(items, list):
                    errors.append(f"{term} p. {page}: respuesta inesperada")
                    break
                pages = int(r.headers.get("X-WP-TotalPages") or 1)
                for it in items:
                    title = H.unescape(re.sub(r"<[^>]+>", "", (it.get("title") or {}).get("rendered", ""))).strip()
                    exc = H.unescape(re.sub(r"<[^>]+>", " ", (it.get("excerpt") or {}).get("rendered", "")))
                    got.append({"id": it.get("id"), "fecha": it.get("date"), "url": it.get("link"),
                                "titulo": re.sub(r"\s+", " ", title), "extracto": re.sub(r"\s+", " ", exc).strip()[:500]})
                page += 1
            write_atomic(part, json.dumps({"termino": term, "notas": got, "errores": errors}, ensure_ascii=False))
            print(f"  {src['id']}: «{term}»: {len(got)} notas", file=sys.stderr)
    return wp_assemble(parts, src)


def _wp_part(term: str) -> str:
    return hashlib.sha256(term.encode("utf-8")).hexdigest()[:16] + ".json"


def wp_assemble(parts: Path, src: dict) -> bytes:
    """El JSON de ``wp_rest`` con los términos que hay en ``parts`` (sin red), también a medias. Una nota que responde a
    varios términos queda una vez, con la lista de términos, en el orden de la búsqueda."""
    posts: dict[int, dict] = {}
    errors = []
    for term in src.get("parametros", {}).get("terminos", NEWS_TERMS):
        part = parts / _wp_part(term)
        if not part.exists():
            continue
        got = json.loads(part.read_text(encoding="utf-8"))
        errors += got["errores"]
        for it in got["notas"]:
            posts.setdefault(it["id"], {**it, "terminos": []})["terminos"].append(term)
    return json.dumps({"source": src["url"], "errores": errors, "notas": [posts[k] for k in sorted(posts)]},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _paced_get(src: dict, delay: float):
    """Un ``get(client, url)`` que espera ``delay`` s desde el pedido anterior, reintenta 429 y 5xx con espera
    creciente y devuelve ``None`` ante 404/410 o cualquier otro 4xx (la página no existe o no se ofrece)."""
    import time

    last = [0.0]

    def get(c: httpx.Client, url: str) -> Optional[httpx.Response]:
        why = ""
        for attempt in range(4):
            time.sleep(max(0.0, last[0] + delay * (1 + 2 * attempt) - time.monotonic()))
            last[0] = time.monotonic()
            try:
                r = c.get(url)
            except httpx.HTTPError as e:
                why = type(e).__name__
                continue
            if r.status_code == 200:
                return r
            why = f"HTTP {r.status_code}"
            if r.status_code != 429 and r.status_code < 500:
                return None
            print(f"  {src['id']}: {url}: {why}, se reintenta", file=sys.stderr)
        raise SystemExit(f"{src['id']}: {url} respondió {why}")

    return get


def rpp_archivo(src: dict, parts: Path, delay: float = 5.0) -> bytes:
    """Notas de RPP por día y sección, del archivo diario ``https://rpp.pe/archivo/<sección>/AAAA-MM-DD`` (su
    robots.txt lo permite desde 2021): enlace, titular y fecha de cada nota, con el departamento que RPP pone en
    la dirección. Solo metadatos. Reanudable con ``parts``; JSON canónico ordenado por enlace."""
    import html as H

    p = src.get("parametros", {})
    parts.mkdir(parents=True, exist_ok=True)
    state = parts / "corte.json"
    if state.exists():
        end = date.fromisoformat(json.loads(state.read_text(encoding="utf-8"))["hasta"])
    else:
        end = datetime.now(F.LIMA).date() - timedelta(days=1)
        write_atomic(state, json.dumps({"hasta": end.isoformat()}))
    get = _paced_get(src, delay)
    with httpx.Client(follow_redirects=True, timeout=60, headers=UA, verify=ssl_context()) as c:
        day = date.fromisoformat(p.get("desde", "2021-01-01"))
        while day <= end:
            part = parts / f"{day.isoformat()}.json"
            if not part.exists():
                got = []
                for sec in p.get("secciones", ["peru", "lima"]):
                    r = get(c, f"{src['url'].rstrip('/')}/{sec}/{day.isoformat()}")
                    for a in (r.text.split("<article")[1:] if r is not None else []):
                        h = re.search(r'<h2[^>]*>\s*<a href="(https://rpp\.pe/[^"]+-noticia-\d+)"[^>]*>(.*?)</a>', a, re.S)
                        if h:
                            got.append({"url": h.group(1), "fecha": day.isoformat(), "seccion": sec,
                                        "titulo": re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", "", h.group(2)))).strip()})
                write_atomic(part, json.dumps(got, ensure_ascii=False))
                if day.day == 1:
                    print(f"  {src['id']}: {day:%Y-%m}", file=sys.stderr)
            day += timedelta(days=1)
    return rpp_assemble(parts, src)


def rpp_assemble(parts: Path, src: dict) -> bytes:
    """El JSON de ``rpp_archivo`` con los días que hay en ``parts`` (sin red); a medias, ``hasta`` es el último."""
    notes: dict[str, dict] = {}
    days = sorted(parts.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json"))
    for part in days:
        for n in json.loads(part.read_text(encoding="utf-8")):
            notes.setdefault(n["url"], n)
    state = parts / "corte.json"
    end = json.loads(state.read_text(encoding="utf-8"))["hasta"] if state.exists() else ""
    if days and days[-1].stem < end:
        end = days[-1].stem
    return json.dumps({"source": src["url"], "hasta": end, "notas": [notes[k] for k in sorted(notes)]},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sitemap_news(src: dict, parts: Path, delay: float = 5.0) -> bytes:
    """Direcciones de notas de un medio por sus sitemaps (``parametros.indice``: el índice; ``parametros.patron``:
    expresión que deben cumplir los sitemaps hijos que se leen), con la fecha (``lastmod`` o
    ``news:publication_date``) y, si el sitemap la trae, el titular (``news:title``), más el sitemap de donde salió
    (si es mensual, da el mes cuando la nota no trae fecha). Se guardan solo las que tienen en la dirección una
    palabra de peligro climático (``NEWS_SLUG``). Reanudable; JSON canónico."""
    import html as H

    p = src.get("parametros", {})
    parts.mkdir(parents=True, exist_ok=True)
    get = _paced_get(src, delay)
    want = re.compile(p.get("patron", "."))
    notes: dict[str, dict] = {}
    with httpx.Client(follow_redirects=True, timeout=120, headers=UA, verify=ssl_context()) as c:
        idx = parts / "indice.json"
        if idx.exists():
            maps = json.loads(idx.read_text(encoding="utf-8"))
        else:
            r = get(c, p["indice"])
            if r is None or b"<!ENTITY" in r.content[:4096]:
                raise SystemExit(f"{src['id']}: el índice de sitemaps no responde")
            maps = sorted(m for m in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text) if want.search(m))
            write_atomic(idx, json.dumps(maps))
        for i, m in enumerate(maps):
            part = parts / (hashlib.sha256(m.encode()).hexdigest()[:16] + ".json")
            if not part.exists():
                r = get(c, m)
                got = []
                if r is not None and b"<!ENTITY" not in r.content[:4096]:
                    for u in re.findall(r"<url>(.*?)</url>", r.text, re.S):
                        loc = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", u)
                        if not loc or not NEWS_SLUG.search(loc.group(1).lower()):
                            continue
                        when = re.search(r"<(?:news:publication_date|lastmod)>\s*([^<\s]+)", u)
                        title = re.search(r"<news:title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</news:title>", u, re.S)
                        got.append({"url": H.unescape(loc.group(1)), "fecha": when.group(1) if when else "",
                                    "titulo": H.unescape(title.group(1)).strip() if title else "", "sitemap": m})
                write_atomic(part, json.dumps(got, ensure_ascii=False))
                if i % 20 == 0:
                    print(f"  {src['id']}: sitemap {i + 1} de {len(maps)}", file=sys.stderr)
            for n in json.loads(part.read_text(encoding="utf-8")):
                notes.setdefault(n["url"], n)
    data = json.dumps({"source": p["indice"], "notas": [notes[k] for k in sorted(notes)]}, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")
    return data


#: Palabras de peligro climático en la dirección de una nota (sin tildes, con guiones).
NEWS_SLUG = re.compile(r"huaic|huayc|inundac|desborde|deslizamiento|derrumbe|aluvion|lluvia|precipitacion|crecida|"
                       r"oleaje|maretazo|helada|friaje|nevada|granizad|sequia|deficit-hidrico|incendio-forestal|"
                       r"vientos-fuertes|damnificad|estado-de-emergencia|nino-costero|fenomeno-el-nino|yaku|"
                       r"quebrada|aniego|tormenta|bajas-temperaturas|ola-de-calor|alud|avalancha")


#: Constantes del formato «turbo-stream» de React Router (los datos de cada página de busquedas.elperuano.pe).
_TURBO = {-1: None, -2: float("nan"), -3: float("-inf"), -4: -0.0, -5: None, -6: float("inf"), -7: None}


def turbo_stream(page: str):
    """Los datos de la página (``loaderData``) que React Router serializa en ``streamController.enqueue(...)``:
    una lista plana en la que cada objeto y lista apunta por índice a sus valores."""
    chunk = re.search(r'streamController\.enqueue\(("(?:[^"\\]|\\.)*")\);</script>', page, re.S)
    if not chunk:
        raise ValueError("la página no trae datos de React Router")
    arr = json.loads(json.loads(chunk.group(1)))
    memo: dict[int, object] = {}

    def dec(i):
        if isinstance(i, int) and i < 0:
            return _TURBO.get(i)
        if i in memo:
            return memo[i]
        v = arr[i]
        if isinstance(v, list):
            if len(v) == 2 and v[0] == "D":
                out = v[1]
            else:
                out = memo[i] = []
                out.extend(dec(x) for x in v)
        elif isinstance(v, dict):
            out = memo[i] = {}
            for k, x in v.items():
                out[arr[int(k[1:])]] = dec(x)
        else:
            out = v
        memo[i] = out
        return out

    return dec(0)


def _loc_part(q: str) -> str:
    """El archivo de ``parts`` con las páginas de una consulta de Chronicling America."""
    return f"q-{hashlib.sha256(q.encode()).hexdigest()[:16]}.json"


def _loc_snippet(url: str) -> str:
    """El archivo de ``parts/fragmentos`` con el fragmento de una página."""
    return hashlib.sha256(url.encode()).hexdigest()[:20] + ".json"


def loc_chronam(src: dict, parts: Path, delay: float = 5.0) -> bytes:
    """Páginas de periódicos de EE. UU. digitalizados por la Biblioteca del Congreso (Chronicling America, 1836-1963)
    que responden a las consultas de ``parametros.consultas`` (una frase entre comillas o términos unidos con AND, sobre
    el texto OCR), por la API JSON de loc.gov (160 por página), con el fragmento del texto donde aparecen los términos
    (``word_coordinates_url``, servicio de texto de loc.gov). Solo metadatos y el fragmento, con enlace a la página.
    Cada consulta terminada y cada fragmento leído quedan en ``parts``. JSON canónico ordenado por dirección."""
    from urllib.parse import urlencode

    p = src.get("parametros", {})
    parts.mkdir(parents=True, exist_ok=True)
    (parts / "fragmentos").mkdir(exist_ok=True)
    get = _paced_get(src, delay)

    def doc(r: Optional[httpx.Response], what: str):
        if r is None:
            raise SystemExit(f"{src['id']}: {what} no responde")
        try:
            return r.json()
        except ValueError:
            raise SystemExit(f"{src['id']}: {what} respondió algo que no es JSON (¿verificación antirobots?)") from None

    pages: dict[str, dict] = {}
    with httpx.Client(follow_redirects=True, timeout=120, headers=UA, verify=ssl_context()) as c:
        for q in p["consultas"]:
            part = parts / _loc_part(q)
            if not part.exists():
                got, page = [], 1
                while True:
                    d = doc(get(c, f"{src['url']}?" + urlencode({"q": q, "fo": "json", "c": 160, "sp": page,
                                                                 "at": "results,pagination"})), f"la búsqueda «{q}»")
                    for it in d.get("results", []):
                        url = (it.get("id") or "").replace("http://", "https://", 1)
                        if not url:
                            continue
                        got.append({"url": url, "fecha": it.get("date") or "",
                                    "periodico": (it.get("partof_title") or [""])[0],
                                    "lugar": ", ".join(dict.fromkeys(x for k in ("location_city", "location_state")
                                                                     for x in (it.get(k) or [])[:1])),
                                    "texto": it.get("word_coordinates_url") or ""})
                    if not (d.get("pagination") or {}).get("next"):
                        break
                    page += 1
                write_atomic(part, json.dumps({"consulta": q, "paginas": got}, ensure_ascii=False))
                print(f"  {src['id']}: «{q}»: {len(got)} páginas", file=sys.stderr)
            for it in json.loads(part.read_text(encoding="utf-8"))["paginas"]:
                pages.setdefault(it["url"], {**it, "consulta": q})
        for i, (url, it) in enumerate(sorted(pages.items())):
            f = parts / "fragmentos" / _loc_snippet(url)
            if f.exists() or not it["texto"]:
                continue
            r = get(c, it["texto"])  # None: la página no tiene texto (404); queda sin fragmento
            d = doc(r, "el servicio de texto") if r is not None else {}
            seg = next(iter(d.values()), {}) if isinstance(d, dict) and d else {}
            snippet = seg.get("relevant_snippet") if isinstance(seg, dict) else ""
            write_atomic(f, json.dumps({"fragmento": (snippet or "")[:1000]}, ensure_ascii=False))
            if i % 100 == 0:
                print(f"  {src['id']}: fragmento {i + 1} de {len(pages)}", file=sys.stderr)
    return loc_assemble(parts, src)


def loc_assemble(parts: Path, src: dict) -> bytes:
    """El JSON de ``loc_chronam`` con lo que hay en ``parts`` (sin red), también a medias: cada página con la primera
    consulta que la trajo y su fragmento, o sin fragmento si aún no se leyó."""
    pages: dict[str, dict] = {}
    for q in src.get("parametros", {}).get("consultas", []):
        part = parts / _loc_part(q)
        if part.exists():
            for it in json.loads(part.read_text(encoding="utf-8"))["paginas"]:
                pages.setdefault(it["url"], {**it, "consulta": q})
    out = []
    for url, it in sorted(pages.items()):
        f = parts / "fragmentos" / _loc_snippet(url)
        frag = json.loads(f.read_text(encoding="utf-8"))["fragmento"] if f.exists() else None
        out.append({**{k: v for k, v in it.items() if k != "texto"}, "fragmento": frag})
    return json.dumps({"source": src["url"], "consultas": src.get("parametros", {}).get("consultas", []), "paginas": out},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


#: Sumilla de un decreto que declara o prorroga un estado de emergencia.
EMERGENCY_DECREE = re.compile(r"(?:declara|prorroga)\w*\s+(?:el\s+)?estado\s+de\s+emergencia", re.I)


def elperuano_normas(src: dict, parts: Path, delay: float = 5.0) -> bytes:
    """Decretos supremos que declaran o prorrogan un estado de emergencia, del buscador de normas legales de El
    Peruano (``parametros.query``, mes por mes desde ``parametros.desde``, 20 resultados por página), con el texto
    de cada uno (``pdf_text`` de su PDF, que trae el anexo de distritos). La búsqueda es de texto completo y
    trae ruido: se guardan solo los dispositivos cuyo tipo es decreto supremo y cuya sumilla declara o prorroga
    un estado de emergencia. Reanudable con ``parts``. JSON canónico ordenado por número de operación."""
    import gzip
    import time
    from urllib.parse import urlencode

    p = src.get("parametros", {})
    base = src["url"].rstrip("/")
    parts.mkdir(parents=True, exist_ok=True)
    state = parts / "corte.json"
    if state.exists():
        end = date.fromisoformat(json.loads(state.read_text(encoding="utf-8"))["hasta"])
    else:
        end = datetime.now(F.LIMA).date()
        write_atomic(state, json.dumps({"hasta": end.isoformat()}))
    last = [0.0]

    def get(c: httpx.Client, url: str, pdf: bool = False) -> Optional[httpx.Response]:
        for attempt in range(4):
            time.sleep(max(0.0, last[0] + delay * (1 + 2 * attempt) - time.monotonic()))
            last[0] = time.monotonic()
            try:
                r = c.get(url)
            except httpx.HTTPError as e:
                why = type(e).__name__
                continue
            why = f"HTTP {r.status_code}"
            if r.status_code == 200:
                if pdf and r.content[:5] != b"%PDF-":
                    why = "una respuesta que no es PDF (¿verificación antirobots?)"
                    break
                return r
            if pdf and r.status_code in (404, 410):
                return None
            # El buscador responde a veces 404 a una página de resultados que existe (visto el 26-10-2026 en la
            # página 11 de diciembre de 2007, que al reintentar respondió bien): se reintenta como un 5xx.
            if r.status_code not in (404, 429) and r.status_code < 500:
                break
            print(f"  {src['id']}: {why}, se reintenta", file=sys.stderr)
        raise SystemExit(f"{src['id']}: {url} respondió {why}")

    hits: dict[str, dict] = {}
    with httpx.Client(follow_redirects=True, timeout=120, headers=UA, verify=ssl_context()) as c:
        for a, b in _months(date.fromisoformat(p.get("desde", "2000-01-01")), end):
            part = parts / f"{a:%Y-%m}.json"
            if not part.exists():
                got, start, total = [], 0, None
                while total is None or start < total:
                    q = urlencode({"query": p.get("query", "estado de emergencia"), "fechaIni": f"{a:%Y%m%d}",
                                   "fechaFin": f"{b:%Y%m%d}", "tipoPublicacion": "NL", "start": start, "ci": "all"})
                    res = turbo_stream(get(c, f"{base}/?{q}").text)["loaderData"]["routes/_index"]["results"]
                    total = res["totalHits"] or 0
                    got += [h for h in res["hits"] if (h.get("tipoDispositivo") or "").upper().startswith("DECRETO SUPREMO")
                            and EMERGENCY_DECREE.search(h.get("sumilla") or "")]
                    start += res.get("paginatedBy") or 20
                    if not res["hits"]:
                        break
                write_atomic(part, json.dumps(got, ensure_ascii=False))
                print(f"  {src['id']}: {a:%Y-%m}: {len(got)} decretos de {total} resultados", file=sys.stderr)
            hits.update((h["op"], h) for h in json.loads(part.read_text(encoding="utf-8")) if h.get("op"))
        texts = parts / "textos"
        texts.mkdir(exist_ok=True)
        for i, (op, h) in enumerate(sorted(hits.items())):
            f = texts / f"{op}.txt.gz"
            if f.exists() or not h.get("urlPDF"):
                continue
            r = get(c, base + h["urlPDF"], pdf=True)
            write_atomic(f, gzip.compress(pdf_text(r.content).encode("utf-8") if r is not None else b"", mtime=0))
            if i % 100 == 0:
                print(f"  {src['id']}: texto {i + 1} de {len(hits)}", file=sys.stderr)
    return elperuano_assemble(parts, src)


def elperuano_assemble(parts: Path, src: dict) -> bytes:
    """El JSON de ``elperuano_normas`` con lo que hay en ``parts`` (sin red), también a medias: ``hasta`` es
    entonces el último mes buscado."""
    import gzip

    hits: dict[str, dict] = {}
    months = sorted(parts.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))
    for part in months:
        hits.update((h["op"], h) for h in json.loads(part.read_text(encoding="utf-8")) if h.get("op"))
    state = parts / "corte.json"
    end = json.loads(state.read_text(encoding="utf-8"))["hasta"] if state.exists() else ""
    if months and months[-1].stem < end[:7]:
        end = months[-1].stem
    texts = parts / "textos"
    out = []
    for op, h in sorted(hits.items()):
        f = texts / f"{op}.txt.gz"
        out.append({**{k: h.get(k) for k in ("fechaPublicacion", "numeroDispositivo", "op", "sumilla", "tipoDispositivo",
                                                "distributor", "urlPDF")},
                    "texto": gzip.decompress(f.read_bytes()).decode("utf-8") if f.exists() else None})
    return json.dumps({"source": src["url"].rstrip("/"), "parametros": src.get("parametros", {}), "hasta": end,
                       "normas": out}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def indeci_coen(src: dict, parts: Path, delay: float = 5.0) -> bytes:
    """Reportes del COEN (INDECI) de una sección del portal (``src["url"]``, p. ej. los reportes preliminares y
    complementarios de emergencias): cada entrada del listado es una emergencia, con el título del último
    reporte y el enlace a su PDF. Se recorre el listado completo (20 por página) y, de las emergencias de
    origen climático (``COEN_CLIMATE`` sobre el título), se baja el PDF y se guarda su texto (``pdf_text``),
    no el PDF. Todo queda en ``parts``, así que una descarga cortada sigue donde quedó (son decenas de miles
    de pedidos a 5 s). Devuelve JSON canónico ordenado por la dirección de cada entrada."""
    import gzip
    import html as H
    import time

    base = src["url"].rstrip("/")
    parts.mkdir(parents=True, exist_ok=True)
    last = [0.0]

    def get(c: httpx.Client, url: str, kind: str) -> Optional[httpx.Response]:
        for attempt in range(4):
            time.sleep(max(0.0, last[0] + delay * (1 + 2 * attempt) - time.monotonic()))
            last[0] = time.monotonic()
            try:
                r = c.get(url)
            except httpx.HTTPError as e:
                why = type(e).__name__
                continue
            why = f"HTTP {r.status_code}"
            if r.status_code == 200:
                ctype = r.headers.get("content-type", "")
                if kind == "pdf" and (r.content[:5] == b"%PDF-" or "pdf" in ctype):
                    return r
                if kind == "html" and "html" in ctype:
                    return r
                why = f"un {ctype or 'documento'} donde se esperaba {kind} (¿verificación antirobots?)"
                break
            if r.status_code in (404, 410) and kind == "pdf":
                return None  # PDF retirado: la entrada queda sin texto
            if r.status_code != 429 and r.status_code < 500:
                break
            print(f"  {src['id']}: {why}, se reintenta", file=sys.stderr)
        raise SystemExit(f"{src['id']}: {url} respondió {why}")

    def items(t: str) -> list[dict]:
        """Entradas del listado (no las del carrusel de alertas de la cabecera)."""
        got = []
        for chunk in t.split('class="list-news alerts-archive"', 1)[-1].split("<article")[1:]:
            url = re.search(r'href="(https://portal\.indeci\.gob\.pe/emergencias/[^"]+)"', chunk)
            title = re.search(r"<h3>(.*?)</h3>", chunk, re.S)
            pdf = re.search(r'href="([^"]+\.pdf)"', chunk, re.I)
            if url and title:
                got.append({"url": url.group(1), "pdf": H.unescape(pdf.group(1)) if pdf else "",
                            "titulo": re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", "", title.group(1)))).strip()})
        return got

    entries: dict[str, dict] = {}
    for p in sorted(parts.glob("lista-*.json")):
        entries.update((e["url"], e) for e in json.loads(p.read_text(encoding="utf-8")))
    with httpx.Client(follow_redirects=True, timeout=120, headers=UA, verify=ssl_context()) as c:
        state = parts / "lista.json"
        done = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {"pagina": 0, "paginas": None}
        page = done["pagina"] + 1
        while done["paginas"] is None or page <= done["paginas"]:
            t = get(c, f"{base}/page/{page}/", "html").text
            if done["paginas"] is None:
                m = re.findall(r"/page/(\d+)/", t)
                done["paginas"] = max(map(int, m)) if m else 1
            got = items(t)
            write_atomic(parts / f"lista-{page:05d}.json", json.dumps(got, ensure_ascii=False))
            entries.update((e["url"], e) for e in got)
            done["pagina"] = page
            write_atomic(state, json.dumps(done))
            if page % 50 == 0:
                print(f"  {src['id']}: listado {page} de {done['paginas']} ({len(entries)} entradas)", file=sys.stderr)
            page += 1
        # El listado va del más nuevo al más viejo: lo publicado mientras se recorría corrió las páginas.
        page = 1
        while True:
            t = get(c, f"{base}/page/{page}/", "html").text
            new = [e for e in items(t) if e["url"] not in entries]
            entries.update((e["url"], e) for e in new)
            if not new:
                break
            page += 1
        texts = parts / "textos"
        texts.mkdir(exist_ok=True)
        todo = [e for e in entries.values() if e["pdf"] and COEN_CLIMATE.search(_plain(e["titulo"]))]
        for i, e in enumerate(todo):
            f = texts / (hashlib.sha256(e["pdf"].encode()).hexdigest()[:20] + ".txt.gz")
            if f.exists():
                continue
            r = get(c, e["pdf"], "pdf")
            write_atomic(f, gzip.compress(pdf_text(r.content).encode("utf-8") if r is not None else b"", mtime=0))
            if i % 100 == 0:
                print(f"  {src['id']}: PDF {i + 1} de {len(todo)}", file=sys.stderr)
    return coen_assemble(parts, base)


def coen_assemble(parts: Path, base: str) -> bytes:
    """El JSON de ``indeci_coen`` con lo que hay en ``parts`` (sin red): sirve también para una descarga a medias.
    Del texto de cada PDF quedan las secciones 1 a 3 (hechos, ubicación y daños), no las acciones de respuesta."""
    import gzip

    entries: dict[str, dict] = {}
    for p in sorted(parts.glob("lista-*.json")):
        entries.update((e["url"], e) for e in json.loads(p.read_text(encoding="utf-8")))
    texts = parts / "textos"
    out = []
    for e in sorted(entries.values(), key=lambda e: e["url"]):
        f = texts / (hashlib.sha256(e["pdf"].encode()).hexdigest()[:20] + ".txt.gz") if e["pdf"] else None
        text = gzip.decompress(f.read_bytes()).decode("utf-8") if f and f.exists() else None
        if text:
            text = re.split(r"\n\s*4\.\s*ACCIONES", text, maxsplit=1)[0]
        out.append({**e, "texto": text})
    return json.dumps({"source": base, "entradas": out}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


#: Instituciones públicas peruanas (``enso.reach.public_peru``: .gob.pe y .mil.pe): su información es pública por
#: ley (Ley N° 27806) y, por decisión del proyecto (26-10-2026), un «Disallow» de su robots.txt no impide pedirla.
#: ``Robots.allowed`` aplica esa excepción (nunca ante una verificación antirobots); aquí se pide además al menos
#: PERU_PUBLIC_DELAY entre pedidos, porque estas descargas son de miles de páginas.
PERU_PUBLIC_DELAY = 5.0
peru_public = public_peru


def robots_check(url: str) -> float:
    """Como el resto del observatorio, lee el robots.txt del servidor (RFC 9309) antes de pedir nada y lo
    respeta, con la excepción de las instituciones públicas peruanas de ``Robots.allowed``. Devuelve la pausa
    entre pedidos: el Crawl-delay del servidor (0 si no pide; al menos PERU_PUBLIC_DELAY para esas instituciones)."""
    with httpx.Client(follow_redirects=True, timeout=30, headers=UA, verify=ssl_context()) as c:
        robots = Robots(c)
        ok = robots.allowed(url)
        if not ok and robots.failure(url) == "challenge":
            raise SystemExit(f"{url}: el servidor responde con una verificación antirobots; no se pide nada")
        if ok is None:
            raise SystemExit(f"{url}: el robots.txt del servidor no respondió ({robots.failure(url)}); no se pide nada")
        if not ok:
            raise SystemExit(f"{url}: el robots.txt del servidor no permite pedirlo a un programa")
        delay = robots.crawl_delay(url) or 0.0
        return max(PERU_PUBLIC_DELAY, delay) if public_peru(url) else delay


def locate(src: dict, caches: list[Path]) -> Path:
    """El archivo de ``src`` en la primera caché que lo tenga, o donde se descargaría (la primera)."""
    for cache in caches:
        if (cache / src["archivo"]).exists():
            return cache / src["archivo"]
    return caches[0] / src["archivo"]


#: Ensamblado sin red de las descargas largas y reanudables, para construir con lo bajado hasta ahora.
ASSEMBLE = {
    "indeci-coen": lambda src, parts: coen_assemble(parts, src["url"].rstrip("/")),
    "elperuano": lambda src, parts: elperuano_assemble(parts, src),
    "dspace": lambda src, parts: dspace_assemble(parts, src["url"]),
    "rpp": lambda src, parts: rpp_assemble(parts, src),
    "wp-rest": lambda src, parts: wp_assemble(parts, src),
    "loc-chronam": lambda src, parts: loc_assemble(parts, src),
}


def snapshot(src: dict, caches: list[Path]) -> Optional[Path]:
    """Si la cosecha de ``src`` sigue a medias (hay carpeta de partes y no archivo final), escribe lo bajado hasta
    ahora en ``<archivo>.parcial.json`` junto a las partes, lo anota en el manifiesto (``parcial``) y lo devuelve;
    ``None`` si no hay nada a medias."""
    if src.get("descarga") not in ASSEMBLE:
        return None
    for cache in caches:
        path = cache / src["archivo"]
        parts = cache / f"{path.stem}-partes"
        if path.exists():
            return None
        if parts.is_dir():
            out = path.with_name(path.stem + ".parcial.json")
            write_atomic(out, ASSEMBLE[src["descarga"]](src, parts))
            src["parcial"] = True
            src["obtenido"] = datetime.now(timezone.utc).date().isoformat()
            return finish(src, out, accept_changes=True)
    return None


def fetch(src: dict, cache, accept_changes: bool, offline: bool) -> Path:
    """El archivo de ``src`` en la caché, descargado si falta. Lo descargado se escribe de una vez (``write_atomic``) y
    solo después se borran las partes de una cosecha larga: si se corta antes, la próxima sigue con ellas."""
    caches = cache if isinstance(cache, list) else [cache]
    stem = Path(src["archivo"]).stem
    cache = next((c for c in caches if (c / src["archivo"]).exists()), None)
    if cache is not None:
        src.pop("parcial", None)
    else:  # una cosecha a medias sigue en la caché donde están sus partes
        cache = next((c for c in caches if (c / f"{stem}-partes").is_dir()), caches[0])
    path = cache / src["archivo"]
    origin = path.with_name(path.name + ".origen")  # de dónde salió una fuente con semilla (la API o la semilla)
    if path.exists() and origin.exists():
        src["copia"] = origin.read_text(encoding="utf-8").strip()
    if not path.exists():
        if offline:
            raise SystemExit(f"{src['id']}: falta {path} y se pidió --sin-red")
        kind = src.get("descarga")
        if kind == "manual":
            raise SystemExit(f"{src['id']}: falta {path}. Esta fuente se descarga a mano: {src['manual']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        parts = cache / f"{path.stem}-partes"
        src["obtenido"] = datetime.now(timezone.utc).date().isoformat()
        if kind == "idmc-api" and not os.environ.get("IDMC_CLIENT_ID", "").strip() and src.get("semilla"):
            # Sin la clave de la API, la copia guardada en el repositorio (el robots.txt de HDX, donde el IDMC publica
            # sus exportaciones, no deja que un programa baje sus CSV).
            import gzip

            print(f"{src['id']}: sin IDMC_CLIENT_ID, se usa la copia de {src['semilla']}", file=sys.stderr)
            write_atomic(path, gzip.decompress((ROOT / src["semilla"]).read_bytes()))
            write_atomic(origin, "semilla")
            src["copia"] = "semilla"
            return finish(src, path, accept_changes)
        delay = robots_check(src.get("url_robots", src["url"]))  # p. ej. la URL con la consulta que se hará
        peru = max(PERU_PUBLIC_DELAY, delay)
        print(f"descargando {src['url']}", file=sys.stderr)
        if kind == "arcgis":
            data = arcgis_dump(src["url"], src.get("campos", "*"), src.get("geometria", True), src.get("consulta", "1=1"),
                               delay=max(0.5, delay))
        elif kind == "idmc-api":
            data = idmc_api(src, delay=max(1.0, delay))
            write_atomic(origin, "API")
        elif kind == "sinpad-api":
            data = sinpad_api(src, parts, delay=peru)
        elif kind == "oai-pmh":
            data = oai_pmh(src, delay=peru)
        elif kind == "indeci-coen":
            data = indeci_coen(src, parts, delay=peru)
        elif kind == "elperuano":
            data = elperuano_normas(src, parts, delay=peru)
        elif kind == "wp-rest":
            data = wp_rest(src, parts, delay=peru)
        elif kind == "rpp":
            data = rpp_archivo(src, parts, delay=peru)
        elif kind == "sitemaps":
            data = sitemap_news(src, parts, delay=peru)
        elif kind == "dspace":
            data = dspace_items(src, parts, delay=peru)
        elif kind == "loc-chronam":
            data = loc_chronam(src, parts, delay=peru)
        else:
            with httpx.Client(follow_redirects=True, timeout=180, headers=UA, verify=ssl_context()) as c:
                r = c.get(src["url"])
                r.raise_for_status()
                data = r.content
        write_atomic(path, data)
        if parts.is_dir():
            shutil.rmtree(parts)
    return finish(src, path, accept_changes)


def finish(src: dict, path: Path, accept_changes: bool) -> Path:
    """Compara el archivo con el SHA-256 del manifiesto (y lo anota)."""
    digest = sha256(path)
    if src.get("sha256") and digest != src["sha256"]:
        msg = f"{src['id']}: la fuente cambió (SHA-256 {digest[:12]}… ≠ {src['sha256'][:12]}… del manifiesto)"
        if not accept_changes:
            raise SystemExit(msg + ". Revise el cambio y repita con --aceptar-cambios.")
        print(msg + ": se acepta y se actualiza el manifiesto", file=sys.stderr)
    src["sha256"] = digest
    src.setdefault("obtenido", datetime.now(timezone.utc).date().isoformat())
    return path


def fresh_indices(dest: Path) -> tuple[Path, Path]:
    """El ICEN y el ONI vigentes, descargados en ``dest``. Si una descarga falla, no se puede leer o trae menos meses
    que la copia de las pruebas, se usan las dos copias de las pruebas (un calendario ENSO a medias es peor)."""
    got = {}
    for name, (url, _) in INDICES.items():
        try:
            with httpx.Client(follow_redirects=True, timeout=60, headers=UA, verify=ssl_context()) as c:
                r = c.get(url)
                r.raise_for_status()
            got[name] = dest / f"{name}.txt"
            write_atomic(got[name], r.content)
        except httpx.HTTPError as e:
            print(f"{name}: no se pudo descargar ({e}); se usan los índices de las pruebas", file=sys.stderr)
            return INDICES["icen"][1], INDICES["oni"][1]
    try:
        new = EnsoCalendar.from_files(got["icen"], got["oni"])
        old = EnsoCalendar.from_files(INDICES["icen"][1], INDICES["oni"][1])
        if max(new.icen) < max(old.icen):
            raise ValueError(f"el ICEN descargado llega a {max(new.icen)} y la copia de las pruebas a {max(old.icen)}")
    except (ValueError, KeyError) as e:
        print(f"índices descargados inservibles ({e}); se usan los de las pruebas", file=sys.stderr)
        return INDICES["icen"][1], INDICES["oni"][1]
    return got["icen"], got["oni"]


def curated_records(territory: Territory, calendar: EnsoCalendar) -> list[dict]:
    """Registros curados a mano: cada uno con su fuente (URL) y su cita textual."""
    out = []
    for f in sorted(CURATED.glob("*.yaml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        defaults = doc.get("comun", {})
        for item in doc.get("registros", []):
            out.append(normalize_curated({**defaults, **item}, territory, calendar, f.name))
    return out


def normalize_curated(it: dict, territory: Territory, calendar: EnsoCalendar, fname: str) -> dict:
    code = territory.resolve(it.get("Departamento", ""), it.get("Provincia", ""), it.get("Distrito", ""), str(it.get("Ubigeo", "")))
    if not code or (it.get("Distrito") and len(code) != 6) or (it.get("Provincia") and len(code) < 4):
        raise SystemExit(f"{fname} {it.get('Id')}: lugar desconocido {it.get('Ubigeo')} {it.get('Distrito') or it.get('Provincia')}")
    if it.get("DangerType") not in E.DANGER_TYPES:
        raise SystemExit(f"{fname} {it.get('Id')}: DangerType desconocido {it.get('DangerType')!r}")
    if not str(it.get("Fuente", "")).startswith("https://"):
        raise SystemExit(f"{fname} {it.get('Id')}: todo registro curado necesita una Fuente https://")
    if not str(it.get("FuenteCita", "")).strip():
        raise SystemExit(f"{fname} {it.get('Id')}: todo registro curado necesita la cita (FuenteCita)")
    raw = str(it["Date"])
    precision = it.get("PrecisionFecha") or {10: "dia", 7: "mes", 4: "anio"}.get(len(raw))
    if not precision:
        raise SystemExit(f"{fname} {it.get('Id')}: fecha {raw!r}")
    day = raw if len(raw) == 10 else (raw[:7] + "-01" if len(raw) == 7 else raw[:4] + "-01-01")
    latlon = (float(it["Latitud"]), float(it["Longitud"])) if it.get("Latitud") and it.get("Longitud") else None
    return make(territory, calendar, code=code, day=day, precision=precision, danger=it["DangerType"],
                origin="curado", source_id=str(it["Id"]), url=it["Fuente"], cite=" ".join(str(it["FuenteCita"]).split()),
                license=it.get("Licencia", "Cita de la fuente indicada"),
                description=" ".join(str(it.get("Descripción", "")).split()), place=it.get("Ubicacion", ""),
                duration=it.get("DuraciónEvento"), source_type=it.get("PeligroFuente", ""),
                cause=it.get("CausaFuente", ""), latlon=latlon, impacts={k: it.get(k) for k in E.IMPACT_COLUMNS},
                tipo=it.get("TipoEvento"), confidence=it.get("Confianza"))


def apply_reviews(records: list[dict], path: Path = DATA / "revisiones.yaml", strict: bool = True) -> list[dict]:
    """Aplica ``data/historico/revisiones.yaml`` (exclusiones y cifras dudosas, cada una con su motivo). ``strict``: cada
    revisión debe coincidir con algún registro (con ``--desde-catalogo`` solo se aplican a los curados, que se releen)."""
    revs = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("revisiones", []) if path.exists() else []
    used = [0] * len(revs)
    out = []
    for r in records:
        action = None
        for i, v in enumerate(revs):
            if ("id" in v and v["id"] == r["Id"]) or ("fecha" in v and r["Date"] == str(v["fecha"])
                                                       and r["Ubigeo"].startswith(str(v.get("departamento", "")))):
                action = v
                used[i] += 1
                break
        if action and action["accion"] == "excluir":
            continue
        if action and action["accion"] == "sin-impactos":
            r["ImpactoEnTotales"] = "no"
            r["Confianza"] = "baja"
            r["Descripción"] = (r["Descripción"] + f" [Revisión del observatorio: {' '.join(action['motivo'].split())}]").strip()
        out.append(r)
    for v, n in zip(revs, used):
        if strict and not n:
            raise SystemExit(f"revisiones.yaml: la revisión {v.get('id') or v.get('fecha')} no coincide con ningún registro")
    return out


def mark_duplicate_impacts(records: list[dict]) -> None:
    """Un registro curado que resume un área y evento ya cubiertos por fichas de otra fuente con cifras de
    daños no suma sus impactos a los totales (``ImpactoEnTotales = no``): las cifras quedan en la fila, pero no se cuentan
    dos veces."""
    seen = defaultdict(set)
    for r in records:
        if r["Origen"] != "curado" and r.get("ImpactoReportado") == "si":
            code = r["Ubigeo"]
            for n in (2, 4, 6):
                if len(code) >= n:
                    seen[(code[:n], r["TipoEvento"])].add(r["Origen"])
    for r in records:
        if r["Origen"] == "curado" and seen.get((r["Ubigeo"], r["TipoEvento"])):
            r["ImpactoEnTotales"] = "no"


# ---------------------------------------------------------------------------
# Salidas
# ---------------------------------------------------------------------------
#: Impactos que una fila del IDMC pasa a su emergencia gemela del SINPAD.
IDMC_TWIN_DAYS = 1


def merge_idmc_twins(records: list[dict], stats: Counter) -> list[dict]:
    """El IDMC recopila las mismas emergencias del INDECI que el SINPAD: una fila distrital del IDMC con una emergencia del
    SINPAD en el mismo distrito y a ±1 día es la misma emergencia. Sus personas desplazadas, viviendas y duración pasan a
    la fila del SINPAD (que no trae daños desde 2019), el IDMC queda como corroboración y la fila del IDMC se quita. El
    tipo de peligro es el del SINPAD (el IDMC solo dice «Flood» o «Storm»). Las filas del IDMC por departamento y mes no
    tienen gemela: se quedan como resumen de desplazamiento (``docs/memoria-desastres.md``)."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r["Origen"] == "sinpad" and r["PrecisionFecha"] == "dia":
            by[r["Ubigeo"]].append(r)
    drop = set()
    for r in records:
        if r["Origen"] != "idmc" or len(r["Ubigeo"]) != 6 or r["PrecisionFecha"] != "dia":
            continue
        day = date.fromisoformat(r["Date"])
        near = [(abs((date.fromisoformat(s["Date"]) - day).days), s["GrupoPeligro"] != r["GrupoPeligro"], s["Id"], s)
                for s in by.get(r["Ubigeo"], [])]
        near = [x for x in near if x[0] <= IDMC_TWIN_DAYS]
        if not near:
            continue
        t = min(near, key=lambda x: x[:3])[3]
        for k in E.IMPACT_COLUMNS:
            if r.get(k) not in (None, ""):
                t[k] = _n(t.get(k)) + _n(r[k]) if t.get(k) not in (None, "") else r[k]
        if r.get("DuraciónEvento") and not t.get("DuraciónEvento"):
            t["DuraciónEvento"] = r["DuraciónEvento"]
            if t["PrecisionFecha"] == "dia":
                t["FechaFin"] = (date.fromisoformat(t["Date"]) + timedelta(days=int(r["DuraciónEvento"]) - 1)).isoformat()
        if any(t.get(k) not in (None, "", 0) for k in E.IMPACT_COLUMNS):
            t["ImpactoReportado"] = "si"
        enlace.attach(t, r)
        # Lo que ya corroboraba a la fila del IDMC (notas, reportes) pasa a la del SINPAD.
        links = [u for u in (t.get("FuentesAdicionales") or "").split(" | ") if u]
        links += [u for u in (r.get("FuentesAdicionales") or "").split(" | ") if u and u not in links]
        t["FuentesAdicionales"] = " | ".join(links[:enlace.MAX_LINKS])
        origins = set(filter(None, (t.get("OrigenesCorroboran") or "").split(","))) | set(
            filter(None, (r.get("OrigenesCorroboran") or "").split(",")))
        t["OrigenesCorroboran"] = ",".join(sorted(origins))
        t["Corroboracion"] = int(t.get("Corroboracion") or 0) + int(r.get("Corroboracion") or 0)
        drop.add(r["Id"])
    if drop:
        stats["idmc unidas a su emergencia del SINPAD"] += len(drop)
    return [r for r in records if r["Id"] not in drop]


def tidy(records: list[dict], calendar: EnsoCalendar, stats: Counter) -> list[dict]:
    """Reglas de calidad para todo el catálogo, también con ``--desde-catalogo`` (las halló la revisión independiente de
    octubre de 2026; ``docs/memoria-desastres.md``, «Validación»)."""
    last_icen = max(calendar.icen) if calendar.icen else ""
    keep = []
    for r in records:
        # Los impactos de toda fila cuentan salvo que otra fila del mismo evento ya los detalle («no»).
        r["ImpactoEnTotales"] = r.get("ImpactoEnTotales") or "si"
        # Notas de prensa que no cuentan un desastre (bonos, reconstrucción, donaciones, crímenes): el titular manda.
        if r["Origen"] == "prensa" and C._OFF.search(re.match(r"«?([^»]*)", r.get("Descripción") or "").group(1)):
            stats["nota de prensa que no es un evento"] += 1
            continue
        # La fecha de un reporte del COEN o de una nota no es la del evento: nunca confianza alta.
        if r.get("FechaTipo") in ("informe", "publicacion") and r.get("Confianza") == "alta":
            r["Confianza"] = "media"
            stats["confianza alta → media (fecha de reporte o publicación)"] += 1
        # DesInventar pone el 1 de enero cuando no sabe el día (hay 5 veces más de lo esperable): mes, no día.
        if r["Origen"] == "desinventar" and r["PrecisionFecha"] == "dia" and r["Date"].endswith("-01-01"):
            r["PrecisionFecha"], r["FechaFin"] = "mes", ""
            if r.get("Confianza") == "alta":
                r["Confianza"] = "media"
            stats["DesInventar 1 de enero → precisión de mes"] += 1
        # Después del último mes con ICEN no se sabe la fase: «ICEN pendiente», no «sin asociación».
        if (last_icen and r["PrecisionFecha"] != "anio" and r["Date"][:7] > last_icen and r.get("AtribucionENSO") == "ninguna"):
            r["TipoEvento"], r["AtribucionENSO"] = "ICEN pendiente", "pendiente"
            stats["ICEN pendiente"] += 1
        keep.append(r)
    return merge_idmc_twins(keep, stats)


#: Un punto de la fuente a esta distancia o menos de la capital del distrito, la provincia o el departamento es esa
#: capital (el punto que el SINPAD pone cuando no hay uno de campo), no el lugar del evento.
DEFAULT_CAPITAL_KM = 0.5
#: El mismo punto (4 decimales, unos 11 m) en tantas filas o más de un distrito es un punto por defecto de la fuente,
#: salvo que esté en un centro poblado (``DEFAULT_PLACE_KM``): entonces es ese pueblo, que la fuente repite.
DEFAULT_REPEATS = 5
DEFAULT_PLACE_KM = 0.3


def _point_key(r: dict) -> Optional[tuple[float, float]]:
    try:
        return round(float(r["Latitud"]), 4), round(float(r["Longitud"]), 4)
    except (TypeError, ValueError, KeyError):
        return None


def default_point(r: dict, territory: Territory, repeats: Counter, places) -> str:
    """Por qué el punto de la fuente no es el lugar del evento («capital», «repetido»), o "" si lo es."""
    from enso.lugares import _km

    lat, lon = float(r["Latitud"]), float(r["Longitud"])
    code = r["Ubigeo"]
    for table, n in ((territory.dist, 6), (territory.prov, 4), (territory.dep, 2)):
        rec = table.get(code[:n]) if len(code) >= n else None
        if rec and rec.get("lat") is not None and rec.get("point") != "interior" and \
                _km(lat, lon, rec["lat"], rec["lon"]) <= DEFAULT_CAPITAL_KM:
            return "capital"
    # El centro poblado capital del distrito: el INEI y el IGN lo ubican a veces a cientos de metros del nomenclátor
    # (Santo Tomás, a 0,5 km), y el SINPAD usa también ese punto por defecto.
    sc = places.scale
    rows = places.rows.get(code, [])
    capital = [row for row in rows if row[3] == "capital de distrito" or row[4].endswith("0001")]
    if any(_km(lat, lon, row[2] / sc, row[1] / sc) <= DEFAULT_CAPITAL_KM for row in capital):
        return "capital"
    if repeats[(code, _point_key(r))] >= DEFAULT_REPEATS:
        if not any(_km(lat, lon, row[2] / sc, row[1] / sc) <= DEFAULT_PLACE_KM for row in rows if row not in capital):
            return "repetido"
    return ""


def place_names(r: dict, territory: Territory, places):
    """Los centros poblados del distrito que nombra la fila: su Ubicacion (un campo de lugar) o, si no, su
    descripción (con una palabra que presente el lugar)."""
    code = r["Ubigeo"]
    if len(code) != 6:
        return None
    names = territory.names(code)
    m = places.find(code, r.get("Ubicacion") or "", field=True, exclude=names) if (r.get("Ubicacion") or "").strip() else None
    if not (m and m.places):
        m = places.find(code, r.get("Descripción") or "", exclude=names)
    return m if m.places else None


def relocate(records: list[dict], territory: Territory, stats: Counter, places=None, basins=None) -> None:
    """Puntos y lugares con los límites y el nomenclátor vigentes, también con ``--desde-catalogo``; idempotente.

    - Un punto de la fuente que cae en un distrito creado después de 2020, en la misma provincia que el distrito que
      nombró la fuente, lleva el UBIGEO del punto (``fuentes.newer_sibling``).
    - Un punto de la fuente que no cae en el área asignada se reemplaza por la capital (como en ``fuentes.place``).
    - Un punto de la fuente que es la capital del distrito, la provincia o el departamento, o que la fuente repite en
      ``DEFAULT_REPEATS`` filas o más del distrito sin que sea un centro poblado, es un punto por defecto (el SINPAD lo
      pone cuando no hay uno de campo): vale como la capital.
    - Sin punto de la fuente, el centro poblado que nombra la fila (``enso.lugares``), dentro de su distrito:
      ``centro-poblado``, con su radio.
    - Los nombres son los del nomenclátor para el UBIGEO.
    - La capital (o el punto interior) de los demás se toma del nomenclátor: un distrito que no tenía coordenadas
      llevaba la capital de su provincia, a veces a más de 100 km.
    - La cuenca (ANA) es la del punto si es de la fuente o de un centro poblado; si no, la del distrito cuando el 80 %
      o más de él cae en una."""
    from enso import lugares as LG

    places = places or LG.lugares()
    basins = basins or LG.basins()
    repeats = Counter((r["Ubigeo"], _point_key(r)) for r in records if r.get("PrecisionGeo") == "coordenada-fuente")
    for r in records:
        code = r["Ubigeo"]
        names = territory.names(code)
        if (r.get("Departamento"), r.get("Provincia"), r.get("Distrito")) != names:
            r["Departamento"], r["Provincia"], r["Distrito"] = names  # el nomenclátor corrigió una grafía («Boquerón»)
            stats["nombres del nomenclátor actualizados"] += 1
        r["Lugar"] = r["LugarCodigo"] = r["RadioKm"] = r["Cuenca"] = r["CuencaCodigo"] = ""
        match = place_names(r, territory, places)
        if match:
            r["Lugar"] = " · ".join(dict.fromkeys(p.name for p in match.places))
            r["LugarCodigo"] = match.places[0].code
        if r.get("PrecisionGeo") == "coordenada-fuente":
            loc = F.locate_point(r["Latitud"], r["Longitud"])[0]
            if F.inside(territory, code, loc):
                why = default_point(r, territory, repeats, places)
                if not why:
                    _basin(r, basins.at(r["Latitud"], r["Longitud"]))
                    continue
                stats[f"punto por defecto de la fuente ({why}): no es el lugar del evento"] += 1
            else:
                sib = F.newer_sibling(code, loc)
                if sib:
                    r["Ubigeo"] = code = sib
                    r["Departamento"], r["Provincia"], r["Distrito"] = territory.names(sib)
                    r["Region"], r["AltitudCapital"] = territory.region(sib), territory.altitude(sib)
                    stats["punto de la fuente en un distrito creado después de 2020: UBIGEO del punto"] += 1
                    _basin(r, basins.at(r["Latitud"], r["Longitud"]))
                    continue
                stats["punto de la fuente fuera del área asignada: capital"] += 1
        # La capital del distrito que nombra la fuente («Puerto Maldonado») no es más fina que el distrito.
        pt = match.point() if match and not all(_is_capital(p, territory) for p in match.places) else None
        if pt and not _inside_district(code, pt[0], pt[1]):
            # Un centro poblado a metros del límite (los límites se simplifican a unos 110 m): el punto publicado
            # siempre cae en su distrito, así que queda la capital (y el nombre en Lugar).
            if r.get("PrecisionGeo") == "centro-poblado":
                stats["centro poblado al otro lado del límite del distrito: capital"] += 1
            pt = None
        if pt:
            lat, lon, radius = round(pt[0], 5), round(pt[1], 5), pt[2]
            if r.get("PrecisionGeo") != "centro-poblado" or _point_key(r) != (round(lat, 4), round(lon, 4)):
                stats["punto del centro poblado que nombra la fuente"] += 1
            r["Latitud"], r["Longitud"], r["PrecisionGeo"], r["RadioKm"] = lat, lon, "centro-poblado", radius
            _basin(r, basins.at(lat, lon))
            continue
        lat, lon, geo = territory.point(code)
        _basin(r, LG.district_basin(code))
        if lat is None:
            continue
        old = (r.get("Latitud"), r.get("Longitud"))
        try:
            same = (round(float(old[0]), 5), round(float(old[1]), 5)) == (lat, lon) and r["PrecisionGeo"] == geo
        except (TypeError, ValueError):
            same = False
        if not same:
            if r["PrecisionGeo"] not in ("coordenada-fuente", "centro-poblado"):
                stats[f"punto del nomenclátor actualizado ({geo})"] += 1
            r["Latitud"], r["Longitud"], r["PrecisionGeo"] = lat, lon, geo


def _inside_district(code: str, lat: float, lon: float) -> bool:
    from enso.limites import limits

    lim = limits()
    d = lim.levels[6].get(code)
    x, y = lon * lim.scale, lat * lim.scale
    return bool(d) and lim.containing(6, x, y, code) == code


def _is_capital(place, territory: Territory) -> bool:
    from enso.lugares import _km, name_key

    rec = territory.dist.get(place.district, {})
    return place.code.endswith("0001") or place.category == "capital de distrito" or \
        name_key(place.name) == name_key(rec.get("capital", "")) or \
        (rec.get("lat") is not None and _km(place.lat, place.lon, rec["lat"], rec["lon"]) <= DEFAULT_CAPITAL_KM)


def _basin(r: dict, basin: Optional[dict]) -> None:
    r["Cuenca"], r["CuencaCodigo"] = (basin["name"], basin["code"]) if basin else ("", "")


def redate(records: list[dict], manifest: dict, caches: list[Path], territory: Territory, calendar: EnsoCalendar,
           stats: Counter) -> None:
    """Con ``--desde-catalogo``: vuelve a leer de la caché las fuentes cuyo lector cambió las fechas (el SINPAD de
    2016-2018, por la hora de Lima guardada como UTC) y corrige la fecha y lo que depende de ella en las filas del
    mismo Id, sin tocar sus enlaces de corroboración."""
    fields = ("Date", "FechaFin", "PrecisionFecha", "Anio", "Mes", "AnioHidrologico", "FaseENSO", "EventoENSO", "ICEN",
              "ONI", "TipoEvento", "AtribucionENSO")
    by_id = {r["Id"]: r for r in records}
    for src in manifest["fuentes"]:
        if src.get("lector") != "sinpad" or not any((c / src["archivo"]).exists() for c in caches):
            continue
        path = fetch(src, caches, False, True)
        for new in READERS["sinpad"](path, territory, calendar, Counter()):
            old = by_id.get(new["Id"])
            if old and old["Date"] != new["Date"]:
                for k in fields:
                    old[k] = "" if new.get(k) is None else str(new[k])
                stats["SINPAD 2016-2018: fecha corregida (hora de Lima)"] += 1


def catalog_csv(records: list[dict]) -> bytes:
    """El catálogo como CSV UTF-8 con BOM (para que Excel lea las tildes)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(E.COLUMNS)
    for r in records:
        w.writerow([csv_safe("" if r.get(c) is None else r.get(c)) for c in E.COLUMNS])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def write_zip(records: list[dict], path: Path, name: str = "eventos.csv") -> None:
    """El CSV dentro de un ZIP: sin comprimir pasa de los 25 MiB que acepta Cloudflare Pages por archivo
    (y de lo que conviene versionar en git). Fecha fija y orden estable: el ZIP solo cambia si cambian
    los datos."""
    info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
    info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(info, catalog_csv(records), compresslevel=9)


def _n(v) -> int:
    try:
        return int(float(v)) if v not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def web_payload(records: list[dict]) -> tuple[dict, dict[str, dict]]:
    dicts: dict[str, list[str]] = {k: [] for k in ("DangerType", "TipoEvento", "FaseENSO", "Origen", "Confianza")}
    index = {k: {} for k in dicts}

    def idx(k: str, v: str) -> int:
        if v not in index[k]:
            index[k][v] = len(dicts[k])
            dicts[k].append(v)
        return index[k][v]

    rows, detail = [], defaultdict(dict)
    for i, r in enumerate(records):
        count = r.get("ImpactoEnTotales") != "no"
        date = r["Date"][:4] if r["PrecisionFecha"] == "anio" else r["Date"][:7] if r["PrecisionFecha"] == "mes" else r["Date"]
        rows.append([
            date, idx("DangerType", r["DangerType"]), r["Ubigeo"], idx("TipoEvento", r["TipoEvento"]),
            idx("FaseENSO", r["FaseENSO"]), idx("Origen", r["Origen"]), idx("Confianza", r["Confianza"]),
            _n(r["Fallecidos"]) + _n(r["Desaparecidos"]) if count else 0,
            (_n(r["Afectados"]) + _n(r["Damnificados"]) or _n(r["Desplazados"])) if count else 0,
            _n(r["ViviendasDestruidas"]) if count else 0, i,
        ])
        detail[r["Ubigeo"][:2]][str(i)] = [
            r["Descripción"], r["Ubicacion"], r["FuenteCita"], r["Fuente"], r["DuraciónEvento"] or "",
            r["PrecisionFecha"], r["Id"], r["DangerTypeMetodo"], r["AtribucionENSO"],
            {k: r[k] for k in E.IMPACT_COLUMNS if r.get(k)},
            int(r.get("Corroboracion") or 0), [u for u in (r.get("FuentesAdicionales") or "").split(" | ") if u],
            r.get("FechaTipo") or "evento",
        ]
    return {"cols": WEB_COLS, "dict": dicts, "rows": rows}, detail


def area_names(t: Territory) -> dict:
    return {
        "departamento": {c: d["name"] for c, d in t.dep.items()},
        "provincia": {c: d["name"] for c, d in t.prov.items()},
        "distrito": {c: d["name"] for c, d in t.dist.items()},
    }


def area_attrs(t: Territory) -> dict:
    out = {}
    for c, a in t.attrs.items():
        if c not in t.dist:
            continue
        out[c] = [_n(a.get("poblacion_2020")), float(a["pobreza_pct"]) if a.get("pobreza_pct") else None,
                  float(a["idh_2019"]) if a.get("idh_2019") else None, _n(a.get("altitud")) or None,
                  t.region(c)]
    return out


INDICATOR_COLS = ["nivel", "codigo", "nombre", "departamento", "registros", "aniosConEvento", "aniosCobertura",
                  "frecuenciaAnual", "frecuenciaIC_inf", "frecuenciaIC_sup", "periodoRetorno", "periodoRetornoIC_inf",
                  "periodoRetornoIC_sup", "prob5Anios", "prob5AniosIC_inf", "prob5AniosIC_sup",
                  "distritoAnios", "distritoAniosPorAnio", "razonNino", "razonNinoIC_inf", "razonNinoIC_sup",
                  "dispersionNino", "grandesNinos", "nGrandesNinos",
                  "muestraPequena", "registrosIntensivos", "peligroPrincipal", "ultimoEvento", "Fallecidos",
                  "Desaparecidos", "Afectados", "Damnificados", "Desplazados", "ViviendasDestruidas", "poblacion2020"]


def write_indicators(ind: dict, t: Territory, path_for) -> None:
    names = area_names(t)
    for level, areas in ind.items():
        if level == "pais":
            continue
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(INDICATOR_COLS)
        for code, s in sorted(areas.items()):
            name = names.get(level, {}).get(code, code)
            dep = names["departamento"].get(code[:2], "") if level != "region" else ""
            w.writerow([level, code, name, dep, s["registros"], s["aniosConEvento"], s["aniosCobertura"],
                        s["frecuenciaAnual"], *s["frecuenciaIC"], s["periodoRetorno"], *s["periodoRetornoIC"],
                        s["prob5Anios"], *s["prob5AniosIC"], s["distritoAnios"], s["distritoAniosPorAnio"],
                        s["razonNino"], *s["razonNinoIC"], s["dispersionNino"], "; ".join(s["grandesNinos"]),
                        len(s["grandesNinos"]),
                        "si" if s["muestraPequena"] else "no", s["registrosIntensivos"],
                        s["peligros"][0][0] if s["peligros"] else "", (s["ultimo"] or {}).get("Date", ""),
                        s["impactos"].get("Fallecidos", 0), s["impactos"].get("Desaparecidos", 0),
                        s["impactos"].get("Afectados", 0), s["impactos"].get("Damnificados", 0),
                        s["impactos"].get("Desplazados", 0), s["impactos"].get("ViviendasDestruidas", 0),
                        t.population(code) if level != "region" else ""])
        path_for(level).write_text("\ufeff" + buf.getvalue(), encoding="utf-8")


#: Primera temporada de la validación fuera de muestra: la primera completa del SINPAD (el de 2015-16 empieza en enero).
VALIDATION_FROM = 2016


def validation(records: list[dict], t: Territory, calendar: EnsoCalendar, years: range, ind: dict) -> Optional[dict]:
    """Prueba fuera de muestra de los indicadores (``enso.historico.validacion``) con las temporadas completas del SINPAD
    posteriores al periodo homogéneo: de ``VALIDATION_FROM`` a la última que terminó (en junio) antes del último
    registro."""
    last = max((r["Date"] for r in records if r.get("Origen") == "sinpad" and len(r["Date"]) >= 7), default="")
    if not last:
        return None
    y, m = int(last[:4]), int(last[5:7])
    test = range(VALIDATION_FROM, (y - 1 if m >= 7 else y - 2) + 1)
    if len(test) < 3:
        return None
    names = area_names(t)
    out = V.validate(records, t.dist, years, test, nino_hydro_years(calendar, test), ind, names)
    out["calibracion"] = V.calibration(records, t.dist)
    out["grandesNinos"] = V.great_repeat(records, t.dist)
    peak = {y: v for y in years if (v := peak_icen(calendar, y)) is not None}
    out["sensibilidadNino"] = V.sensitivity(records, years, nino_hydro_years(calendar, years),
                                            nino_hydro_years_any(calendar, years), peak, ind, names)
    out["icenPico"] = {str(y): round(v, 2) for y, v in sorted(peak.items())}
    return out


def write_dictionary(records: list[dict], path: Path) -> None:
    """``diccionario.csv``: tipo, contenido y regla de cada columna del catálogo (``esquema.COLUMN_DOCS``), con el
    porcentaje de filas que traen el dato, en total y por origen (los vacíos dicen qué no reporta cada fuente)."""
    origins = [o for o, _ in Counter(r["Origen"] for r in records).most_common()]
    rows_by = defaultdict(list)
    for r in records:
        rows_by[r["Origen"]].append(r)

    def pct(rows: list[dict], c: str) -> float:
        return round(100 * sum(1 for r in rows if r.get(c) not in (None, "")) / len(rows), 1) if rows else 0.0

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["columna", "grupo", "tipo", "descripcion", "valores", "conDato_pct"] + [f"conDato_pct_{o}" for o in origins])
    for c in E.COLUMNS:
        tipo, desc, rule = E.COLUMN_DOCS[c]
        w.writerow([c, "equipo de prevención" if c in E.TEAM_COLUMNS else "adicional", tipo, desc, rule, pct(records, c),
                    *(pct(rows_by[o], c) for o in origins)])
    path.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")


CONTEXT_COLS = ["ubigeo", "departamento", "provincia", "distrito", "poblacion2020", "registros", "aniosConEvento",
                "frecuenciaAnual", "frecuenciaIC_inf", "frecuenciaIC_sup", "grandesNinos", "registrosEventoEnCurso",
                "ingemmetPuntos", "ingemmetFlujos", "ingemmetDeslizamientos", "ingemmetCaidas", "zonasCriticasIngemmet", "puntosCriticosANA",
                "puntosCriticosANAMuyAlto", "poblacionExpuestaANA", "viviendasExpuestasANA", "costoAccionesANA",
                "establecimientosSaludAfectados2023"]
ING_ORDER = ["total", "flujos", "deslizamientos", "caidas", "complejos", "reptacion", "otros"]


def write_context(context: dict, ind: dict, records: list[dict], ongoing: Optional[str], t: Territory,
                  json_path: Path, csv_path: Path, generated: str) -> None:
    """Peligro identificado hoy en cada distrito, junto a su historial (para el perfil y para el equipo)."""
    ing, zc = context.get("ingemmet-inventario", {}), context.get("ingemmet-criticas", {})
    ana, ips = context.get("ana-puntos", {}), context.get("ipress-2023", {})
    now = Counter(r["Ubigeo"] for r in records if len(r["Ubigeo"]) == 6 and ongoing and r["TipoEvento"] == ongoing)
    out = {}
    for code in sorted(set(ing) | set(zc) | set(ana) | set(ips)):
        d = {}
        if code in ing:
            d["ing"] = [ing[code].get(k, 0) for k in ING_ORDER]
        for k, src in (("zc", zc), ("ana", ana), ("ips", ips)):
            if code in src:
                d[k] = src[code]
        out[code] = d
    json_path.write_text(json.dumps({"generatedAt": generated, "ingCols": ING_ORDER,
                                     "anaCols": ["punto", "sector", "peligro", "nivel", "poblacion", "viviendas", "accion", "costo"],
                                     "distritos": out}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    dist = ind.get("distrito", {})
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CONTEXT_COLS)
    for code in sorted(set(out) | set(dist)):
        if code not in t.dist:
            continue
        s, d = dist.get(code), out.get(code, {})
        dep, prov, name = t.names(code)
        a = d.get("ana", [])
        w.writerow([code, dep, prov, name, t.population(code) or "",
                    s["registros"] if s else 0, s["aniosConEvento"] if s else 0, s["frecuenciaAnual"] if s else "",
                    *(s["frecuenciaIC"] if s else ("", "")), "; ".join(s["grandesNinos"]) if s else "", now.get(code, 0),
                    *(d.get("ing", [0] * 7)[:4]), len(d.get("zc", [])), len(a), sum(1 for x in a if x[3] == "Muy Alto"),
                    round(sum(x[4] or 0 for x in a)), round(sum(x[5] or 0 for x in a)), round(sum(x[7] or 0 for x in a)),
                    len(d.get("ips", []))])
    csv_path.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")


PREVENTION_COLS = ["ubigeo", "departamento", "provincia", "distrito"]  # + enlace.prevention()["columnas"]


def write_prevention(prev: dict, evidence: dict, t: Territory, path_json: Path, path_csv: Path, generated: str) -> None:
    """Indicadores de prevención (``enlace.prevention``) para el sitio, con la lista de declaratorias y evaluaciones
    (fecha, tipo, peligro, enlace y distritos), y el CSV por distrito."""
    decrees = [[d["fecha"], d["numero"], d["tipo"], d["peligro"], d["url"], d["ubigeos"]] for d in evidence.get("decretos", [])]
    # Los informes técnicos van uno por uno; los puntos del inventario de INGEMMET (miles) solo como cifras por distrito.
    evals = [[e["anio"], e["institucion"], e["titulo"], e["url"], e["ubigeos"]]
             for e in sorted(evidence.get("evaluaciones", []), key=lambda e: (e["anio"], e["titulo"]))
             if e.get("tipo") != "inventario"]
    appeal_cols = ["fecha", "codigo", "nombre", "tipo", "modalidad", "clima", "montoCHF", "beneficiarios", "url"]
    appeals = [[a[k] for k in appeal_cols] for a in evidence.get("llamamientos", [])]
    path_json.write_text(json.dumps({"generatedAt": generated, **prev,
                                     "decretos": {"cols": ["fecha", "numero", "tipo", "peligro", "url", "ubigeos"], "rows": decrees},
                                     "evaluaciones": {"cols": ["anio", "institucion", "titulo", "url", "ubigeos"], "rows": evals},
                                     "llamamientos": {"cols": appeal_cols, "rows": appeals}},
                                    ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(PREVENTION_COLS + prev["columnas"])
    for code, vals in prev["distritos"].items():
        if len(code) != 6:
            continue
        dep, prov, dist = t.names(code)
        w.writerow([code, dep, prov, dist, *vals])
    path_csv.write_text(buf.getvalue(), encoding="utf-8")


def harvest(manifest: dict, territory: Territory, calendar: EnsoCalendar, caches: list[Path], parcial: bool,
            offline: bool, accept_changes: bool) -> tuple[list[dict], dict, dict]:
    """Pasos 1 a 3b: lee todas las fuentes y devuelve los registros (ordenados), las capas de contexto y la evidencia de
    prevención. Anota en ``manifest`` lo que salió de cada fuente."""
    def obtain(src: dict) -> Optional[Path]:
        """El archivo de la fuente; con ``--parcial``, lo bajado hasta ahora, o nada si la cosecha (de la segunda ronda)
        aún no empezó o no se puede retomar: esa fuente se salta y queda anotada como pendiente."""
        got = snapshot(src, caches) if parcial else None
        if got:
            return got
        if parcial and offline and src.get("lector") in {**CANDIDATES, **EVIDENCE} \
                and not any((c / src["archivo"]).exists() for c in caches):
            print(f"{src['id']}: cosecha pendiente, se salta", file=sys.stderr)
            src["parcial"] = "pendiente"
            return None
        return fetch(src, caches, accept_changes, offline)

    records: list[dict] = []
    context: dict[str, dict] = {}
    candidates: dict[str, list[dict]] = defaultdict(list)
    evidence: dict[str, list[dict]] = defaultdict(list)
    for src in manifest["fuentes"]:
        lector = src.get("lector")
        if lector in READERS:
            path = obtain(src)
            skipped: Counter = Counter()
            got = list(READERS[lector](path, territory, calendar, skipped))
            src["registros"] = len(got)
            if skipped:
                src["descartados"] = dict(skipped.most_common())
            records += got
        elif lector in CANDIDATES:
            path = obtain(src)
            if path is None:
                continue
            skipped = Counter()
            got = list(CANDIDATES[lector](path, territory, calendar, skipped, src))
            for r in got:
                r["_fuente"] = src["id"]
            src["candidatos"] = len(got)
            if skipped:
                src["descartados"] = dict(skipped.most_common())
            candidates[lector] += got
        elif lector in EVIDENCE:
            path = obtain(src)
            if path is None:
                continue
            got = EVIDENCE[lector](json.loads(path.read_text(encoding="utf-8")), territory, src)
            src["registros"] = len(got)
            evidence[EVIDENCE_KIND.get(lector, "evaluaciones")] += got
        elif lector in CONTEXT:
            path = obtain(src)
            context[lector] = CONTEXT[lector](json.loads(path.read_text(encoding="utf-8")), territory)
            src["registros"] = sum(v["total"] if isinstance(v, Counter) else len(v) for v in context[lector].values())
    cur = curated_records(territory, calendar)
    for src in manifest["fuentes"]:
        if src.get("lector") == "curado":
            src["registros"] = len(cur)
    records += cur
    records = apply_reviews(records)
    # Segunda ronda: lo que cuentan el COEN y la prensa se une a las filas del mismo evento (o queda como fila propia).
    link_stats: Counter = Counter()
    ordered = [c for k in LINK_ORDER for c in sorted(candidates.get(k, []), key=lambda r: (r["Date"], r["Id"]))]
    added = enlace.link(records, ordered, link_stats)
    by_src = Counter(r["_fuente"] for r in added)
    linked = Counter(r["_fuente"] for r in ordered) - by_src
    for src in manifest["fuentes"]:
        if src.get("lector") in CANDIDATES:
            src["registros"] = by_src.get(src["id"], 0)
            src["corroboran"] = linked.get(src["id"], 0)
    records += added
    manifest["enlace"] = dict(sorted(link_stats.items()))
    ids = Counter(r["Id"] for r in records)
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        raise SystemExit(f"Id repetidos: {dup[:5]}")
    records.sort(key=lambda r: (r["Date"], r["Ubigeo"], r["Id"]))
    return records, context, evidence


def read_catalog(path: Path) -> list[dict]:
    """Las filas del ``eventos.zip`` publicado, como las escribió ``catalog_csv`` (sin el apóstrofo de ``csv_safe``)."""
    with zipfile.ZipFile(path) as z, z.open("eventos.csv") as f:
        rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")))
    for r in rows:
        for k, v in r.items():
            if v[:1] == "'" and v[1:2] in ("=", "+", "-", "@"):
                r[k] = v[1:]
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, action="append", help="caché de descargas (puede repetirse; por omisión "
                    "~/.cache/enso-historico)")
    ap.add_argument("--aceptar-cambios", action="store_true")
    ap.add_argument("--sin-red", action="store_true", help="no descargar: usar solo la caché")
    ap.add_argument("--parcial", action="store_true", help="usar lo bajado de las cosechas largas que siguen a medias")
    ap.add_argument("--icen", type=Path, default=INDICES["icen"][1])
    ap.add_argument("--oni", type=Path, default=INDICES["oni"][1])
    ap.add_argument("--indices-al-dia", type=Path, metavar="CARPETA",
                    help="descargar el ICEN y el ONI vigentes en CARPETA (aunque se use --sin-red) en lugar de --icen/--oni")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--desde-catalogo", action="store_true",
                    help="no leer las fuentes de eventos: rehacer los archivos publicados a partir del eventos.zip "
                         "publicado (con las capas de contexto de la caché); la prevención, que necesita la evidencia "
                         "cosechada, no cambia")
    args = ap.parse_args(argv)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    territory = Territory()
    if args.indices_al_dia:
        args.indices_al_dia.mkdir(parents=True, exist_ok=True)
        args.icen, args.oni = fresh_indices(args.indices_al_dia)
    calendar = EnsoCalendar.from_files(args.icen, args.oni)
    caches = args.cache or [CACHE]
    quality: Counter = Counter()
    if args.desde_catalogo:
        records = read_catalog(args.out / "eventos.zip")
        # El catálogo publicado ya pasó por las reglas de calidad y el manifiesto guarda cuántas filas tocó cada una: se
        # suman a las de esta corrida (que sobre un catálogo ya limpio son 0) para que el recuento no se pierda.
        quality.update(manifest.get("calidad") or {})
        last_icen = max(calendar.icen) if calendar.icen else ""
        stale = sum(1 for r in records if r.get("TipoEvento") == "ICEN pendiente" and r["Date"][:7] <= last_icen)
        if stale:
            # Clasificar de nuevo el evento ENSO necesita las fuentes (nivel del SINPAD, causa): solo la construcción completa.
            raise SystemExit(f"{stale} registros con «ICEN pendiente» ya tienen ICEN (hasta {last_icen}): haga la "
                             "construcción completa en lugar de --desde-catalogo")
        redate(records, manifest, caches, territory, calendar, quality)
        # Los registros curados se leen de nuevo (los YAML del repositorio pueden ser más nuevos que el catálogo).
        cur = apply_reviews(curated_records(territory, calendar), strict=False)
        records = [r for r in records if r["Origen"] != "curado"] + cur
        for src in manifest["fuentes"]:
            if src.get("lector") == "curado":
                src["registros"] = len(cur)
        context = {s["lector"]: CONTEXT[s["lector"]](json.loads(fetch(s, caches, False, True).read_text(encoding="utf-8")),
                                                     territory)
                   for s in manifest["fuentes"] if s.get("lector") in CONTEXT}
        evidence = None
        generated = json.loads((args.out / "resumen.json").read_text(encoding="utf-8"))["generatedAt"]
    else:
        records, context, evidence = harvest(manifest, territory, calendar, caches, args.parcial, args.sin_red,
                                             args.aceptar_cambios)
        generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    relocate(records, territory, quality)
    records = tidy(records, calendar, quality)
    mark_duplicate_impacts(records)
    records.sort(key=lambda r: (r["Date"], r["Ubigeo"], r["Id"]))
    manifest["calidad"] = dict(sorted(quality.items()))

    first, last = manifest["cobertura"]["homogenea"]
    years = range(first, last + 1)
    nino = nino_hydro_years(calendar, years)
    current = next((e for e in calendar.events if e["ongoing"] and e["phase"] == "warm"), None)
    ongoing = calendar.phase(current["start"]).short if current else None
    homogeneous = set(manifest["cobertura"]["origenes"])
    ind = by_area(records, years, nino, homogeneous)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "detalle").mkdir(exist_ok=True)
    write_zip(records, args.out / "eventos.zip")
    (args.out / "eventos.csv").unlink(missing_ok=True)
    payload, detail = web_payload(records)
    payload["generatedAt"] = generated
    (args.out / "eventos.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for dep, d in detail.items():
        (args.out / "detalle" / f"{dep}.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    all_years = range(min(int(r["Anio"]) for r in records), max(int(r["Anio"]) for r in records) + 1)
    summary = {
        "generatedAt": generated, "registros": len(records),
        "cobertura": {**manifest["cobertura"], "anios": [all_years.start, all_years.stop - 1]},
        # El sitio publicado no enlaza al repositorio (tools/prepare_site --hide-repo).
        "fuentes": [{k: (None if k == "url" and REPO in (s.get(k) or "") else s.get(k))
                     for k in ("id", "nombre", "tipo", "url", "pagina", "licencia", "cobertura", "registros", "corroboran",
                               "parcial", "nota", "obtenido")}
                    for s in manifest["fuentes"]],
        "eventoEnCurso": ongoing,
        "grandesNinos": GREAT,
        "eventosNombrados": [{"nombre": n, "desde": a, "hasta": b, "departamentos": sorted(d) if d else None} for a, b, n, d in NAMED],
        "aniosNino": sorted(nino),
        "eventosICEN": [{"fase": e["phase"], "inicio": e["start"], "fin": e["end"], "pico": e["peak"],
                         "magnitud": e["magnitude"], "enCurso": e["ongoing"]} for e in calendar.events],
        "icenUltimo": max(calendar.icen.items()) if calendar.icen else None,
        "peligros": {k: {"grupo": v[0], "irdr": v[1]} for k, v in E.DANGER_TYPES.items()},
        "nombres": area_names(territory),
        "atributos": {"cols": ["poblacion2020", "pobrezaPct", "idh2019", "altitud", "region"], "distritos": area_attrs(territory)},
        "columnas": E.COLUMNS,
        "calidad": manifest["calidad"],
        # De dónde salió el calendario ENSO (el ICEN de los últimos meses es preliminar).
        "indicesENSO": {k: {"archivo": p.name, "sha256": sha256(p), "ultimoMes": last_month}
                        for k, p, last_month in (("icen", args.icen, max(calendar.icen) if calendar.icen else None),
                                                 ("oni", args.oni, max(calendar.oni) if calendar.oni else None))},
        "validacion": validation(records, territory, calendar, years, ind),
    }
    (args.out / "resumen.json").write_text(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if evidence is not None:
        prev = enlace.prevention(records, evidence["decretos"], evidence["evaluaciones"], evidence["llamamientos"],
                                 districts={c: territory.population(c) or 0.0 for c in territory.dist})
        write_prevention(prev, evidence, territory, args.out / "prevencion.json", DATA / "prevencion-distrito.csv",
                         generated)
    write_indicators(ind, territory, lambda lvl: DATA / f"indicadores-{lvl}.csv")
    write_context(context, ind, records, ongoing, territory, args.out / "contexto.json", DATA / "contexto-distrito.csv", generated)
    write_dictionary(records, DATA / "diccionario.csv")
    # Copias en el sitio para descargarlas sin pasar por el repositorio.
    for name in [f"indicadores-{lvl}.csv" for lvl in ind if lvl != "pais"] + ["contexto-distrito.csv",
                                                                             "prevencion-distrito.csv", "diccionario.csv"]:
        shutil.copyfile(DATA / name, args.out / name)
    if not args.desde_catalogo:
        manifest["generado"] = generated
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(records)} registros · {Counter(r['Origen'] for r in records)} · "
          f"{(args.out / 'eventos.json').stat().st_size / 1024:.0f} KB web")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
