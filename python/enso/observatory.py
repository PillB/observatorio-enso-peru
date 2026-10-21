"""Orquestador de publicación del Observatorio ENSO Perú (v4).

Flujo de una corrida:
  1. Para cada fuente del catálogo: descargar (con canales alternativos),
     parsear con parsers tolerantes y validar.
  2. Si una fuente falla, reutilizar su último resultado válido de la
     publicación anterior (marcado como arrastrado, con su fecha real).
  3. Construir series, índices derivados, estados oficiales y la señal GRD.
  4. Escribir todos los artefactos en un directorio temporal, validar la
     coherencia y reemplazar la publicación de forma atómica.
  5. Registrar cada incidencia en ``run-report.json`` (severidad, fuente,
     etapa, huella) para que el flujo de CI abra o cierre issues.

Uso:
    python -m enso.observatory --out public/data \
        [--previous https://pillb.github.io/observatorio-enso-peru/data] \
        [--fixtures tests/fixtures/sources] [--offline]
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
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .feeds import FormatChanged, Parsed
from .feeds import cpc, peru
from . import archive
from . import signals as sig

SCHEMA = "observatorio-enso/4"
PIPELINE_VERSION = "4.0.0"
REPO = Path(__file__).resolve().parents[2]
LIVE_DATA = "https://pillb.github.io/observatorio-enso-peru/data"


# ---------------------------------------------------------------------------
# Registro de incidencias
# ---------------------------------------------------------------------------
@dataclass
class Event:
    severity: str  # info | warning | error | critical
    source: str
    stage: str  # fetch | parse | validate | derive | publish
    code: str
    message: str

    @property
    def fingerprint(self) -> str:
        return hashlib.sha1(f"{self.source}|{self.stage}|{self.code}".encode()).hexdigest()[:10]

    def as_dict(self) -> dict:
        return {"severity": self.severity, "source": self.source, "stage": self.stage, "code": self.code,
                "message": self.message, "fingerprint": self.fingerprint}


class EventLog:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def add(self, severity: str, source: str, stage: str, code: str, message: str) -> None:
        ev = Event(severity, source, stage, code, message[:2000])
        self.events.append(ev)
        print(f"[{severity.upper():8}] {source}/{stage}/{code}: {message[:300]}", file=sys.stderr)

    def worst(self) -> str:
        order = ["info", "warning", "error", "critical"]
        return max((e.severity for e in self.events), key=order.index, default="info")


# ---------------------------------------------------------------------------
# Catálogo de fuentes
# ---------------------------------------------------------------------------
@dataclass
class Source:
    id: str
    institution: str
    product: str
    urls: list[str]
    parse: Callable[[Any], Parsed]
    cadence_days: int  # cada cuánto publica la institución
    slo_days: int  # antigüedad máxima aceptable del último periodo observado
    layer: str  # rapid | index | official
    fixture: str
    binary: bool = False
    archive: bool = True
    save: bool = False
    docs: str = ""
    critical: bool = False
    accept: tuple = ()


def _txt(fn):
    return lambda resp: fn(resp.text)


def _parse_enfen(resp) -> Parsed:
    """Listado de comunicados (HTML o WP JSON) → comunicado más reciente."""
    body = resp.text
    if body.lstrip().startswith("["):
        lst = peru.parse_enfen_wp_posts(body)
        if lst.data and "comunicado oficial" in lst.data[0]["text"].lower():
            try:
                c = peru.parse_enfen_communique(lst.data[0]["text"], source=lst.data[0]["url"])
                return Parsed({"listing": lst.data[:6], "latest": c.data}, lst.fingerprint, c.warnings)
            except FormatChanged:
                pass
        return Parsed({"listing": [{k: v for k, v in i.items() if k != "text"} for i in lst.data[:6]]}, lst.fingerprint)
    lst = peru.parse_enfen_listing(body)
    return Parsed({"listing": lst.data[:6]}, lst.fingerprint)


SOURCES: list[Source] = [
    Source("cpc-wksst", "NOAA / CPC", "Índices semanales de TSM en regiones Niño (OISST v2.1, base 1991–2020)",
           ["https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for"], _txt(cpc.parse_weekly),
           7, 16, "rapid", "cpc-wksst9120.for", critical=True,
           docs="https://www.cpc.ncep.noaa.gov/data/indices/"),
    Source("cpc-sstoi", "NOAA / CPC", "Índices mensuales de TSM en regiones Niño (OISST v2.1, base 1991–2020)",
           ["https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices"], _txt(lambda t: cpc.parse_nino_monthly(t, name="sstoi")),
           31, 50, "index", "cpc-sstoi.indices", docs="https://www.cpc.ncep.noaa.gov/data/indices/"),
    Source("psl-ersst6-nino12", "NOAA / PSL", "Anomalía mensual de TSM Niño 1+2 (ERSSTv6)",
           ["https://psl.noaa.gov/data/correlation/nina1.anom.data"],
           _txt(lambda t: cpc.parse_psl_matrix(t, name="ersst6-nino12")), 31, 50, "index", "psl-nina1.anom.data",
           docs="https://psl.noaa.gov/data/timeseries/month/DS/NINO12/"),
    Source("psl-ersst6-nino34", "NOAA / PSL", "Anomalía mensual de TSM Niño 3.4 (ERSSTv6)",
           ["https://psl.noaa.gov/data/correlation/nina34.anom.data"],
           _txt(lambda t: cpc.parse_psl_matrix(t, name="ersst6-nino34")), 31, 50, "index", "psl-nina34.anom.data",
           docs="https://psl.noaa.gov/data/timeseries/month/DS/NINO34/"),
    Source("cpc-roni", "NOAA / CPC", "RONI — Índice Oceánico Relativo de El Niño (oficial)",
           ["https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"], _txt(lambda t: cpc.parse_seasonal(t, name="roni")),
           31, 80, "index", "cpc-roni.txt", critical=True,
           docs="https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php"),
    Source("cpc-oni", "NOAA / CPC", "ONI — Índice Oceánico de El Niño (tradicional)",
           ["https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"], _txt(lambda t: cpc.parse_seasonal(t, name="oni")),
           31, 80, "index", "cpc-oni.txt"),
    Source("cpc-soi", "NOAA / CPC", "Índice de Oscilación del Sur (Tahití − Darwin, estandarizado)",
           ["https://www.cpc.ncep.noaa.gov/data/indices/soi"],
           _txt(lambda t: cpc.parse_year_matrix(t, lo=-12, hi=12, name="soi")), 31, 50, "index", "cpc-soi.txt"),
    Source("cpc-tahiti", "NOAA / CPC", "Presión a nivel del mar en Tahití",
           ["https://www.cpc.ncep.noaa.gov/data/indices/tahiti"],
           _txt(lambda t: cpc.parse_year_matrix(t, lo=-50, hi=1100, name="tahiti")), 31, 50, "index", "cpc-tahiti.txt"),
    Source("cpc-darwin", "NOAA / CPC", "Presión a nivel del mar en Darwin",
           ["https://www.cpc.ncep.noaa.gov/data/indices/darwin"],
           _txt(lambda t: cpc.parse_year_matrix(t, lo=-50, hi=1100, name="darwin")), 31, 50, "index", "cpc-darwin.txt"),
    Source("cpc-wpac850", "NOAA / CPC", "Índice de vientos alisios a 850 hPa, Pacífico occidental (135°E–180°)",
           ["https://www.cpc.ncep.noaa.gov/data/indices/wpac850"],
           _txt(lambda t: cpc.parse_year_matrix(t, lo=-30, hi=30, name="wpac850")), 31, 50, "index", "cpc-wpac850.txt"),
    Source("cpc-cpac850", "NOAA / CPC", "Índice de vientos alisios a 850 hPa, Pacífico central (175°O–140°O)",
           ["https://www.cpc.ncep.noaa.gov/data/indices/cpac850"],
           _txt(lambda t: cpc.parse_year_matrix(t, lo=-30, hi=30, name="cpac850")), 31, 50, "index", "cpc-cpac850.txt"),
    Source("cpc-epac850", "NOAA / CPC", "Índice de vientos alisios a 850 hPa, Pacífico oriental (135°O–120°O)",
           ["https://www.cpc.ncep.noaa.gov/data/indices/epac850"],
           _txt(lambda t: cpc.parse_year_matrix(t, lo=-30, hi=30, name="epac850")), 31, 50, "index", "cpc-epac850.txt"),
    Source("cpc-heat", "NOAA / CPC", "Contenido de calor de los 300 m superiores en el Pacífico ecuatorial (GODAS)",
           ["https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ocean/index/heat_content_index.txt"],
           _txt(cpc.parse_heat_content), 31, 50, "index", "cpc-heat-content.txt",
           docs="https://www.cpc.ncep.noaa.gov/products/GODAS/"),
    Source("igp-icen", "ENFEN / IGP", "ICEN oficial (Nota Técnica ENFEN 01-2024)",
           ["http://met.igp.gob.pe/datos/ICEN.txt", "https://met.igp.gob.pe/datos/ICEN.txt"],
           _txt(peru.parse_icen_txt), 31, 100, "index", "igp-icen.txt",
           docs="https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen"),
    Source("cpc-ensodisc", "NOAA / CPC", "ENSO Diagnostic Discussion (estado del sistema de alerta)",
           ["https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml"],
           _txt(cpc.parse_enso_discussion), 31, 40, "official", "cpc-ensodisc.html", critical=True,
           docs="https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml"),
    Source("enfen-comunicados", "ENFEN", "Comunicados oficiales del ENFEN (listado)",
           ["https://enfen.imarpe.gob.pe/wp-json/wp/v2/posts?per_page=10&search=comunicado",
            "https://enfen.imarpe.gob.pe/comunicados/",
            # Réplica oficial de la DHN (Marina de Guerra, miembro del ENFEN).
            "https://www.dhn.mil.pe/portal/comunicados-oficiales-enfen"],
           _parse_enfen, 14, 30, "official", "enfen-comunicados.html", save=True,
           docs="https://enfen.imarpe.gob.pe/comunicados/"),
]

SOURCE_BY_ID = {s.id: s for s in SOURCES}


# ---------------------------------------------------------------------------
# Adquisición de una fuente con respaldo en la publicación anterior
# ---------------------------------------------------------------------------
@dataclass
class Acquired:
    source: Source
    data: Any = None
    ok: bool = False
    carried: bool = False  # dato reutilizado de una publicación anterior
    channel: str = ""
    url: str = ""
    retrieved_at: str = ""
    archived_at: Optional[str] = None
    sha256: str = ""
    fingerprint: str = ""
    previous_fingerprint: str = ""
    warnings: list = field(default_factory=list)
    error: str = ""
    attempts: list = field(default_factory=list)
    raw: bytes = b""
    documents: list = field(default_factory=list)  # otros archivos leídos (p. ej. el PDF del comunicado)


class PreviousPublication:
    """Lee los artefactos de la publicación anterior (en vivo o local)."""

    def __init__(self, base: Optional[str], fetcher=None):
        self.base = base.rstrip("/") if base else None
        self.fetcher = fetcher
        self._cache: dict[str, Any] = {}

    def get_text(self, name: str, tries: int = 1) -> Optional[str]:
        """Archivo de texto de la publicación anterior (p. ej. el histórico de noticias).

        Con ``tries`` > 1 se reintenta si el servidor falla o no responde (no si el archivo no existe)."""
        if not self.base:
            return None
        for attempt in range(max(1, tries)):
            if attempt:
                time.sleep(5 * attempt)
            try:
                if self.base.startswith("http"):
                    if self.fetcher is None:
                        return None
                    r = self.fetcher.client.get(f"{self.base}/{name}", params={"t": int(time.time())})
                    if r.status_code == 200:
                        return r.text
                    if r.status_code < 500:
                        return None
                    continue
                p = Path(self.base) / name
                return p.read_text(encoding="utf-8") if p.exists() else None
            except Exception:
                continue
        return None

    def get_bytes(self, name: str) -> Optional[bytes]:
        """Archivo binario de la publicación anterior (p. ej. una copia archivada)."""
        if not self.base:
            return None
        try:
            if self.base.startswith("http"):
                if self.fetcher is None:
                    return None
                r = self.fetcher.client.get(f"{self.base}/{name}")
                return r.content if r.status_code == 200 else None
            p = Path(self.base) / name
            return p.read_bytes() if p.exists() else None
        except Exception:
            return None

    def get(self, name: str) -> Optional[Any]:
        if not self.base:
            return None
        if name in self._cache:
            return self._cache[name]
        val = None
        try:
            if self.base.startswith("http"):
                if self.fetcher is None:
                    return None
                r = self.fetcher.client.get(f"{self.base}/{name}", params={"t": int(time.time())})
                if r.status_code == 200:
                    val = r.json()
            else:
                p = Path(self.base) / name
                if p.exists():
                    val = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            val = None
        self._cache[name] = val
        return val


def acquire(src: Source, fetcher, fixtures: Optional[Path], previous: PreviousPublication, log: EventLog) -> Acquired:
    from .fetch import FetchError, Response

    acq = Acquired(src)
    prev = previous.get(f"sources/{src.id}.json")
    if prev:
        acq.previous_fingerprint = prev.get("fingerprint", "")
    resp = None
    try:
        if fixtures is not None:
            resp = _fixture_response(src, fixtures)
        else:
            resp = fetcher.get(src.urls, archive=src.archive, save=src.save, accept=src.accept)
        acq.attempts = resp.attempts
        acq.raw = resp.body
        parsed = src.parse(resp)
        acq.data = parsed.data
        acq.ok = True
        acq.channel, acq.url = resp.channel, resp.url
        acq.retrieved_at, acq.archived_at, acq.sha256 = resp.retrieved_at, resp.archived_at, resp.sha256
        acq.fingerprint = parsed.fingerprint
        acq.warnings = parsed.warnings
        for w in parsed.warnings:
            log.add("warning", src.id, "validate", "implausible-value", w)
        if acq.previous_fingerprint and acq.previous_fingerprint != parsed.fingerprint:
            log.add("warning", src.id, "parse", "format-drift",
                    f"Se detectó un cambio en el formato de la fuente (huella {acq.previous_fingerprint} → {parsed.fingerprint}). "
                    "El parseo siguió siendo válido; revisar que los valores sean coherentes.")
        if resp.channel == "relay-peru":
            log.add("info", src.id, "fetch", "relay-channel",
                    f"Fuente oficial no accesible desde el servidor; se usó la copia recolectada desde el Perú el {resp.archived_at}.")
        elif resp.channel == "relay-n8n":
            log.add("info", src.id, "fetch", "relay-channel",
                    f"Fuente oficial no accesible desde el servidor; se usó la copia que bajó n8n el {resp.archived_at}.")
        if resp.channel.startswith("archive"):
            log.add("warning", src.id, "fetch", "archive-channel",
                    f"Fuente oficial no accesible; se usó la copia del Internet Archive del {resp.archived_at}.")
    except FetchError as exc:
        acq.error = str(exc)
        acq.attempts = exc.attempts
        log.add("error" if src.critical else "warning", src.id, "fetch", "unreachable",
                f"{exc}. Intentos: {json.dumps(exc.attempts, ensure_ascii=False)[:1600]}")
    except FormatChanged as exc:
        acq.error = str(exc)
        log.add("error", src.id, "parse", "format-changed",
                f"Se detectó un cambio en el formato de la fuente. El dato permanece en validación. Detalle: {exc}")
    except Exception as exc:  # defensa: un parser con error no debe tumbar la corrida
        acq.error = f"{type(exc).__name__}: {exc}"
        log.add("error", src.id, "parse", "exception", acq.error)

    if not acq.ok and prev and prev.get("data") is not None:
        acq.data = prev["data"]
        acq.carried = True
        acq.channel = "previous-publication"
        acq.retrieved_at = prev.get("retrievedAt", "")
        acq.fingerprint = prev.get("fingerprint", "")
        log.add("info", src.id, "fetch", "carried-forward",
                f"Se mantiene el último dato válido obtenido el {acq.retrieved_at}.")
    return acq


def _fixture_response(src: Source, fixtures: Path):
    """Respuesta capturada; si la captura directa falló, la copia de archivo más reciente."""
    from .fetch import FetchError, Response

    p = fixtures / src.fixture
    meta = _fixture_meta(fixtures, src.fixture)
    if p.exists() and meta.get("status") in (None, 200):
        return Response(src.urls[0], p.read_bytes(), "fixture", 200, retrieved_at=meta.get("captured_at") or "")
    stem = src.fixture.rsplit(".", 1)[0]
    hist = sorted((fixtures / "history").glob(f"{stem}-[0-9]*")) if (fixtures / "history").exists() else []
    if hist:
        ts = hist[-1].stem.rsplit("-", 1)[1]
        from .fetch import _ts_iso
        return Response(src.urls[0], hist[-1].read_bytes(), "archive", 200, archived_at=_ts_iso(ts),
                        retrieved_at=meta.get("captured_at") or "")
    raise FetchError(f"sin fixture {src.fixture}", [])


ENFEN_BASE = "https://enfen.imarpe.gob.pe"


def _clean_wpdm(url: str) -> str:
    """Quita el parámetro «refresh» (token por visita) de los enlaces de descarga."""
    import html as _html
    import re as _re

    return _re.sub(r"[&?]refresh=[^&]*", "", _html.unescape(url))


def _communique_urls(item: dict) -> list[str]:
    """URL donde puede estar el PDF de un comunicado: la del listado y su
    PDF directo en la réplica de la DHN. La DHN pide una verificación humana
    a algunos clientes (como GitHub Actions) y entonces responde HTML, que se
    descarta; si falla también el anterior, se intenta el comunicado previo."""
    n, y = item["number"], item["year"]
    urls = [_clean_wpdm(item["url"]), item["url"],
            f"{peru.DHN_BASE}/Archivos/oceanografia/enfen/comunicado-oficial/{n:02d}-{y}.pdf"]
    return list(dict.fromkeys(urls))


def _get_communique(fetcher, item: dict):
    """PDF de un comunicado: sus URL conocidas y, si ninguna sirve, cualquier
    copia en PDF que el Internet Archive tenga de su página de descarga en el
    portal del ENFEN."""
    from .fetch import FetchError, archive_prefix

    try:
        return fetcher.get(_communique_urls(item), archive=True, save=True, accept=("pdf", "octet-stream"))
    except FetchError as exc:
        page = f"{ENFEN_BASE}/download/comunicado-oficial-enfen-n-{item['number']:02d}-{item['year']}/"
        tried: list = []
        got = archive_prefix(fetcher, page, attempts=tried)
        if got is not None:
            got.attempts = exc.attempts + tried
            return got
        last = tried[-1] if tried else {}
        note = next((a["note"] for a in tried if a.get("channel") == "archive-prefix"),
                    f"consulta sin respuesta: {last.get('status') or last.get('error') or 'sin intento'}")
        raise FetchError(f"{exc} (archivo por prefijo: {note})", exc.attempts + tried) from exc


def enfen_latest(acq: Acquired, fetcher, fixtures: Optional[Path], previous: PreviousPublication,
                 log: EventLog, today: date) -> None:
    """Completa el listado ENFEN con el comunicado más reciente (PDF).

    1. Toma el número más alto entre el listado y la publicación anterior.
    2. Sondea los dos números siguientes por su página de descarga
       (``/download/comunicado-oficial-enfen-n-NN-AAAA/``): así un
       comunicado nuevo se detecta aunque el listado o su copia de archivo
       estén desactualizados.
    3. Descarga el PDF (directo, archivo o copia nueva del archivo) y lo
       parsea. Si el PDF ya fue leído en la corrida anterior, se reutiliza.
    """
    from .fetch import FetchError, Response

    data = acq.data if isinstance(acq.data, dict) else {}
    listing = list(data.get("listing") or [])
    prev_src = previous.get("sources/enfen-comunicados.json") or {}
    prev_latest = (prev_src.get("data") or {}).get("latest")
    if data.get("latest"):
        return
    known = [(i["year"], i["number"]) for i in listing if i.get("kind", "oficial") == "oficial"]
    if prev_latest:
        known.append((prev_latest["year"], prev_latest["number"]))
    if not known and fixtures is None:
        return

    if fixtures is None and known:
        y, n = max(known)
        probes = [(y, n + 1), (y, n + 2)]
        if today.month == 1 and y < today.year:
            probes.insert(0, (today.year, 1))
        for py, pn in probes:
            # Primero el PDF directo en la réplica de la DHN (rápido y sin archivo).
            dhn = f"{peru.DHN_BASE}/Archivos/oceanografia/enfen/comunicado-oficial/{pn:02d}-{py}.pdf"
            try:
                r = fetcher.get([dhn], archive=False, accept=("pdf", "octet-stream"))
                if r.body[:5] == b"%PDF-":
                    listing.insert(0, {"year": py, "number": pn, "kind": "oficial", "id": f"{pn:02d}-{py}", "url": dhn})
                    log.add("info", "enfen-comunicados", "fetch", "probe-found",
                            f"Se detectó el comunicado {pn:02d}-{py} en la réplica de la DHN antes de que apareciera en el listado.")
                    continue
            except FetchError:
                pass
            page = f"{ENFEN_BASE}/download/comunicado-oficial-enfen-n-{pn:02d}-{py}/"
            try:
                r = fetcher.get([page], archive=True, save=True, accept=("html",))
            except FetchError:
                continue
            got = peru.LISTING_RE.search(r.text) or re.search(r"href=[\"']([^\"']*\?wpdmdl=\d+[^\"']*)", r.text)
            url = got.group(1) if got else f"{page}?wpdmdl="
            if "wpdmdl=" in url and not url.endswith("="):
                listing.insert(0, {"year": py, "number": pn, "kind": "oficial", "id": f"{pn:02d}-{py}", "url": url})
                log.add("info", "enfen-comunicados", "fetch", "probe-found",
                        f"Se detectó el comunicado {pn:02d}-{py} antes de que apareciera en el listado.")
        listing.sort(key=lambda i: (i.get("kind", "oficial") == "oficial", i["year"], i["number"]), reverse=True)

    top = listing[0] if listing else None
    if prev_latest and (not top or (prev_latest["year"], prev_latest["number"]) >= (top["year"], top["number"])):
        data["latest"] = prev_latest
        data["listing"] = listing[:6]
        acq.data = data
        return

    if fixtures is not None:
        pdfs = sorted((fixtures / "history").glob("enfen-pdf-imarpe-*.txt"))
        pdfs = [p for p in pdfs if p.read_bytes()[:5] == b"%PDF-"]
        item = top or {"id": "", "year": 0, "number": 0, "url": ""}
        # El PDF capturado del comunicado más reciente del listado, si está.
        def _number(p: Path):
            m = peru.NUMBER_RE.search(peru.pdf_text(p.read_bytes())[:3000])
            return (int(m.group(2)), int(m.group(1))) if m else None

        chosen = next((p for p in reversed(pdfs) if item["id"] and _number(p) == (item["year"], item["number"])), None)
        chosen = chosen or (pdfs[-1] if pdfs else None)
        candidates = [(item, [Response(item["url"], chosen.read_bytes(), "archive", 200)])] if chosen else []
    else:
        # El más reciente y, si no se puede leer, los anteriores: un estado
        # anterior marcado como vencido es mejor que ninguno.
        oficial = [i for i in listing if i.get("kind", "oficial") == "oficial"][:3]
        candidates = [(i, None) for i in oficial]
    failures = []
    for item, canned in candidates:
        if prev_latest and (prev_latest["year"], prev_latest["number"]) >= (item["year"], item["number"]):
            data["latest"] = prev_latest
            break
        try:
            resp = canned[0] if canned else _get_communique(fetcher, item)
            acq.documents.append(resp.body)
            if resp.body[:5] != b"%PDF-":
                raise FormatChanged("enfen: la descarga no es un PDF")
            c = peru.parse_enfen_communique(peru.pdf_text(resp.body), source=_clean_wpdm(item["url"]))
        except FetchError as exc:
            failures.append(f"{item['id']}: {exc}")
            continue
        except FormatChanged as exc:
            failures.append(f"{item['id']}: {exc}")
            continue
        except Exception as exc:  # pypdf u otro error inesperado
            failures.append(f"{item['id']}: {type(exc).__name__}: {exc}")
            continue
        for w in c.warnings:
            log.add("warning", "enfen-comunicados", "parse", "communique-warning", w)
        c.data["channel"] = resp.channel
        c.data["archived_at"] = resp.archived_at
        c.data["archive"] = archive.source_path("enfen-comunicados", resp.body)
        data["latest"] = c.data
        if resp.channel.startswith("archive") and fixtures is None:
            log.add("warning", "enfen-comunicados", "fetch", "archive-channel",
                    f"El PDF del comunicado {item['id']} se obtuvo del Internet Archive ({resp.archived_at}).")
        break
    if failures:
        log.add("error", "enfen-comunicados", "fetch", "communique-unread",
                "No se pudo leer el PDF del comunicado " + "; ".join(failures)[:1500])
    if not data.get("latest") and prev_latest:
        data["latest"] = prev_latest
    data["listing"] = listing[:6]
    acq.data = data
    if not acq.ok and data.get("latest"):
        acq.ok = True


def _fixture_meta(fixtures: Path, name: str) -> dict:
    idx = fixtures / "index.json"
    if not idx.exists():
        return {}
    data = json.loads(idx.read_text(encoding="utf-8"))
    for e in data.get("entries", []):
        if e.get("name") == name:
            return {"status": e.get("status"), "captured_at": data.get("captured_at")}
    return {"captured_at": data.get("captured_at")}


# ---------------------------------------------------------------------------
# Derivados
# ---------------------------------------------------------------------------
def centered_mean3(points: list[dict]) -> list[dict]:
    """Media móvil de 3 meses centrada (metodología ICEN, ENFEN 01-2024)."""
    out = []
    for i in range(1, len(points) - 1):
        trio = points[i - 1: i + 2]
        if all(p["value"] is not None for p in trio) and _consecutive([p["period"] for p in trio]):
            out.append({"period": points[i]["period"], "value": round(sum(p["value"] for p in trio) / 3, 2)})
    return out


def _consecutive(periods: list[str]) -> bool:
    idx = [int(p[:4]) * 12 + int(p[5:7]) for p in periods]
    return all(b - a == 1 for a, b in zip(idx, idx[1:]))


def troup_soi(tahiti: list[dict], darwin: list[dict], base=(1951, 1992)) -> list[dict]:
    """SOI en escala Troup (BoM): 10 × (ΔP − media) / desv. estándar, por mes.

    ΔP = Tahití − Darwin (hPa). La climatología mensual usa 1951–1992,
    el periodo común más largo disponible en los archivos de NOAA/CPC
    (BoM usa 1933–1992; ver docs/metodologia.md y la validación contra
    valores archivados de BoM en las pruebas).
    """
    d = {p["period"]: p["value"] for p in darwin if p["value"] is not None}
    diff = [(p["period"], p["value"] - d[p["period"]]) for p in tahiti if p["value"] is not None and p["period"] in d]
    by_month: dict[int, list[float]] = {}
    for per, v in diff:
        if base[0] <= int(per[:4]) <= base[1]:
            by_month.setdefault(int(per[5:7]), []).append(v)
    stats = {}
    for m, vals in by_month.items():
        mu = sum(vals) / len(vals)
        sd = (sum((x - mu) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5
        stats[m] = (mu, sd)
    out = []
    for per, v in diff:
        mu, sd = stats.get(int(per[5:7]), (None, None))
        if mu is None or not sd:
            continue
        out.append({"period": per, "value": round(10 * (v - mu) / sd, 1)})
    return out


def month_age(period: str, today: date) -> int:
    """Días desde el último día del periodo mensual (o desde la fecha exacta)."""
    if len(period) >= 10:
        d = date.fromisoformat(period[:10])
    else:
        y, m = int(period[:4]), int(period[5:7])
        d = date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1)
    return (today - d).days


def last_valid(points: list[dict]) -> Optional[dict]:
    for p in reversed(points or []):
        if p.get("value") is not None:
            return p
    return None


# ---------------------------------------------------------------------------
# Construcción de la publicación
# ---------------------------------------------------------------------------
class Builder:
    def __init__(self, acquired: dict[str, Acquired], log: EventLog, today: date):
        self.a = acquired
        self.log = log
        self.today = today
        self.series: dict[str, dict] = {}

    def data(self, sid: str):
        a = self.a.get(sid)
        return a.data if a and a.data is not None else None

    def add_series(self, key: str, points: list[dict], *, label: str, units: str, scope: str, source: str,
                   frequency: str, slo_days: int, description: str, climatology: str = "",
                   period_kind: str = "month", category: Optional[Callable] = None, history_from: str = "1950-01"):
        pts = [{"period": p["period"], "value": p["value"]} for p in points if p["period"] >= history_from]
        if not pts:
            self.log.add("warning", source, "derive", "empty-series", f"Serie {key} sin datos")
            return
        lv = last_valid(pts)
        age = month_age(lv["period"], self.today) if lv else None
        acq = self.a.get(source)
        stale = age is None or age > slo_days
        latest = {
            "period": lv["period"] if lv else None, "value": lv["value"] if lv else None,
            "ageDays": age, "stale": stale, "carried": bool(acq and acq.carried),
        }
        prev = None
        if lv:
            i = pts.index(lv)
            prev = next((p for p in reversed(pts[:i]) if p["value"] is not None), None)
        if prev:
            latest["previous"] = {"period": prev["period"], "value": prev["value"],
                                  "change": round(lv["value"] - prev["value"], 2)}
        if category and lv:
            latest["category"] = category(lv["value"])
        if stale and lv:
            self.log.add("warning", source, "validate", f"stale-{key}",
                         f"El último dato de {label} corresponde a {lv['period']} ({age} días); supera el umbral de {slo_days} días.")
        self.series[key] = {
            "id": key, "label": label, "units": units, "scope": scope, "source": source,
            "frequency": frequency, "periodKind": period_kind, "sloDays": slo_days,
            "description": description, "climatology": climatology, "latest": latest, "points": pts,
        }

    def build_series(self) -> None:
        # ERSSTv6 (NOAA dejó de actualizar ERSSTv5 en 2026). PSL publica la
        # anomalía con base 1981–2010; se lleva a 1991–2020 restando la media
        # de cada mes en ese periodo. No se usa para estimar el ICEN: frente
        # al ICEN oficial difiere hasta 0,7 °C (ver docs/metodologia.md).
        for sid, key, label, region in (
            ("psl-ersst6-nino12", "nino12", "Niño 1+2", "Niño 1+2 (0°–10°S, 90°–80°O), frente a Ecuador y el norte del Perú"),
            ("psl-ersst6-nino34", "nino34", "Niño 3.4", "Niño 3.4 (5°N–5°S, 170°–120°O), Pacífico central"),
        ):
            pts = self.data(sid)
            if not pts:
                continue
            try:
                pts = cpc.rebase_anomalies(pts, (1991, 2020))
            except FormatChanged as exc:
                self.log.add("error", sid, "derive", "rebase-failed", str(exc))
                continue
            self.add_series(key, pts, label=f"{label} (ERSSTv6)", units="degC", scope="coastal" if key == "nino12" else "basin",
                            source=sid, frequency="mensual", slo_days=50, climatology="1991–2020",
                            category=lambda v: {"tone": sig.anomaly_tone(v)},
                            description=f"Anomalía mensual de TSM en la región {region}. NOAA ERSSTv6, llevada a la base 1991–2020.")
        oi = self.data("cpc-sstoi")
        if oi:
            meta = dict(units="degC", source="cpc-sstoi", frequency="mensual", slo_days=50, climatology="1991–2020",
                        category=lambda v: {"tone": sig.anomaly_tone(v)}, history_from="1982-01")
            self.add_series("nino12_oisst", oi["anom"]["nino12"], label="Niño 1+2 (OISST)", scope="coastal",
                            description="Anomalía mensual de TSM Niño 1+2 del análisis OISST v2.1. Disponible antes que ERSST.", **meta)
            self.add_series("nino34_oisst", oi["anom"]["nino34"], label="Niño 3.4 (OISST)", scope="basin",
                            description="Anomalía mensual de TSM Niño 3.4 del análisis OISST v2.1. Disponible antes que ERSST.", **meta)
            self.add_series("nino3_oisst", oi["anom"]["nino3"], label="Niño 3 (OISST)", scope="basin",
                            description="Anomalía mensual de TSM en la región Niño 3 (5°N–5°S, 150°–90°O), OISST v2.1.", **meta)
            self.add_series("nino4_oisst", oi["anom"]["nino4"], label="Niño 4 (OISST)", scope="basin",
                            description="Anomalía mensual de TSM en la región Niño 4 (5°N–5°S, 160°E–150°O), OISST v2.1.", **meta)
        icen = self.data("igp-icen")
        if icen:
            self.add_series("icen", icen, label="ICEN oficial", units="degC", scope="coastal", source="igp-icen",
                            frequency="mensual", slo_days=110, climatology="1991–2020", category=sig.icen_category,
                            description="Índice Costero El Niño oficial publicado por ENFEN (archivo del IGP). Media de 3 meses centrada de la anomalía de TSM Niño 1+2, según la Nota Técnica ENFEN 01-2024.")
        for sid, key, label, desc in (
            ("cpc-roni", "roni", "RONI", "Índice Oceánico Relativo de El Niño de NOAA/CPC: anomalía de Niño 3.4 menos la anomalía media tropical (20°N–20°S), reescalada. Trimestres móviles (ERSSTv6, base 1991–2020). Es el índice oficial de NOAA desde febrero de 2026."),
            ("cpc-oni", "oni", "ONI", "Índice Oceánico de El Niño tradicional de NOAA/CPC: media de 3 meses de la anomalía Niño 3.4 (ERSST, bases de 30 años actualizadas cada 5 años)."),
        ):
            d = self.data(sid)
            if d:
                self.add_series(key, d, label=label, units="degC", scope="basin", source=sid, frequency="trimestral móvil",
                                slo_days=80, climatology="1991–2020", period_kind="season", category=sig.oni_category,
                                description=desc)
        soi = self.data("cpc-soi")
        if soi:
            pts = soi.get("standardized") or soi.get("anomaly") or []
            self.add_series("soi", pts, label="SOI (NOAA)", units="dimensionless", scope="basin", source="cpc-soi",
                            frequency="mensual", slo_days=50, climatology="1981–2010",
                            category=lambda v: {"tone": "warm" if v <= -1 else "cool" if v >= 1 else "neutral"},
                            description="Índice de Oscilación del Sur de NOAA/CPC: diferencia estandarizada de presión Tahití − Darwin. Valores negativos sostenidos acompañan a El Niño.")
        t, dw = self.data("cpc-tahiti"), self.data("cpc-darwin")
        if t and dw:
            tp = t.get("original") or t.get("data") or next(iter(t.values()))
            dp = dw.get("original") or dw.get("data") or next(iter(dw.values()))
            troup = troup_soi(tp, dp)
            src = "cpc-tahiti"
            if troup:
                self.add_series("soi_troup", troup, label="SOI escala Troup", units="dimensionless", scope="basin", source=src,
                                frequency="mensual", slo_days=50, climatology="1951–1992",
                                category=lambda v: {"tone": "warm" if v <= -7 else "cool" if v >= 7 else "neutral"},
                                description="SOI en la escala de Troup usada por la Oficina de Meteorología de Australia (×10; umbrales ±7), calculado por el observatorio con las presiones de Tahití y Darwin de NOAA/CPC.")
        for sid, key, label, region in (("cpc-wpac850", "wpac850", "Alisios Pacífico occidental", "135°E–180°"),
                                        ("cpc-cpac850", "cpac850", "Alisios Pacífico central", "175°O–140°O"),
                                        ("cpc-epac850", "epac850", "Alisios Pacífico oriental", "135°O–120°O")):
            d = self.data(sid)
            if not d:
                continue
            if d.get("anomaly"):
                self.add_series(f"{key}_anom", d["anomaly"], label=f"{label} (anomalía)", units="m_per_s", scope="basin",
                                source=sid, frequency="mensual", slo_days=50, climatology="1991–2020", history_from="1979-01",
                                category=lambda v: {"tone": "warm" if v <= -1 else "cool" if v >= 1 else "neutral"},
                                description=f"Anomalía del índice de vientos alisios a 850 hPa ({region}, 5°N–5°S). Negativa = alisios más débiles o vientos del oeste (favorece El Niño); positiva = alisios más fuertes.")
            if d.get("original"):
                self.add_series(key, d["original"], label=label, units="m_per_s", scope="basin", source=sid,
                                frequency="mensual", slo_days=50, history_from="1979-01",
                                description=f"Índice de vientos alisios a 850 hPa ({region}, 5°N–5°S) de NOAA/CPC, en m/s con signo invertido: positivo = viento del este (alisios normales); negativo = flujo de oeste a este.")

        heat = self.data("cpc-heat")
        if heat:
            for key, region, scope in (("heat_160e80w", "160°E–80°O", "basin"), ("heat_180w100w", "180°–100°O", "basin"),
                                       ("heat_130e80w", "130°E–80°O", "basin")):
                if heat.get(key):
                    self.add_series(key, heat[key], label=f"Contenido de calor 0–300 m ({region})", units="degC", scope=scope,
                                    source="cpc-heat", frequency="mensual", slo_days=50, climatology="1981–2010",
                                    history_from="1979-01", category=lambda v: {"tone": sig.anomaly_tone(v)},
                                    description=f"Anomalía de la temperatura media de los 300 m superiores del océano en el Pacífico ecuatorial ({region}, GODAS). Valores positivos indican una termoclina más profunda y calor acumulado bajo la superficie, que suele anticipar el calentamiento superficial.")

    def events(self) -> list[dict]:
        s = self.series.get("icen")
        return sig.icen_events(s["points"]) if s else []

    def weekly(self) -> Optional[dict]:
        w = self.data("cpc-wksst")
        if not w:
            return None
        out = {}
        for region, pts in w.items():
            if not pts:
                continue
            last = pts[-1]
            out[region] = {
                "latest": {"date": last["date"], "anom": last["anom"], "sst": last["sst"],
                           "ageDays": (self.today - date.fromisoformat(last["date"])).days},
                "points": [{"date": p["date"], "value": p["anom"], "sst": p["sst"]} for p in pts if p["date"] >= "1990-01-01"],
            }
            lastage = out[region]["latest"]["ageDays"]
            if lastage > 16:
                self.log.add("warning", "cpc-wksst", "validate", "stale-weekly",
                             f"Último dato semanal {region} del {last['date']} ({lastage} días).")
        return out

    def official(self) -> dict:
        noaa = self.data("cpc-ensodisc")
        res: dict[str, Any] = {}
        if noaa:
            a = self.a["cpc-ensodisc"]
            stale = bool(noaa.get("next_issue") and date.fromisoformat(noaa["next_issue"]) + timedelta(days=3) < self.today)
            code = (noaa.get("codes") or ["unknown"])[0]
            level = "alert" if "advisory" in code and "final" not in code else "watch" if "watch" in code else "ok"
            res["noaa"] = {
                "institution": "NOAA / CPC", "status": noaa["status"], "statusEs": noaa_status_es(noaa["status"]),
                "codes": noaa.get("codes"), "level": level, "issued": noaa.get("issued"),
                "nextIssue": noaa.get("next_issue") or second_thursday_after(noaa.get("issued"), self.today),
                "nextIssueEstimated": not noaa.get("next_issue"),
                "synopsis": noaa.get("synopsis"), "valuesInText": noaa.get("weekly_values_in_text"),
                "url": SOURCE_BY_ID["cpc-ensodisc"].urls[0], "channel": a.channel, "carried": a.carried,
                "retrievedAt": a.retrieved_at, "stale": stale,
            }
            if stale:
                self.log.add("warning", "cpc-ensodisc", "validate", "official-overdue",
                             f"La próxima discusión de NOAA estaba prevista para {noaa.get('next_issue')} y no se ha capturado.")
        enfen = self.data("enfen-comunicados")
        a = self.a.get("enfen-comunicados")
        if enfen:
            latest = enfen.get("latest")
            listing = enfen.get("listing") or []
            res["enfen"] = {
                "institution": "ENFEN", "listing": listing[:6], "channel": a.channel if a else "",
                "carried": bool(a and a.carried), "retrievedAt": a.retrieved_at if a else "",
                "url": "https://enfen.imarpe.gob.pe/comunicados/",
            }
            if latest:
                level = latest.get("level", "na")
                stale = bool(latest.get("next_issue") and date.fromisoformat(latest["next_issue"]) + timedelta(days=4) < self.today)
                res["enfen"].update({
                    "status": latest["status"], "statusCode": latest["status_code"], "level": level,
                    "number": latest["id"], "issued": latest.get("issued"), "nextIssue": latest.get("next_issue"),
                    "summary": latest.get("summary"), "documentUrl": latest.get("source") or (listing[0]["url"] if listing else ""),
                    "archive": latest.get("archive"), "stale": stale,
                })
                if (listing and listing[0].get("kind", "oficial") == "oficial"
                        and (listing[0]["year"], listing[0]["number"]) > (latest["year"], latest["number"])):
                    # Un comunicado más reciente existe pero no se pudo leer: el estado
                    # anterior ya no es vigente y no debe mostrarse como actual.
                    res["enfen"]["newerListed"] = listing[0]["id"]
                    res["enfen"]["stale"] = stale = True
                    self.log.add("warning", "enfen-comunicados", "parse", "newer-communique-unparsed",
                                 f"El listado muestra el comunicado {listing[0]['id']} pero solo se pudo leer el {latest['id']}.")
                if stale:
                    self.log.add("warning", "enfen-comunicados", "validate", "official-overdue",
                                 f"El siguiente comunicado ENFEN estaba previsto para {latest.get('next_issue')} y no se ha capturado.")
        if "enfen" not in res or "status" not in res.get("enfen", {}):
            self.log.add("error", "enfen-comunicados", "derive", "status-unknown",
                         "No se pudo determinar el estado del sistema de alerta de ENFEN en esta corrida.")
        return res

    def grd(self) -> dict:
        def pick(key, stale_days=None):
            s = self.series.get(key)
            if not s or s["latest"]["value"] is None:
                return {}
            return {"value": s["latest"]["value"], "period": s["latest"]["period"], "source": s["source"],
                    "stale": s["latest"]["stale"]}
        coastal = pick("nino12_oisst") or pick("nino12")
        basin = pick("nino34_oisst") or pick("nino34")
        inputs = {
            "coastal_sst": coastal, "basin_sst": basin,
            "wind_coastal": pick("epac850"), "wind_global": pick("cpac850"),
            "d20_coastal": pick("d20_coastal"), "d20_global": pick("d20_global"),
            "soi_troup": pick("soi_troup"),
        }
        return sig.grd_signals(inputs)


NOAA_ES = {
    "El Niño Advisory": "Advertencia de El Niño",
    "La Niña Advisory": "Advertencia de La Niña",
    "El Niño Watch": "Vigilancia de El Niño",
    "La Niña Watch": "Vigilancia de La Niña",
    "Final El Niño Advisory": "Advertencia final de El Niño",
    "Final La Niña Advisory": "Advertencia final de La Niña",
    "Not Active": "No activo",
}


def noaa_status_es(status: str) -> str:
    return " / ".join(NOAA_ES.get(s.strip(), s.strip()) for s in status.split("/"))


def second_thursday_after(issued: Optional[str], today: date) -> Optional[str]:
    """Estimación de respaldo: NOAA publica el segundo jueves de cada mes."""
    ref = date.fromisoformat(issued) if issued else today
    y, m = ref.year, ref.month
    for _ in range(3):
        first = date(y, m, 1)
        thursday = first + timedelta(days=(3 - first.weekday()) % 7 + 7)
        if thursday > ref:
            return thursday.isoformat()
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------
def csv_safe(v: Any) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not _is_number(s) else s


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def write_publication(out: Path, acquired: dict[str, Acquired], b: Builder, official: dict, weekly, grd: dict,
                      log: EventLog, started: datetime, news: Optional[dict] = None,
                      feed: Optional[dict] = None, previous: Optional["PreviousPublication"] = None) -> dict:
    now = datetime.now(timezone.utc)
    content_hash = hashlib.sha256(json.dumps(
        {k: v["points"][-24:] for k, v in sorted(b.series.items())} | {"official": official}, sort_keys=True, default=str
    ).encode()).hexdigest()
    pub_id = f"{now:%Y%m%dT%H%MZ}-{content_hash[:8]}"
    git_sha = os.environ.get("GITHUB_SHA") or _git_sha()
    common = {"schema": SCHEMA, "publicationId": pub_id, "generatedAt": now.isoformat(timespec="seconds")}

    tmp = Path(tempfile.mkdtemp(prefix="enso-pub-", dir=out.parent if out.parent.exists() else None))
    (tmp / "sources").mkdir()
    (tmp / "csv").mkdir()

    def dump(name: str, obj: dict) -> None:
        (tmp / name).write_text(json.dumps(common | obj, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")

    # Copias archivadas servidas por el propio sitio (enlace «copia archivada»)
    aw = archive.Writer(tmp)
    prev_bytes = previous.get_bytes if previous is not None else None
    arch = archive.write_sources(aw, acquired, prev_bytes,
                                 (lambda sid: previous.get(f"sources/{sid}.json")) if previous is not None else None)
    if official.get("enfen", {}).get("archive"):
        official["enfen"]["archive"] = archive.carry(aw, official["enfen"]["archive"], prev_bytes,
                                                     source="enfen-comunicados", document=True)
    if official.get("noaa") is not None:
        official["noaa"]["archive"] = (arch.get("cpc-ensodisc") or {}).get("file")
    if feed is not None:
        for g in feed.get("groups", []):
            for it in g["items"]:
                if g["id"] == "alertas":
                    continue  # ya enlazan a la página del archivo de noticias
                it["archive"] = (official.get("enfen", {}).get("archive") if it.get("id") == "enfen"
                                 else (arch.get(it.get("source") or "") or {}).get("file"))

    # Por fuente (base para el arrastre en la siguiente corrida)
    health = []
    for sid, a in acquired.items():
        s = a.source
        dump(f"sources/{sid}.json", {
            "id": sid, "ok": a.ok, "carried": a.carried, "channel": a.channel, "url": a.url,
            "retrievedAt": a.retrieved_at, "archivedAt": a.archived_at, "sha256": a.sha256,
            "fingerprint": a.fingerprint, "archive": arch.get(sid), "data": a.data,
        })
        health.append({
            "id": sid, "institution": s.institution, "product": s.product, "layer": s.layer,
            "url": s.urls[0], "docs": s.docs or s.urls[0], "cadenceDays": s.cadence_days, "sloDays": s.slo_days,
            "status": "ok" if a.ok and not a.channel.startswith("archive") else "archive" if a.ok else "carried" if a.carried else "failed",
            "channel": a.channel, "retrievedAt": a.retrieved_at, "archivedAt": a.archived_at,
            "fingerprint": a.fingerprint, "formatDrift": bool(a.ok and a.previous_fingerprint and a.previous_fingerprint != a.fingerprint),
            "error": a.error, "warnings": a.warnings[:5], "attempts": a.attempts[-12:],
            "archive": (arch.get(sid) or {}).get("file"), "archiveRetrievedAt": (arch.get(sid) or {}).get("retrievedAt"),
        })

    series_light = {k: {kk: vv for kk, vv in v.items() if kk != "points"} for k, v in b.series.items()}
    spark = {k: [[p["period"], p["value"]] for p in v["points"][-36:]] for k, v in b.series.items()}
    weekly_light = None
    if weekly:
        weekly_light = {r: {"latest": w["latest"], "recent": [[p["date"], p["value"]] for p in w["points"][-26:]]}
                        for r, w in weekly.items()}
    ok = sum(1 for h in health if h["status"] == "ok")
    events = [e.as_dict() for e in log.events]
    dashboard = {
        "official": official, "events": b.events(), "series": series_light, "spark": spark, "weekly": weekly_light, "grd": grd,
        "sources": {h["id"]: {"institution": h["institution"], "product": h["product"], "live": h["docs"],
                              "archive": h["archive"], "retrievedAt": h["archiveRetrievedAt"]} for h in health},
        "health": {"sourcesOk": ok, "sourcesTotal": len(health),
                   "degraded": [h["id"] for h in health if h["status"] != "ok"], "worst": log.worst()},
        "pipeline": {"version": PIPELINE_VERSION, "gitSha": git_sha, "startedAt": started.isoformat(timespec="seconds")},
    }
    if news is not None:
        from .news import FEED_BY_ID
        snapshots = archive.write_feeds(aw, news.get("raw") or {}, FEED_BY_ID, now.isoformat(timespec="seconds"))
        archive.write_news_days(aw, news.get("items") or [], FEED_BY_ID, snapshots, set(news.get("live") or {}),
                                now.date())
        for c in news["clusters"]["clusters"]:
            for link in c["links"]:
                fid = (news.get("live") or {}).get(link.get("id"))
                if fid in snapshots:
                    link["snapshot"] = snapshots[fid]
        for g in (feed or {}).get("groups", []):
            for it in g["items"] if g["id"] == "alertas" else []:
                fid = (news.get("live") or {}).get(it["id"].removeprefix("alert-"))
                if fid in snapshots:
                    it["snapshot"] = snapshots[fid]  # la respuesta de la fuente tal como se bajó hoy
    if feed is not None:
        dump("feed.json", feed)
        (tmp / "news").mkdir()
        dump("news/feeds.json", news["feeds"])
        dump("news/clusters.json", news["clusters"])
        (tmp / "news" / "items.jsonl").write_text(news["jsonl"], encoding="utf-8")
        (tmp / "news" / "items.csv").write_text(news["csv"], encoding="utf-8")
        dashboard["news"] = {"clusters": len(news["clusters"]["clusters"]), "items": news["feeds"]["history"]["items"],
                             "feedsActive": sum(1 for f in news["feeds"]["feeds"] if f["active"]),
                             "feedsTotal": len(news["feeds"]["feeds"])}
    dump("dashboard.json", dashboard)
    (tmp / archive.ROOT).mkdir(exist_ok=True)
    dump(f"{archive.ROOT}/index.json", aw.index(now.isoformat(timespec="seconds")))
    dump("series.json", {"series": b.series})
    if weekly:
        dump("weekly.json", {"source": "cpc-wksst", "regions": weekly})
    dump("sources.json", {"sources": health})
    dump("run-report.json", {"events": events, "worst": log.worst(),
                             "counts": {s: sum(1 for e in events if e["severity"] == s) for s in ("info", "warning", "error", "critical")}})
    dump("health.json", {"pipelineStatus": "degraded" if log.worst() in ("error", "critical") else "ok",
                         "sourcesOk": ok, "sourcesTotal": len(health), "lastSuccessfulRun": now.isoformat(timespec="seconds"),
                         "sources": [{k: h[k] for k in ("id", "status", "retrievedAt", "channel")} for h in health]})

    # CSV por serie y combinado
    for k, v in b.series.items():
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["periodo", "valor", "unidad", "serie", "fuente", "publicacion"])
        for p in v["points"]:
            w.writerow([p["period"], csv_safe(p["value"]), v["units"], k, v["source"], pub_id])
        (tmp / "csv" / f"{k}.csv").write_text(buf.getvalue(), encoding="utf-8")
    if weekly:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        regions = list(weekly)
        w.writerow(["semana_centrada"] + [f"{r}_anom" for r in regions] + [f"{r}_tsm" for r in regions])
        dates = sorted({p["date"] for r in regions for p in weekly[r]["points"]})
        idx = {r: {p["date"]: p for p in weekly[r]["points"]} for r in regions}
        for d in dates:
            w.writerow([d] + [idx[r].get(d, {}).get("value", "") for r in regions] + [idx[r].get(d, {}).get("sst", "") for r in regions])
        (tmp / "csv" / "semanal-regiones-nino.csv").write_text(buf.getvalue(), encoding="utf-8")
    periods = sorted({p["period"] for v in b.series.values() for p in v["points"] if v["periodKind"] != "date"})
    idx = {k: {p["period"]: p["value"] for p in v["points"]} for k, v in b.series.items()}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    keys = sorted(b.series)
    w.writerow(["periodo"] + keys)
    for per in periods:
        w.writerow([per] + [csv_safe(idx[k].get(per)) for k in keys])
    (tmp / "csv" / "todas-las-series.csv").write_text(buf.getvalue(), encoding="utf-8")

    # Las copias archivadas se listan en archive/index.json, no en el manifiesto.
    files = sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*")
                   if p.is_file() and not _third_party(p.relative_to(tmp)))
    dump("manifest.json", {"pipelineVersion": PIPELINE_VERSION, "gitSha": git_sha, "files": files + ["manifest.json"],
                           "series": sorted(b.series), "contentHash": content_hash})
    validate_publication(tmp, pub_id)

    # Reemplazo atómico del directorio publicado
    out.parent.mkdir(parents=True, exist_ok=True)
    old = out.with_name(out.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    if out.exists():
        out.rename(old)
    tmp.rename(out)
    if old.exists():
        shutil.rmtree(old)
    return {"publicationId": pub_id, "files": len(files) + 1}


def _third_party(rel: Path) -> bool:
    """Copias de terceros dentro de ``archive/`` (todo salvo su índice)."""
    return rel.parts[0] == archive.ROOT and rel.as_posix() != f"{archive.ROOT}/index.json"


def validate_publication(d: Path, pub_id: str) -> None:
    """Coherencia: todos los JSON comparten publicationId; series sin duplicados."""
    for p in d.rglob("*.json"):
        if p.name == "manifest.json" or _third_party(p.relative_to(d)):
            continue
        obj = json.loads(p.read_text(encoding="utf-8"))
        if obj.get("publicationId") != pub_id:
            raise RuntimeError(f"publicationId incoherente en {p.name}")
    series = json.loads((d / "series.json").read_text(encoding="utf-8"))["series"]
    for k, s in series.items():
        per = [p["period"] for p in s["points"]]
        if len(per) != len(set(per)) or per != sorted(per):
            raise RuntimeError(f"serie {k}: periodos duplicados o desordenados")
    dash = json.loads((d / "dashboard.json").read_text(encoding="utf-8"))
    for k in ("official", "series", "grd"):
        if k not in dash:
            raise RuntimeError(f"dashboard.json sin «{k}»")


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def archive_raw(raw_dir: Path, acquired: dict[str, "Acquired"], today: date) -> int:
    """Guarda cada respuesta original nueva (por sha256) para backtesting futuro."""
    n = 0
    for sid, a in acquired.items():
        if a.channel in ("fixture", "previous-publication"):
            continue
        d = raw_dir / sid
        for body in ([a.raw] if a.raw else []) + list(a.documents):
            sha = hashlib.sha256(body).hexdigest()[:12]
            d.mkdir(parents=True, exist_ok=True)
            if any(p.stem.endswith(f"-{sha}") for p in d.iterdir()):
                continue
            ext = ".pdf" if body[:5] == b"%PDF-" else ".html" if b"<html" in body[:2000].lower() else ".txt"
            (d / f"{today.isoformat()}-{sha}{ext}").write_bytes(body)
            n += 1
    return n


def run(out: Path, previous: Optional[str], fixtures: Optional[Path] = None, offline: bool = False,
        today: Optional[date] = None, only: Optional[list[str]] = None, raw_dir: Optional[Path] = None,
        relay_dir: Optional[Path] = None, n8n_dir: Optional[Path] = None,
        plan: Optional[dict[str, list[str]]] = None, history_dir: Optional[Path] = None,
        reader: Optional[set[str]] = None) -> dict:
    """``plan``: canales de cada URL según el registro (``registry.url_channels``); la línea de comandos
    lo lee de ``registry/sources.json`` para no insistir con lo que solo responde desde el Perú.
    ``reader``: feeds que robots.txt no permite y se leen como un lector de feeds (``registry.reader_urls``)."""
    from .fetch import Fetcher

    started = datetime.now(timezone.utc)
    log = EventLog()
    relay = load_relay(relay_dir, log, plan) if relay_dir is not None and fixtures is None else None
    n8n = load_n8n_relay(n8n_dir, log) if n8n_dir is not None and fixtures is None else None
    fetcher = Fetcher(offline=offline, allow_save=os.environ.get("ENSO_ARCHIVE_SAVE") == "1", relay=[relay, n8n],
                      plan=plan if fixtures is None else None)
    prev = PreviousPublication(previous, fetcher)
    acquired: dict[str, Acquired] = {}
    for src in SOURCES:
        if only and src.id not in only:
            continue
        acquired[src.id] = acquire(src, fetcher, fixtures, prev, log)
    if today is None:
        today = (started.date() if fixtures is None else _fixture_date(fixtures)) or started.date()
    if "enfen-comunicados" in acquired:
        enfen_latest(acquired["enfen-comunicados"], fetcher, fixtures, prev, log, today)
    b = Builder(acquired, log, today)
    b.build_series()
    weekly = b.weekly()
    official = b.official()
    grd = b.grd()
    news = None
    if not offline and not only:
        try:
            news = acquire_news(fetcher, fixtures, prev, log, started if fixtures is None else
                                datetime.combine(today, datetime.min.time(), timezone.utc), raw_dir, history_dir,
                                reader if fixtures is None else None)
        except Exception as exc:  # las noticias nunca deben detener la publicación
            log.add("warning", "news", "parse", "exception", f"{type(exc).__name__}: {exc}")
    from . import sourcefeed
    meta = {s.id: {"institution": s.institution, "docs": s.docs or s.urls[0],
                   "retrievedAt": acquired[s.id].retrieved_at if s.id in acquired else None,
                   "channel": acquired[s.id].channel if s.id in acquired else None} for s in SOURCES}
    feed = sourcefeed.build(official, b.series, weekly, meta, relay, news_items=(news or {}).get("items"),
                            now=started if fixtures is None else datetime.combine(today, datetime.min.time(), timezone.utc),
                            feed_status=((news or {}).get("feeds") or {}).get("feeds"))
    for s in SOURCES:
        a = acquired.get(s.id)
        if a and not a.ok and not a.carried:
            log.add("critical" if s.critical else "error", s.id, "publish", "no-data",
                    "La fuente falló y no hay un dato anterior que conservar.")
    res = write_publication(out, acquired, b, official, weekly, grd, log, started, news=news, feed=feed, previous=prev)
    if raw_dir is not None:
        res["rawArchived"] = archive_raw(raw_dir, acquired, today)
    fetcher.close()
    res.update({"worst": log.worst(), "events": len(log.events)})
    return res


RELAY_STALE_HOURS = 36
RELAY_TOKEN_WARN_DAYS = 21
#: Tiempo máximo para empezar a pedir feeds de noticias (el build entero tiene 30 min).
NEWS_DEADLINE_S = 600


def _hours_since(iso: Optional[str], now: datetime) -> float:
    """Horas desde una fecha ISO con zona horaria (infinito si falta o no se entiende)."""
    try:
        return (now - datetime.fromisoformat(str(iso))).total_seconds() / 3600
    except (TypeError, ValueError):
        return float("inf")


def read_history_backup(history_dir: Optional[Path]) -> str:
    """El histórico de noticias según la rama ``data-archive``: primero la copia completa de la última
    corrida archivada (``items.jsonl``), luego las notas de cada día (``<día>.jsonl``) que no estén en ella."""
    if history_dir is None or not history_dir.is_dir():
        return ""
    seen, lines = set(), []
    files = sorted(history_dir.glob("*.jsonl"), key=lambda p: (p.name != "items.jsonl", p.name))
    for p in files:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get("id") and item["id"] not in seen:
                seen.add(item["id"])
                lines.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    return "".join(lines)


def acquire_news(fetcher, fixtures: Optional[Path], previous: PreviousPublication, log: EventLog,
                 now: datetime, raw_dir: Optional[Path], history_dir: Optional[Path] = None,
                 reader: Optional[set[str]] = None) -> Optional[dict]:
    """Feeds de noticias → histórico de solo anexar, CSV, estado de feeds y grupos.

    ``reader``: URL de feeds que robots.txt no permite y se leen como un lector de feeds
    (``registry.reader_urls``): como mucho una vez cada ``registry.READER_MIN_HOURS``."""
    from . import news as N
    from .fetch import FetchError
    from .geo import department_names

    by_url = {f.url: f for f in N.FEEDS}
    if fixtures is not None and not any(fixtures.glob("news-*.*")):
        return None
    if fixtures is not None:
        def fetch(url):
            p = fixtures / by_url[url].fixture
            return (200, p.read_bytes(), "", "") if p.exists() else (None, b"", "", "sin captura")
    else:
        # Cliente propio para los feeds: menos espera y menos reintentos que para las
        # fuentes oficiales (son ~180 y un medio caído no debe retrasar la publicación).
        from .fetch import Fetcher
        import httpx
        # Todas las copias (Perú y n8n), no solo la primera: gana la más reciente de la URL.
        news_fetcher = Fetcher(timeout=20.0, retries=2, polite_delay=1.0, relay=list(getattr(fetcher, "relays", [])),
                               plan=getattr(fetcher, "plan", None))

        def fetch(url):
            try:
                r = news_fetcher.get([url], archive=False)
                return 200, r.body, r.content_type, "", {"channel": r.channel, "copyAt": r.archived_at or None}
            except FetchError as exc:
                last = exc.attempts[-1] if exc.attempts else {}
                return last.get("status"), b"", "", last.get("error") or f"HTTP {last.get('status')}"
            except httpx.HTTPError as exc:  # redirecciones infinitas, gzip roto, URL inválida…
                return None, b"", "", f"{type(exc).__name__}: {exc}"[:200]

    # Feeds cuyo robots.txt no permite pedirlos (el registro los deja sin canales): no se piden y
    # quedan en el estado como omitidos, no como caídos.
    plan = getattr(fetcher, "plan", None) or {}
    barred = {f.id for f in N.FEEDS if plan.get(f.url) == []}
    # Los que se leen como un lector de feeds y tuvieron una lectura buena hace menos de READER_MIN_HOURS
    # no se vuelven a pedir: queda el estado de esa lectura (sus notas ya están en el histórico).
    from .registry import READER_MIN_HOURS

    prev_feeds = previous.get("news/feeds.json") or {}
    prev_status = {st.get("id"): st for st in prev_feeds.get("feeds") or [] if isinstance(st, dict)}
    recent = {}
    for f in N.FEEDS:
        st = prev_status.get(f.id) or {}
        if (f.url in (reader or ()) and f.id not in barred and st.get("ok") and not st.get("skipped")
                and 0 <= _hours_since(st.get("checkedAt"), now) < READER_MIN_HOURS):
            recent[f.id] = {**st, "carried": True}
    try:
        found, status, raw = N.collect(fetch, now, feeds=[f for f in N.FEEDS if f.id not in barred | set(recent)],
                                       deadline=None if fixtures is not None else NEWS_DEADLINE_S)
    finally:
        if fixtures is None:
            news_fetcher.close()
    if barred or recent:
        by_id = {st["id"]: st for st in status}
        by_id.update({f.id: {**N._status(f, now, "omitido: su robots.txt no permite pedir este feed"), "skipped": "robots"}
                      for f in N.FEEDS if f.id in barred})
        by_id.update(recent)
        status = [by_id[f.id] for f in N.FEEDS]
    if barred:
        log.add("info", "news", "fetch", "feeds-robots",
                f"{len(barred)} feeds no se piden porque su robots.txt no lo permite (registro de fuentes).")
    asked_reader = sum(1 for f in N.FEEDS if f.url in (reader or ()) and f.id not in recent and f.id not in barred)
    if reader and (recent or asked_reader):
        log.add("info", "news", "fetch", "feeds-reader",
                f"Feeds que su robots.txt no permite, leídos como un lector de feeds (una vez cada {READER_MIN_HOURS} h): "
                f"{asked_reader} pedidos en esta corrida, {len(recent)} con la lectura anterior.")
    prev_text = previous.get_text("news/items.jsonl", tries=3) or ""
    had = (prev_feeds.get("history") or {}).get("items")
    # «restarted»: una corrida anterior publicó un histórico incompleto (no leyó ni el publicado ni la copia).
    incomplete = bool((prev_feeds.get("history") or {}).get("restarted"))
    if not prev_text and (had or history_dir is not None):
        # Sin el histórico publicado (sitio caído, otro hosting), se rehace con la copia de data-archive.
        prev_text = read_history_backup(history_dir)
        was = f" ({had} notas)" if had else ""
        if prev_text:
            incomplete = False
            log.add("warning", "news", "fetch", "news-history-missing",
                    f"No se pudo leer el histórico de noticias de la publicación anterior{was}; se rehízo con la "
                    f"copia de la rama data-archive ({prev_text.count(chr(10))} notas).")
        elif had:
            incomplete = True
            log.add("error", "news", "fetch", "news-history-missing",
                    f"No se pudo leer el histórico de noticias de la publicación anterior{was} ni la copia de la "
                    "rama data-archive: se publica solo con las notas de hoy y se completa en cuanto se lea la copia.")
    elif incomplete and history_dir is not None:
        # La publicación anterior empezó de nuevo: se le agregan al final (sin reordenar) las notas de la copia.
        backup = N.read_jsonl(read_history_backup(history_dir))
        if backup:
            known = {i["id"] for i in N.read_jsonl(prev_text)}
            back = [i for i in backup if i.get("id") not in known]
            if prev_text and not prev_text.endswith("\n"):
                prev_text += "\n"
            prev_text += "".join(json.dumps(i, ensure_ascii=False, separators=(",", ":")) + "\n" for i in back)
            incomplete = False
            log.add("warning", "news", "fetch", "news-history-restored",
                    f"Se completó el histórico de noticias con {len(back)} notas de la copia de data-archive "
                    "(una corrida anterior no pudo leerlo).")
    history = N.read_jsonl(prev_text)
    added = N.new_lines(history, found)
    if prev_text and not prev_text.endswith("\n"):
        prev_text += "\n"
    jsonl = prev_text + "".join(json.dumps(i, ensure_ascii=False, separators=(",", ":")) + "\n" for i in added)
    items = history + added

    for st in status:
        if st.get("skipped") or st.get("carried"):
            continue
        if not st["ok"]:
            log.add("info", "news", "fetch", "feed-down", f"{st['name']}: {st['error']}")
        elif not st["active"]:
            log.add("info", "news", "fetch", "feed-inactive",
                    f"{st['name']}: la entrada más reciente es del {st['latest'] or '¿?'}.")
    active = sum(1 for st in status if st["active"])
    asked = sum(1 for st in status if not st.get("skipped"))
    if active < asked / 2:
        log.add("warning", "news", "fetch", "news-degraded",
                f"Solo {active} de {asked} feeds de noticias están activos.")

    if raw_dir is not None and fixtures is None:
        day = now.date().isoformat()
        for fid, body in raw.items():
            d = raw_dir / f"news-{fid}"
            d.mkdir(parents=True, exist_ok=True)
            sha = hashlib.sha256(body).hexdigest()[:12]
            ext = N.FEED_BY_ID[fid].fixture.rsplit(".", 1)[-1] if fid in N.FEED_BY_ID else "xml"
            if not any(p.stem.endswith(f"-{sha}") for p in d.iterdir()):
                (d / f"{day}-{sha}.{ext}").write_bytes(body)
        if added:
            (raw_dir / "news").mkdir(parents=True, exist_ok=True)
            with open(raw_dir / "news" / f"{day}.jsonl", "a", encoding="utf-8") as fh:
                fh.write("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in added))
        if not incomplete:  # la copia de data-archive solo se reemplaza con un histórico entero
            (raw_dir / "news").mkdir(parents=True, exist_ok=True)
            (raw_dir / "news" / "items.jsonl").write_text(jsonl, encoding="utf-8")

    return {
        "jsonl": jsonl, "csv": N.to_csv(items), "items": items, "raw": raw,
        "live": {i["id"]: i["feed"] for i in found},
        "feeds": {"feeds": status, "history": {"items": len(items), "added": len(added),
                                               "since": min((i["first_seen"] for i in items), default=None),
                                               **({"restarted": True} if incomplete else {})}},
        "clusters": {"days": 14, "clusters": N.cluster(items, now), "departmentNames": department_names()},
    }


def load_relay(relay_dir: Path, log: EventLog, plan: Optional[dict[str, list[str]]] = None):
    """Abre las copias del recolector del Perú y registra si faltan o están viejas.

    ``plan`` (canales por URL del registro) sirve para decir cuántas URL solo se obtienen desde el Perú."""
    from .fetch import Relay, _age_hours, read_heartbeat

    only_peru = sorted(u for u, ch in (plan or {}).items() if ch == ["peru-server"])
    hosts = sorted({re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", u) for u in only_peru})
    lost = (f" {len(only_peru)} URL del registro solo responden desde el Perú ({', '.join(hosts[:6])}"
            f"{'…' if len(hosts) > 6 else ''}); sin ese recolector solo quedan sus réplicas y el Internet Archive." if only_peru else
            " SENAMHI, ANA, IMARPE y el portal del ENFEN se leen solo por réplicas y archivo.")

    def sources_down(hb: dict, last_copy: str) -> None:
        log.add("warning", "relay-peru", "fetch", "relay-sources-down",
                f"El recolector del Perú funciona (último intento {hb.get('at')}), pero ninguna fuente peruana "
                f"le respondió ({hb.get('reachable')}): son SENAMHI, ANA, IMARPE o el ENFEN, no el equipo. "
                f"{last_copy}")

    if not relay_dir.exists():
        # El flujo pasa la carpeta aunque falte: o la rama no existe o no se pudo bajar (su aviso dice cuál).
        log.add("warning", "relay-peru", "fetch", "relay-missing",
                "No hay copias de la rama data-peru en esta corrida: o la rama no existe (el recolector del Perú "
                "todavía no subió ninguna, docs/servidor-peru.md) o no se pudo bajar (ver el aviso del paso "
                f"«Fetch the Peru relay copies»).{lost}")
        return None
    try:
        relay = Relay(relay_dir)
    except (OSError, ValueError, KeyError) as exc:
        hb = read_heartbeat(relay_dir)
        if hb.get("result") == "sin-fuentes" and _age_hours(hb.get("at")) <= RELAY_STALE_HOURS:
            sources_down(hb, "Todavía no hay ninguna copia buena.")
        else:
            log.add("warning", "relay-peru", "fetch", "relay-missing",
                    f"No hay copias del recolector del Perú en {relay_dir.name} ({type(exc).__name__}: {exc}).{lost}")
        return None
    age = relay.age_hours
    # El latido se sube en cada corrida, aunque ninguna fuente responda: si es
    # reciente, el equipo funciona y son las fuentes las que no responden.
    hb = relay.heartbeat
    hb_age = _age_hours(hb.get("at")) if hb else float("inf")
    if age > RELAY_STALE_HOURS and hb.get("result") == "sin-fuentes" and hb_age <= RELAY_STALE_HOURS:
        sources_down(hb, f"Se usa la última copia buena, del {relay.collected_at} (hace {age:.0f} h).")
    elif age > RELAY_STALE_HOURS:
        beat = f" (último latido: {hb['at']})" if hb.get("at") else ""
        log.add("warning", "relay-peru", "fetch", "relay-stale",
                f"La última recolección desde el Perú es del {relay.collected_at} (hace {age:.0f} h); "
                f"revisar el recolector{f' en {relay.host}' if relay.host else ''}{beat}.")
    else:
        log.add("info", "relay-peru", "fetch", "relay-ok",
                f"Recolección desde el Perú del {relay.collected_at}: {relay.summary}.")
    # El recolector anota cuándo vence su token: avisar antes de que deje de subir.
    collector = (hb.get("collector") if hb_age < age else None) or relay.collector
    expires = str(collector.get("token_expires_at") or "")
    try:
        left = (datetime.fromisoformat(expires) - datetime.now(timezone.utc)).total_seconds() / 86400
    except (TypeError, ValueError):  # vacío, ilegible o sin zona horaria
        left = None
    if left is not None and left < RELAY_TOKEN_WARN_DAYS:
        log.add("warning", "relay-peru", "fetch", "relay-token-expiring",
                f"El token de GitHub del recolector del Perú vence el {expires[:10]} (en {max(left, 0):.0f} días): "
                "crear uno nuevo y ejecutar INSTALAR en ese equipo con el token nuevo (docs/servidor-peru.md).")
    return relay


def load_n8n_relay(n8n_dir: Path, log: EventLog):
    """Copias del flujo de n8n (rama ``data-n8n``): un segundo canal fuera de
    GitHub Actions para las fuentes que no están geobloqueadas."""
    from .fetch import Relay, _age_hours, read_heartbeat

    if not n8n_dir.exists():
        log.add("warning", "relay-n8n", "fetch", "relay-n8n-missing",
                "No hay copias de la rama data-n8n en esta corrida: o la rama no existe (el flujo «ENSO · Recolector "
                "n8n» no subió ninguna, docs/n8n.md) o no se pudo bajar (ver el aviso del paso «Fetch the n8n relay "
                "copies»). Si GitHub Actions no alcanza una fuente, no hay segundo canal.")
        return None
    hb = read_heartbeat(n8n_dir)
    hb_fresh = bool(hb) and _age_hours(hb.get("at")) <= RELAY_STALE_HOURS
    try:
        relay = Relay(n8n_dir, max_age_hours=RELAY_STALE_HOURS * 2)
    except (OSError, ValueError, KeyError) as exc:
        log.add("warning", "relay-n8n", "fetch", "relay-n8n-missing",
                f"No hay copias de n8n en {n8n_dir.name} ({type(exc).__name__}: {exc}).")
        return None
    if hb_fresh and hb.get("result") == "sin-fuentes":
        # n8n corrió (el latido es de hoy) pero ninguna fuente le respondió: no es n8n, son las fuentes o su red.
        log.add("warning", "relay-n8n", "fetch", "relay-n8n-sources-down",
                f"n8n corrió el {hb.get('at')}, pero ninguna fuente le respondió ({hb.get('reachable')}); solo quedan "
                f"copias anteriores de hasta {RELAY_STALE_HOURS * 2} h.")
    elif relay.age_hours > RELAY_STALE_HOURS:
        log.add("warning", "relay-n8n", "fetch", "relay-n8n-stale",
                f"La última corrida de n8n es del {relay.collected_at} (hace {relay.age_hours:.0f} h); "
                "revisar el flujo «ENSO · Recolector n8n» en n8n.")
    else:
        log.add("info", "relay-n8n", "fetch", "relay-n8n-ok",
                f"Copias de n8n del {relay.collected_at}: {relay.summary}.")
    return relay


def _fixture_date(fixtures: Path) -> Optional[date]:
    idx = fixtures / "index.json"
    if idx.exists():
        ts = json.loads(idx.read_text(encoding="utf-8")).get("captured_at", "")
        if ts:
            return date.fromisoformat(ts[:10])
    return None


def main(argv: Optional[list[str]] = None) -> int:
    from . import registry

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(REPO / "public" / "data"))
    ap.add_argument("--previous", default=LIVE_DATA, help="URL o carpeta de la publicación anterior ('' para ninguna)")
    ap.add_argument("--fixtures", default=None, help="Leer respuestas capturadas en lugar de la red")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--raw-dir", default=None, help="Carpeta donde archivar las respuestas originales nuevas")
    ap.add_argument("--relay-dir", default=None, help="Copia de la rama data-peru (recolector del Perú)")
    ap.add_argument("--n8n-dir", default=None, help="Copia de la rama data-n8n (flujo de n8n)")
    ap.add_argument("--history-dir", default=None,
                    help="Copia del histórico de noticias de la rama data-archive (sources/news/items.jsonl y "
                         "las notas de cada día), para rehacerlo si la publicación anterior no lo trae")
    ap.add_argument("--fail-on", default="critical", choices=["error", "critical", "never"])
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    res = run(out, args.previous or None, Path(args.fixtures).resolve() if args.fixtures else None, args.offline, only=args.only,
              raw_dir=Path(args.raw_dir).resolve() if args.raw_dir else None,
              relay_dir=Path(args.relay_dir).resolve() if args.relay_dir else None,
              n8n_dir=Path(args.n8n_dir).resolve() if args.n8n_dir else None,
              history_dir=Path(args.history_dir).resolve() if args.history_dir else None,
              plan=None if args.fixtures or args.offline else registry.url_channels(),
              reader=None if args.fixtures or args.offline else registry.reader_urls())
    print(json.dumps(res, ensure_ascii=False))
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(f"publication_id={res['publicationId']}\nworst={res['worst']}\n")
    if args.fail_on == "never":
        return 0
    order = ["info", "warning", "error", "critical"]
    return 1 if order.index(res["worst"]) >= order.index(args.fail_on) else 0


if __name__ == "__main__":
    sys.exit(main())
