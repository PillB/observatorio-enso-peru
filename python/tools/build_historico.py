"""Construye el catálogo histórico de desastres y lo publica para la pestaña «Memoria de desastres».

Pasos (todos reproducibles; ``docs/memoria-desastres.md``):

1. Descarga cada fuente de ``data/historico/fuentes.json`` a una caché local (``--cache``) y comprueba
   su SHA-256. Si la fuente cambió, se avisa y no se sigue sin ``--aceptar-cambios`` (que actualiza el
   manifiesto): así un cambio silencioso de la fuente no altera el catálogo publicado.
2. Lee cada fuente con su lector (``enso.historico.desinventar`` para 1970-2015,
   ``enso.historico.fuentes`` para SINPAD 2016-2018, IDMC 2019-2026 y NASA, registros curados en
   ``data/historico/curado/*.yaml``) y normaliza todo a ``enso.historico.esquema.COLUMNS``. Las capas de
   contexto (INGEMMET, ANA, establecimientos de salud) no son eventos: se resumen por distrito.
3. Ubica cada registro en su UBIGEO vigente y le asigna la fase ENSO del mes (ICEN y ONI).
4. Escribe:
   * ``public/assets/historico/eventos.csv``: el catálogo completo, con las 13 columnas del equipo de
     prevención primero (UTF-8 con BOM para que Excel lea las tildes).
   * ``public/assets/historico/eventos.json``: versión compacta para el navegador.
   * ``public/assets/historico/detalle/<departamento>.json``: descripción, lugar y fuente de cada registro,
     que el sitio pide solo al abrir un área.
   * ``public/assets/historico/resumen.json``: cobertura, fuentes, calendario ENSO, nombres y atributos
     de cada área.
   * ``public/assets/historico/contexto.json`` y ``data/historico/contexto-distrito.csv``: peligro
     identificado hoy en cada distrito (zonas críticas, puntos críticos de ríos y quebradas) junto con
     su historial.
   * ``data/historico/indicadores-<nivel>.csv``: los indicadores de recurrencia por área.
   Los CSV de ``data/historico/`` se copian también en ``public/assets/historico/`` para descargarlos
   desde el sitio.

Uso:
    python -m tools.build_historico                      # con la caché en ~/.cache/enso-historico
    python -m tools.build_historico --aceptar-cambios    # tras revisar un cambio de una fuente
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import yaml

from enso.fetch import ssl_context
from enso.historico import desinventar, esquema as E, fuentes as F
from enso.historico.enso import GREAT, NAMED, PIRCC_2017_URL, EnsoCalendar
from enso.historico.indicadores import by_area, nino_hydro_years
from enso.historico.registro import make
from enso.historico.territorio import Territory
from enso.observatory import csv_safe

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "historico"
MANIFEST = DATA / "fuentes.json"
CURATED = DATA / "curado"
OUT = ROOT / "public" / "assets" / "historico"
FIX = ROOT / "python" / "tests" / "fixtures" / "sources"
CACHE = Path.home() / ".cache" / "enso-historico"
REPO = "github.com/PillB/observatorio-enso-peru"
UA = {"User-Agent": f"observatorio-enso-peru (catalogo historico; https://{REPO})"}  # solo ASCII

#: Lectores de eventos: (archivo descargado, territorio, calendario, contador de descartes) → filas.
READERS = {
    "desinventar": lambda path, t, c, sk: desinventar.records(desinventar.read_export(path), t, c),
    "sinpad": lambda path, t, c, sk: F.sinpad(json.loads(path.read_text(encoding="utf-8")), t, c, skipped=sk),
    "idmc-idu": lambda path, t, c, sk: F.idmc_idu(path.read_text(encoding="utf-8"), t, c, skipped=sk),
    "idmc-eventos": lambda path, t, c, sk: F.idmc_events(path.read_text(encoding="utf-8"), t, c, skipped=sk),
    "nasa-glc": lambda path, t, c, sk: F.glc(json.loads(path.read_text(encoding="utf-8")), t, c, skipped=sk),
}
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


def fetch(src: dict, cache: Path, accept_changes: bool, offline: bool) -> Path:
    path = cache / src["archivo"]
    if not path.exists():
        if offline:
            raise SystemExit(f"{src['id']}: falta {path} y se pidió --sin-red")
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"descargando {src['url']}", file=sys.stderr)
        if src.get("descarga") == "arcgis":
            path.write_bytes(arcgis_dump(src["url"], src.get("campos", "*"), src.get("geometria", True),
                                         src.get("consulta", "1=1")))
        else:
            with httpx.Client(follow_redirects=True, timeout=180, headers=UA, verify=ssl_context()) as c:
                r = c.get(src["url"])
                r.raise_for_status()
                path.write_bytes(r.content)
    digest = sha256(path)
    if src.get("sha256") and digest != src["sha256"]:
        msg = f"{src['id']}: la fuente cambió (SHA-256 {digest[:12]}… ≠ {src['sha256'][:12]}… del manifiesto)"
        if not accept_changes:
            raise SystemExit(msg + ". Revise el cambio y repita con --aceptar-cambios.")
        print(msg + ": se acepta y se actualiza el manifiesto", file=sys.stderr)
    src["sha256"] = digest
    src.setdefault("obtenido", datetime.now(timezone.utc).date().isoformat())
    return path


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


def apply_reviews(records: list[dict], path: Path = DATA / "revisiones.yaml") -> list[dict]:
    """Aplica ``data/historico/revisiones.yaml`` (exclusiones y cifras dudosas, cada una con su motivo)."""
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
        if not n:
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
def write_csv(records: list[dict], path: Path) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(E.COLUMNS)
    for r in records:
        w.writerow([csv_safe("" if r.get(c) is None else r.get(c)) for c in E.COLUMNS])
    path.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")


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
        count = r.get("ImpactoEnTotales", "si") == "si"
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
                  "frecuenciaAnual", "frecuenciaIC_inf", "frecuenciaIC_sup", "periodoRetorno", "prob5Anios",
                  "distritoAnios", "distritoAniosPorAnio",
                  "razonNino", "razonNinoIC_inf", "razonNinoIC_sup", "grandesNinos", "nGrandesNinos",
                  "muestraPequena", "nivelAtencion", "peligroPrincipal", "ultimoEvento", "Fallecidos",
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
                        s["frecuenciaAnual"], *s["frecuenciaIC"], s["periodoRetorno"], s["prob5Anios"],
                        s["distritoAnios"], s["distritoAniosPorAnio"],
                        s["razonNino"], *s["razonNinoIC"], "; ".join(s["grandesNinos"]), len(s["grandesNinos"]),
                        "si" if s["muestraPequena"] else "no", s["nivelAtencion"],
                        s["peligros"][0][0] if s["peligros"] else "", (s["ultimo"] or {}).get("Date", ""),
                        s["impactos"].get("Fallecidos", 0), s["impactos"].get("Desaparecidos", 0),
                        s["impactos"].get("Afectados", 0), s["impactos"].get("Damnificados", 0),
                        s["impactos"].get("Desplazados", 0), s["impactos"].get("ViviendasDestruidas", 0),
                        t.population(code) if level != "region" else ""])
        path_for(level).write_text("\ufeff" + buf.getvalue(), encoding="utf-8")


CONTEXT_COLS = ["ubigeo", "departamento", "provincia", "distrito", "poblacion2020", "registros", "aniosConEvento",
                "frecuenciaAnual", "grandesNinos", "nivelAtencion", "registrosEventoEnCurso", "ingemmetPuntos",
                "ingemmetFlujos", "ingemmetDeslizamientos", "ingemmetCaidas", "zonasCriticasIngemmet", "puntosCriticosANA",
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
                    "; ".join(s["grandesNinos"]) if s else "", s["nivelAtencion"] if s else "", now.get(code, 0),
                    *(d.get("ing", [0] * 7)[:4]), len(d.get("zc", [])), len(a), sum(1 for x in a if x[3] == "Muy Alto"),
                    round(sum(x[4] or 0 for x in a)), round(sum(x[5] or 0 for x in a)), round(sum(x[7] or 0 for x in a)),
                    len(d.get("ips", []))])
    csv_path.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--aceptar-cambios", action="store_true")
    ap.add_argument("--sin-red", action="store_true", help="no descargar: usar solo la caché")
    ap.add_argument("--icen", type=Path, default=FIX / "igp-icen.txt")
    ap.add_argument("--oni", type=Path, default=FIX / "cpc-oni.txt")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    territory = Territory()
    calendar = EnsoCalendar.from_files(args.icen, args.oni)
    records: list[dict] = []
    context: dict[str, dict] = {}
    for src in manifest["fuentes"]:
        lector = src.get("lector")
        if lector in READERS:
            path = fetch(src, args.cache, args.aceptar_cambios, args.sin_red)
            skipped: Counter = Counter()
            got = list(READERS[lector](path, territory, calendar, skipped))
            src["registros"] = len(got)
            if skipped:
                src["descartados"] = dict(skipped.most_common())
            records += got
        elif lector in CONTEXT:
            path = fetch(src, args.cache, args.aceptar_cambios, args.sin_red)
            context[lector] = CONTEXT[lector](json.loads(path.read_text(encoding="utf-8")), territory)
            src["registros"] = sum(v["total"] if isinstance(v, Counter) else len(v) for v in context[lector].values())
    cur = curated_records(territory, calendar)
    for src in manifest["fuentes"]:
        if src.get("lector") == "curado":
            src["registros"] = len(cur)
    records += cur
    records = apply_reviews(records)
    ids = Counter(r["Id"] for r in records)
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        raise SystemExit(f"Id repetidos: {dup[:5]}")
    for r in records:
        r.setdefault("ImpactoEnTotales", "si")
    mark_duplicate_impacts(records)
    records.sort(key=lambda r: (r["Date"], r["Ubigeo"], r["Id"]))

    first, last = manifest["cobertura"]["homogenea"]
    years = range(first, last + 1)
    nino = nino_hydro_years(calendar, years)
    current = next((e for e in calendar.events if e["ongoing"] and e["phase"] == "warm"), None)
    ongoing = calendar.phase(current["start"]).short if current else None
    homogeneous = set(manifest["cobertura"]["origenes"])
    ind = by_area(records, years, nino, homogeneous)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "detalle").mkdir(exist_ok=True)
    write_csv(records, args.out / "eventos.csv")
    payload, detail = web_payload(records)
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
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
                     for k in ("id", "nombre", "tipo", "url", "pagina", "licencia", "cobertura", "registros", "nota")}
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
    }
    (args.out / "resumen.json").write_text(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_indicators(ind, territory, lambda lvl: DATA / f"indicadores-{lvl}.csv")
    write_context(context, ind, records, ongoing, territory, args.out / "contexto.json", DATA / "contexto-distrito.csv", generated)
    # Copias en el sitio para descargarlas sin pasar por el repositorio.
    for name in [f"indicadores-{lvl}.csv" for lvl in ind if lvl != "pais"] + ["contexto-distrito.csv"]:
        shutil.copyfile(DATA / name, args.out / name)
    manifest["generado"] = generated
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(records)} registros · {Counter(r['Origen'] for r in records)} · "
          f"{(args.out / 'eventos.json').stat().st_size / 1024:.0f} KB web")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
