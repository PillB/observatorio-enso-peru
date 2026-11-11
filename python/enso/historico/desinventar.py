"""Lector de la base DesInventar del Perú (1970–2015).

DesInventar (Corporación OSSO, LA RED; base del Perú alimentada por ITDG/Soluciones Prácticas y
PREDES, con fichas del INDECI desde los años 90) publica cada ficha con su distrito (UBIGEO del INEI),
fecha, tipo de evento, causa, efectos y la fuente original: casi siempre un diario (El Comercio,
La República, Expreso) con su fecha, o el INDECI/SINPAD. Es la serie más larga y homogénea de desastres
a escala distrital del país.

Exportación: https://www.desinventar.net/DesInventar/download/DI_export_per.zip (XML de DesInventar 8,
secciones ``eventos``, ``causas``, ``regiones``, ``fichas``). Licencia: datos abiertos con atribución
(«DesInventar Sendai, UNDRR / Corporación OSSO»).
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator, Optional

from . import esquema as E
from .fuentes import inside, locate_point

DOWNLOAD_URL = "https://www.desinventar.net/DesInventar/download/DI_export_per.zip"
PROFILE_URL = "https://www.desinventar.net/DesInventar/profiletab.jsp?countrycode=per"
LICENSE = "DesInventar Sendai (UNDRR / Corporación OSSO): uso libre con atribución"

#: Causas geofísicas: un deslizamiento o alud que desató un sismo no es un desastre de origen climático.
GEOPHYSICAL = {"Sismo", "Actividad volcánica"}
_QUAKE = re.compile(r"causa: (?:el )?(?:sismo|terremoto)|^(?:el )?(?:sismo|terremoto)|(?:consecuencia|producto|efecto) del (?:sismo|terremoto)"
                    r"|(?:tras|despues de|por) el (?:sismo|terremoto)|movimiento sismico")

_TR = re.compile(r"<TR>(.*?)</TR>", re.S)
_FIELD = re.compile(r"<([A-Za-z_0-9]+)>(.*?)</\1>", re.S)
_AUTHOR = re.compile(r"\(?\s*DI6Author\s*:[^)]*\)?", re.I)

#: Abreviaturas de diarios en la columna de fuentes (normalizadas sin puntos ni espacios).
PAPERS = [
    (re.compile(r"\b(?:E\.?\s?[lI]\.?\s?C(?:omercio)?|E\.\s?C|EL\s?C|ELC|EIC|EC)\b\.?", re.I), "El Comercio"),
    (re.compile(r"\b(?:La\s?R(?:ep[uú]blica)?|LAR)\b\.?", re.I), "La República"),
    (re.compile(r"\bEXP(?:RESO)?\b\.?", re.I), "Expreso"),
    (re.compile(r"\bE[lI]P\b\.?"), "El Peruano"),
]
#: Rótulos abreviados de las fichas del Perú cuyo significado no es ambiguo («E:», «G:» o «V:» sí lo son:
#: se dejan como están).
LABELS = {"Fe": "Fecha", "Ev": "Evento", "Act": "Acciones", "Ac": "Acciones", "EfS": "Efectos secundarios",
          "Ef": "Efectos", "Vp": "Valor de pérdidas", "Ag": "Agro", "Agr": "Agro", "Va": "Viviendas afectadas",
          "Vd": "Viviendas destruidas", "Tr": "Transporte", "Ca": "Causa", "Fu": "Fuente", "Damn": "Damnificados",
          "Gen": "General", "Op": "Obras públicas", "Du": "Duración", "Ed": "Educación"}
_LABEL = re.compile(r"(^|;\s|\.\s)(" + "|".join(sorted(LABELS, key=len, reverse=True)) + r")\.?\s?:")
_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b")


def _rows(xml: str, section: str) -> Iterator[dict]:
    m = re.search(rf"\n<{section}>\n(.*?)\n</{section}>", xml, re.S)
    if not m:
        return
    for tr in _TR.finditer(m.group(1)):
        yield {k: html.unescape(v).strip() for k, v in _FIELD.findall(tr.group(1))}


def read_export(path: Path) -> str:
    """Texto XML de la exportación (``.zip`` tal como se descarga, o el ``.xml``)."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
            return io.TextIOWrapper(z.open(name), encoding="utf-8").read()
    return path.read_text(encoding="utf-8")


def cite(raw: str) -> str:
    """«ElC 12.03.98» → «El Comercio 12/03/1998 (ElC 12.03.98)»; la cita original siempre queda."""
    raw = re.sub(r"\s+", " ", raw or "").strip()
    if not raw:
        return ""
    out = raw
    for rx, name in PAPERS:
        out = rx.sub(name, out)

    def _d(m: re.Match) -> str:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        y = int(y) if len(y) == 4 else (1900 + int(y) if int(y) > 30 else 2000 + int(y))
        return f"{d:02d}/{mo:02d}/{y}" if 1 <= d <= 31 and 1 <= mo <= 12 else m.group(0)

    out = _DATE.sub(_d, out)
    return out if out == raw else f"{out} (cita original: {raw})"


def _num(v: str) -> Optional[float]:
    """Cifra positiva o None: en DesInventar un 0 casi siempre significa «no registrado», no «ninguno»."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return (int(x) if x == int(x) else round(x, 2)) if x > 0 else None


def _km(v: str) -> Optional[float]:
    """Los kilómetros de vías: DesInventar los guarda en metros aunque el campo se llame «kmvias» («Routes affected:
    the length of transport networks destroyed and/or rendered unusable, in metres», DesInventar Methodological Guide
    8.1.9, 2009; San Hilarión, 1996: «7 kms de la Carretera Marginal», kmvias = 7000)."""
    m = _num(v)
    return (int(m) // 1000 if m % 1000 == 0 else round(m / 1000, 3)) if m else None


def _clean(text: str) -> str:
    text = _AUTHOR.sub("", text or "")
    text = re.sub(r"\s*/\s*", "; ", text)
    text = re.sub(r"\s+", " ", text).strip(" ;")
    return _LABEL.sub(lambda m: f"{m.group(1)}{LABELS[m.group(2)]}:", text)


def records(xml: str, territory, calendar) -> Iterator[dict]:
    """Fichas de peligros de origen climático normalizadas a ``esquema.COLUMNS``."""
    for r in _rows(xml, "fichas"):
        src_type = r.get("evento", "")
        dt = E.DESINVENTAR_TYPES.get(src_type)
        cause = r.get("causa", "")
        if not dt:
            continue
        if dt in ("Epidemia", "Plaga") and cause not in ("El Niño", "La Niña", "Lluvias", "Inundación", "Sequía"):
            continue
        if cause in GEOPHYSICAL or _QUAKE.search(E.key(r.get("descausa", "") + " " + r.get("di_comments", "")[:400])):
            continue  # el alud de Yungay de 1970 lo desató el sismo, no el clima
        try:
            y = int(r.get("fechano") or 0)
        except ValueError:
            continue
        if y < 1900:
            continue
        mo = int(r.get("fechames") or 0) if (r.get("fechames") or "0").isdigit() else 0
        dd = int(r.get("fechadia") or 0) if (r.get("fechadia") or "0").isdigit() else 0
        mo = mo if 1 <= mo <= 12 else 0
        try:
            d0 = date(y, mo or 1, dd if (mo and 1 <= dd <= 31) else 1)
        except ValueError:
            d0, dd = date(y, mo or 1, 1), 0
        precision = "dia" if mo and dd else "mes" if mo else "anio"

        comments = _clean(r.get("di_comments", ""))
        descausa = _clean(r.get("descausa", ""))
        lugar = _clean(r.get("lugar", ""))
        otros = _clean(r.get("otros", ""))
        method = "fuente"
        if dt == "Inundacion":
            dt, method = E.classify_flood([comments, descausa, lugar, otros, r.get("magnitud2", "")], cause)

        code = territory.resolve(r.get("name0", ""), r.get("name1", ""), r.get("name2", ""),
                                 r.get("level2") or r.get("level1") or r.get("level0", ""))
        if not code:
            continue
        dep, prov, dist = territory.names(code)
        lat, lon, geo_prec = territory.point(code)
        # Las coordenadas de la fuente solo si caen en el área asignada (algunas contradicen el lugar).
        loc, pt = locate_point(r.get("latitude"), r.get("longitude"))
        if pt and inside(territory, code, loc):
            (lat, lon), geo_prec = pt, "coordenada-fuente"

        dur = _num(r.get("duracion", ""))
        dur = int(dur) if dur and dur >= 1 else None
        end = (d0 + timedelta(days=dur - 1)).isoformat() if dur and precision == "dia" else ""

        ph = calendar.phase(d0.isoformat()[:7]) if precision != "anio" else None
        tipo, attrib = calendar.tipo_evento(d0.isoformat(), precision != "anio", dt, code[:2], cause)

        imp = {
            "Fallecidos": _num(r.get("muertos")), "Desaparecidos": _num(r.get("desaparece")),
            "Heridos": _num(r.get("heridos")), "Afectados": _num(r.get("afectados")),
            "Damnificados": _num(r.get("damnificados")), "Evacuados": _num(r.get("evacuados")),
            "Reubicados": _num(r.get("reubicados")), "Desplazados": None, "ViviendasDestruidas": _num(r.get("vivdest")),
            "ViviendasAfectadas": _num(r.get("vivafec")), "HectareasCultivo": _num(r.get("nhectareas")),
            "KmVias": _km(r.get("kmvias")), "CentrosEducativos": _num(r.get("nescuelas")),
            "CentrosSalud": _num(r.get("nhospitales")), "PerdidasUSD": _num(r.get("valorus")),
        }
        reported = any(v for v in imp.values())

        place = ", ".join(x for x in (lugar, dist, prov, dep) if x)
        parts = [f"{src_type} en {place}."]
        if descausa and descausa.lower() not in ("no especifica", "desconocida", "desconocida."):
            parts.append(f"Causa: {descausa}.")
        if comments:
            parts.append(comments if comments.endswith(".") else comments + ".")
        if otros:
            parts.append(f"Otros daños: {otros}.")
        desc = " ".join(parts)

        conf_geo = len(code) == 6
        conf_type = method in ("fuente", "texto")
        confidence = "alta" if conf_geo and precision == "dia" and conf_type else (
            "media" if (conf_geo or len(code) == 4) and precision != "anio" else "baja")

        yield {
            "Date": d0.isoformat(), "DangerType": dt, "Ubicacion": lugar, "Distrito": dist, "Provincia": prov,
            "Departamento": dep, "Descripción": desc, "DuraciónEvento": dur, "Ubigeo": code,
            "TipoEvento": tipo, "Fuente": PROFILE_URL, "Latitud": lat, "Longitud": lon,
            "Id": f"desinventar-{r.get('clave', '')}", "Origen": "desinventar", "IdFuente": f"serial {r.get('serial', '')} · uu_id {r.get('uu_id', '')}",
            "FechaFin": end, "PrecisionFecha": precision, "Anio": y, "Mes": mo or None,
            "AnioHidrologico": E.hydro_year(y, mo), "GrupoPeligro": E.danger_group(dt),
            "PeligroFuente": src_type, "DangerTypeMetodo": method, "CausaFuente": cause,
            "NivelUbigeo": {2: "departamento", 4: "provincia", 6: "distrito"}[len(code)],
            "PrecisionGeo": geo_prec, "Region": territory.region(code), "AltitudCapital": territory.altitude(code),
            "FaseENSO": ph.phase if ph else "", "EventoENSO": ph.event if ph else "",
            "ICEN": ph.icen if ph else None, "ONI": ph.oni if ph else None, "AtribucionENSO": attrib,
            **imp, "ImpactoReportado": "si" if reported else "no",
            "FuenteCita": cite(r.get("fuentes", "")), "Licencia": LICENSE, "Confianza": confidence,
        }
