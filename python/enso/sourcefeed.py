"""Feed de las fuentes oficiales: la última novedad de cada una, agrupada por tipo.

Se arma con los mismos datos de la publicación (no descarga nada): cada
entrada dice qué publicó la institución, cuándo, con qué valor y categoría,
y enlaza al documento o archivo original.
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from typing import Optional

GROUPS = [
    ("alertas", "Alertas y reportes de peligros (últimos 7 días)"),
    ("oficial", "Comunicados y avisos oficiales"),
    ("indices", "Índices oficiales"),
    ("mar", "Temperatura del mar"),
    ("atmosfera", "Atmósfera"),
    ("subsuperficie", "Océano bajo la superficie"),
    ("peru", "Fuentes peruanas vía recolector"),
]

SERIES_GROUPS = {
    "indices": ["icen", "roni", "oni"],
    "mar": ["nino12_oisst", "nino34_oisst", "nino3_oisst", "nino4_oisst", "nino12", "nino34"],
    "atmosfera": ["soi_troup", "soi", "epac850_anom", "cpac850_anom", "wpac850_anom"],
    "subsuperficie": ["heat_180w100w", "heat_160e80w", "heat_130e80w"],
}

WEEKLY_LABEL = {"nino12": "Niño 1+2", "nino3": "Niño 3", "nino34": "Niño 3.4", "nino4": "Niño 4"}


def _period_date(period: str) -> str:
    """Fecha ISO del último día del periodo («2026-08» → 2026-08-31)."""
    if len(period) == 7 and period[4] == "-":
        y, m = int(period[:4]), int(period[5:])
        return f"{period}-{calendar.monthrange(y, m)[1]:02d}"
    return period[:10]


#: Avisos y reportes de las fuentes oficiales de peligros que se muestran como máximo.
ALERTS_MAX = 60
ALERTS_DAYS = 7


def _geo_brief(g: Optional[dict]) -> Optional[dict]:
    """Lo que el sitio necesita de la ubicación de un aviso: lugares con su confianza y cómo se obtuvieron."""
    if not g:
        return None
    keep = ("code", "level", "name", "department", "confidence", "method")
    return {"scope": g.get("scope"), "confidence": g.get("confidence"), "method": g.get("method"),
            "places": [{k: p[k] for k in keep if k in p} for p in g.get("places") or []],
            "reviewed": bool(g.get("review"))}


#: Puntos y formas que se publican como máximo por aviso (los focos de calor de un día llegan a cientos de celdas).
DETAIL_MAX_POINTS = 400
DETAIL_MAX_AREAS = 600


def _detail(i: dict) -> Optional[dict]:
    """Lo que ubica un aviso más fino que su distrito, para el mapa de alertas.

    - ``points``: lo que trae la fuente (estaciones hidrológicas con su cuenca, epicentros, volcanes, focos de calor)
      o el centro poblado que nombra (el PDF del COEN, ``documentos``, o el texto del aviso, ``lugares.localities``)
      y, si no nombra uno, el río, la quebrada o la laguna que nombra (``aguas.waters``), con su radio y su cuenca
      (ANA). En el texto el nombre debe ir tras una palabra que lo presente («caserío», «sector», «río»…).
    - ``shapes``: los polígonos de los avisos del SENAMHI (lluvias, peligro de incendios), simplificados.
    - ``areas``: los distritos con quebradas en un aviso de activación de quebradas, con cuántas, y las provincias
      expuestas de un aviso de corto plazo del COEN (``kind`` = provincia)."""
    d = i.get("detail") if isinstance(i.get("detail"), dict) else {}
    points = [p for p in d.get("points") or [] if isinstance(p, dict)]
    if not points:
        points = [p for p in i.get("localities") or [] if isinstance(p, dict)]
    codes = [p.get("code") or "" for p in (i.get("geo") or {}).get("places") or [] if len(p.get("code") or "") == 6]
    if not points and codes and not d.get("areas") and not d.get("shapes"):
        from .aguas import waters
        from .lugares import localities

        text = f"{i.get('title') or ''}. {i.get('summary') or ''}"
        try:
            points = localities(codes, text) or waters(codes, text)
        except Exception:  # noqa: BLE001 — sin el punto fino el aviso sigue en su distrito
            points = []
    out = {}
    if points:
        out["points"] = points[:DETAIL_MAX_POINTS]
    if d.get("shapes"):
        out["shapes"] = d["shapes"]
    areas = list(d.get("areas") or [])
    if i.get("provinces"):
        from .geo import gazetteer

        gz = gazetteer()
        areas += [{"code": c, "name": gz.label(c)["name"], "kind": "provincia"}
                  for c in i["provinces"] if isinstance(c, str) and len(c) == 4 and gz.valid(c)]
    if areas:
        out["areas"] = areas[:DETAIL_MAX_AREAS]
    return out or None


def alerts(news_items: list[dict], now: datetime, avisos=None) -> list[dict]:
    """Lo último de las fuentes oficiales de peligros (INDECI, SENAMHI, IGP, DHN, USGS…), sin agrupar.

    Cada aviso enlaza a la fuente en vivo y a la página del archivo del día en que se vio. ``avisos``: la
    tabla de avisos meteorológicos del SENAMHI (``senamhi_avisos``), de donde sale el nivel de los avisos
    que llegan por Telegram o por el COEN."""
    from .archive import news_page
    from .geo import department_names
    from .hazardparse import TG_KINDS
    from .news import FEED_BY_ID, latest_versions
    from .severity import assess

    since = (now - timedelta(days=ALERTS_DAYS)).isoformat()
    deps = department_names()
    out, seen = [], set()
    hidro = hidro_levels(news_items)
    # Una línea por aviso (``latest_versions``): la versión vista después. Ordenar por fecha no basta: el USGS, al
    # revisar el sismo us6000u1kt (magnitud 5,2 → 5,3), le corrigió también la hora en un segundo hacia atrás, y la
    # versión vieja quedaba primero y tapaba a la nueva.
    for i in sorted(latest_versions(news_items), key=lambda i: (i.get("published") or i["first_seen"], i["first_seen"]),
                    reverse=True):
        f = FEED_BY_ID.get(i.get("feed") or "")
        when = i.get("published") or i["first_seen"]
        if not f or not f.covers or when < since or i["link"] in seen:
            continue
        if f.adapter == "telegram" and not i["title"].startswith(tuple(TG_KINDS.values())):
            continue  # el canal mezcla avisos con notas de prensa («Senamhi capacita a…»)
        seen.add(i["link"])
        hz = [h for h in (i.get("hazards") or []) if h != "enso"]
        if len(hz) > 1:  # «mochila de emergencia», «rutas de evacuación»: consejo, no otro peligro
            hz = [h for h in hz if h != "emergencia"]
        where = [p["name"] if p.get("level") == "departamento" else f"{p['name']} ({deps.get(p['code'][:2], '')})".replace(" ()", "")
                 for p in (i.get("places") or [])][:3]
        out.append({"group": "alertas", "id": f"alert-{i['id']}", "source": f"news-{f.id}",
                    "institution": f.name.split("·")[0].strip(), "kind": f.name.split("·", 1)[-1].strip(),
                    "title": i["title"], "text": i.get("summary") or "", "date": when, "url": i["link"],
                    "archive": news_page(i), "hazards": hz[:3],
                    "where": where, "geo": _geo_brief(i.get("geo")), "stale": False,
                    **({"document": i["document"]} if i.get("document") else {}),
                    **({"detail": det} if (det := _detail(i)) else {}),
                    **assess(f.id, i["title"], i.get("summary") or "", when, now, avisos)})
        cross_level(out[-1], hidro)
        if len(out) >= ALERTS_MAX:
            break
    _share_places(out)
    return out


_HIDRO_NUM_RE = re.compile(r"aviso hidrol[óo]gico N° (\d+)", re.I)


def hidro_levels(news_items: list[dict]) -> dict[int, dict]:
    """Nivel de cada aviso hidrológico en la capa del SENAMHI (``senamhi-hidrologicos``), por su número: la
    segunda fuente del nivel de los avisos hidrológicos que difunde el COEN."""
    from .severity import severity

    out: dict[int, dict] = {}
    for i in news_items or []:
        if i.get("feed") != "senamhi-hidrologicos":
            continue
        m, sev = _HIDRO_NUM_RE.search(i.get("title") or ""), severity("senamhi-hidrologicos", i.get("title") or "", "")
        if m and sev:
            out[int(m.group(1))] = {**sev, "basis": f"nivel del aviso hidrológico N° {m.group(1)} en la capa del "
                                                    "SENAMHI en GEOSINPAD"}
    return out


def cross_level(alert: dict, hidro: dict[int, dict]) -> None:
    """Un aviso hidrológico del COEN toma el nivel de la capa del SENAMHI si su PDF no lo dio, y anota
    (``levelConflict``) si las dos fuentes no coinciden: ninguna de las dos se descarta en silencio."""
    from .severity import is_coen

    m = _HIDRO_NUM_RE.match(alert.get("title") or "")
    other = hidro.get(int(m.group(1))) if m and is_coen(alert["source"].removeprefix("news-")) else None
    if other is None:
        return
    own = alert.get("severity")
    if own is None:
        alert["severity"] = other
        alert.pop("levelStatus", None)
    elif own.get("rank") != other.get("rank"):
        alert["levelConflict"] = {"label": other["label"], "basis": other["basis"]}


#: Cuánto puede esperar un aviso que cita su número a que se lea el documento con su nivel antes de contar como
#: no leído (dos corridas diarias con su PDF o su tabla).
PENDING_HOURS = 48
_CITES_NUM_RE = re.compile(r"\bN°\s*\d+")


def _escalate(a: dict, now: datetime) -> None:
    st = a.get("levelStatus") or {}
    if st.get("code") != "pendiente" or not _CITES_NUM_RE.search(a.get("title") or ""):
        return
    try:
        age = (now - datetime.fromisoformat(a["date"].replace("Z", "+00:00"))).total_seconds() / 3600
    except (KeyError, ValueError, AttributeError):
        return
    if age > PENDING_HOURS:
        from .severity import STATUS

        label, _, _ = STATUS["no-leido"]
        a["levelStatus"] = {"code": "no-leido", "label": label, "loud": True,
                            "why": f"el aviso cita su número y su nivel sigue sin leerse después de {age:.0f} h "
                                   "(el PDF del COEN no lo dice o la tabla de avisos del SENAMHI no lo trae)"}


def _level_lines(bad: list[dict]) -> str:
    return "; ".join(f"«{a['title'][:110]}» ({a.get('url', '')}): {a['levelStatus']['why']}" for a in bad[:4]) + (
        f"; y {len(bad) - 4} más" if len(bad) > 4 else "")


def _classify_levels(alerts_: list[dict], now: datetime) -> tuple[dict[str, int], dict[tuple[str, str], list[dict]]]:
    """Cuántos avisos hay por razón, y los que abren incidencia agrupados por (fuente, razón)."""
    counts: dict[str, int] = {}
    by: dict[tuple[str, str], list[dict]] = {}
    for a in alerts_:
        _escalate(a, now)
        st = a.get("levelStatus")
        code = st["code"] if st else ("conflicto" if a.get("levelConflict") else None)
        if code:
            counts[code] = counts.get(code, 0) + 1
        if st and st.get("loud"):
            by.setdefault((a["source"], st["code"]), []).append(a)
        if a.get("levelConflict"):
            by.setdefault((a["source"], "conflicto"), []).append(a)
        if (a.get("severity") or {}).get("approx"):
            by.setdefault((a["source"], "aproximado"), []).append(a)
    return counts, by


def _log_conflict(log, src: str, bad: list[dict]) -> None:
    log.add("warning", src.removeprefix("news-"), "parse", "alert-level-conflict",
            f"{len(bad)} aviso(s) con un nivel distinto en el PDF del COEN y en la capa del SENAMHI: "
            + "; ".join(f"«{a['title'][:110]}»: PDF {a['severity']['label']}, capa {a['levelConflict']['label']}"
                        for a in bad[:4])
            + ". El mapa muestra el del PDF y la ficha avisa de la diferencia. Revisar cuál es el vigente "
              "(docs/niveles-de-aviso.md).")


def _log_approx(log, src: str, bad: list[dict]) -> None:
    log.add("warning", src.removeprefix("news-"), "parse", "alert-level-approx",
            f"{len(bad)} aviso(s) con el nivel leído por aproximación (una errata a una letra de la palabra de la "
            "escala): " + "; ".join(f"«{a['title'][:110]}»: «{a['severity']['approx']}» leído como "
                                    f"{a['severity']['label']}" for a in bad[:4])
            + ". El mapa lo muestra y la ficha dice que es una lectura aproximada. Confirmar en la respuesta archivada; "
              "si la fuente adoptó esa grafía, agregarla al vocabulario (enso/severity.py) con su prueba.")


_SPECIAL_LOGS = {"conflicto": _log_conflict, "aproximado": _log_approx}


def audit_levels(alerts_: list[dict], log, now: datetime) -> dict[str, int]:
    """Incidencias por los niveles que no se leyeron: ``alert-level-unread`` (la fuente asigna niveles y el lector
    no encontró este; un campo renombrado o un vocabulario nuevo), ``alert-level-norule`` (una fuente de peligros
    nueva sin regla en ``severity.level_status``), ``alert-level-conflict`` (el PDF del COEN y la capa del
    SENAMHI dan otro nivel al mismo aviso) y ``alert-level-approx`` (el nivel se leyó por aproximación). Devuelve cuántos avisos hay con cada razón (para el informe)."""
    counts, by = _classify_levels(alerts_, now)
    for (src, code), bad in sorted(by.items()):
        if code in _SPECIAL_LOGS:
            _SPECIAL_LOGS[code](log, src, bad)
            continue
        log.add("warning", src.removeprefix("news-"), "parse",
                "alert-level-norule" if code == "sin-regla" else "alert-level-unread",
                f"{len(bad)} aviso(s) de {src.removeprefix('news-')} sin nivel leído, de una fuente que sí asigna "
                f"niveles (o sin regla de niveles): {_level_lines(bad)}. En el mapa figuran «{bad[0]['levelStatus']['label']}»"
                ", no como sin peligro. Qué hacer: comparar el campo del nivel en la respuesta archivada con "
                "enso/severity.py (SCALES, _SEVERITY_BY_FEED, level_status) y seguir docs/niveles-de-aviso.md.")
    return counts


def audit_feed_levels(feed: dict, log, now: datetime) -> dict[str, int]:
    """``audit_levels`` sobre el grupo «alertas» de un ``feed.json`` armado por ``build``."""
    return audit_levels([i for g in feed.get("groups") or [] if g.get("id") == "alertas" for i in g["items"]], log, now)


def _brief_places(codes: list[str], confidence: float, method: str) -> list[dict]:
    from .geo import gazetteer

    gz = gazetteer()
    return [{**{k: v for k, v in gz.label(c).items() if k in ("code", "level", "name", "department")},
             "confidence": confidence, "method": method} for c in codes if gz.valid(c)]


def _share_places(rows: list[dict]) -> None:
    """Lugares de los avisos meteorológicos del SENAMHI que llegan sin ellos.

    1. El mismo aviso (año y número, de la tabla del SENAMHI) por otro canal: el mensaje de Telegram toma los
       departamentos expuestos que el COEN publica en el PDF de su boletín (``documentos``).
    2. Si ningún canal los trae, los departamentos de las regiones que nombra el aviso («costa norte y
       sierra», ``senamhi_avisos.REGIONS``), con confianza 0,6: el mapa los marca «≈» y la ficha dice de dónde
       salen. Sin región reconocible, el aviso sigue «sin departamento»."""
    from .geo import gazetteer
    from .senamhi_avisos import REGION_CONFIDENCE, region_departments

    gz = gazetteer()
    by_aviso: dict[tuple, dict] = {}
    for r in rows:
        a, g = r.get("aviso"), r.get("geo") or {}
        if a and g.get("places") and r.get("document"):
            by_aviso.setdefault((a.get("year"), a.get("num")), r)
    for r in rows:
        if r.get("kind") != "pronostico" or (r.get("geo") or {}).get("places"):
            continue
        a = r.get("aviso")
        src = by_aviso.get((a.get("year"), a.get("num"))) if a else None
        if src is not None:
            r["geo"] = {**src["geo"], "via": {"url": src["url"], "document": src["document"],
                                              "basis": f"departamentos del boletín del COEN del aviso N° {a['num']}"}}
        elif r["source"] in ("news-senamhi-telegram",) or r["source"].startswith("news-indeci-coen"):
            names, phrase = region_departments(f"{r['title']} {r.get('text') or ''}")
            codes = [c for c in (_dep_by_name(gz, n) for n in names) if c]
            if not codes:
                continue
            r["geo"] = {"scope": "regional" if len(codes) <= 3 else "nacional", "confidence": REGION_CONFIDENCE,
                        "method": "region", "places": _brief_places(codes, REGION_CONFIDENCE, "region"),
                        "reviewed": False,
                        "via": {"basis": f"regiones que nombra el aviso («{phrase}»), no departamentos de la fuente"}}
        else:
            continue
        r["where"] = [p["name"] for p in r["geo"]["places"]][:3]


def _dep_by_name(gz, name: str):
    hits = gz.find(name, "departamento")
    return hits[0] if len(hits) == 1 else None


def alert_sources(feed_status: Optional[list[dict]]) -> list[dict]:
    """Si cada fuente de alertas respondió en esta corrida. Sin avisos no quiere decir sin peligro:
    el sitio dice cuáles no respondieron, para que nadie lea su silencio como calma, y cuáles se leyeron
    de una copia de otro recolector (``channel``) y de cuándo es (``copyAt``)."""
    from .news import FEED_BY_ID

    out = []
    for st in feed_status or []:
        f = FEED_BY_ID.get(st.get("id") or "")
        if f and f.covers:
            row = {"id": f.id, "name": f.name, "url": f.url, "ok": bool(st.get("ok")),
                   "latest": st.get("latest"), "error": st.get("error") or ""}
            if st.get("formatError"):
                row["formatError"] = True
            if st.get("channel"):  # respondió una copia (Perú, n8n), no la fuente: de cuándo es
                row.update({"channel": st["channel"], "copyAt": st.get("copyAt")})
            out.append(row)
    return out


def levels_table(relay, log=None, now: Optional[datetime] = None):
    """La tabla de avisos del SENAMHI que da su nivel a los avisos de Telegram y del COEN (``senamhi_avisos``),
    y en ``log`` por qué falta o si es vieja: sin ella esos avisos quedan «sin nivel» y nadie lo notaría."""
    from .senamhi_avisos import STALE_HOURS, URL, load

    table, why = load(relay)
    if log is None or relay is None:
        return table
    fresh = getattr(relay, "age_hours", 0) <= STALE_HOURS  # si toda la copia es vieja, ya avisa «relay-stale»
    if why and fresh:
        log.add("warning", "senamhi-avisos", "parse", "senamhi-avisos-unread",
                f"No se pudo usar la tabla de avisos del SENAMHI ({URL}) de la copia del Perú: {why}. Los avisos "
                "del SENAMHI que llegan por Telegram y por el COEN quedan «sin nivel» en el mapa hasta que haya "
                "una copia legible; revisar esa URL en logs/recolector.log del equipo del Perú.")
    age = table.age_hours(now) if table is not None else None
    if age is not None and age > STALE_HOURS and fresh:
        log.add("warning", "senamhi-avisos", "fetch", "senamhi-avisos-stale",
                f"La tabla de avisos del SENAMHI que da el nivel a los avisos es del {table.copy_at} (hace {age:.0f} h): "
                "esta noche el equipo del Perú no la pudo bajar y se usa la copia anterior. Los avisos emitidos "
                "después quedan sin nivel y una cancelación posterior no se ve.")
    return table


def levels_from(table) -> Optional[dict]:
    """Para el pie del mapa: de qué copia de la tabla del SENAMHI salen los niveles (``archive`` lo agrega la
    publicación, con la copia servida por el sitio)."""
    from .senamhi_avisos import URL

    if table is None:
        return None
    return {"source": "senamhi-avisos", "institution": "SENAMHI", "url": URL, "copyAt": table.copy_at,
            "avisos": len(table)}


def build(official: dict, series: dict, weekly: Optional[dict], sources: dict, relay=None,
          news_items: Optional[list[dict]] = None, now: Optional[datetime] = None,
          feed_status: Optional[list[dict]] = None, avisos=None) -> dict:
    """``sources``: id → {institution, docs, retrievedAt, channel, status}; ``news_items``: el histórico
    de noticias, del que salen las alertas de las fuentes oficiales de peligros; ``feed_status``: el
    estado de cada feed en esta corrida (``news/feeds.json``); ``avisos``: la tabla de avisos del SENAMHI
    (``levels_table``; sin ella, se lee de ``relay`` sin registrar nada)."""
    from .senamhi_avisos import from_relay

    table = avisos if avisos is not None else from_relay(relay)
    items: list[dict] = alerts(news_items, now, table) if news_items and now else []
    status = alert_sources(feed_status)

    def src(sid: str) -> dict:
        return sources.get(sid) or {}

    e = official.get("enfen") or {}
    if e.get("number"):
        items.append({
            "group": "oficial", "id": "enfen", "source": "enfen-comunicados", "institution": "ENFEN", "kind": "comunicado",
            "title": f"Comunicado oficial N° {e['number']}: {e.get('status', '')}".strip(": "),
            "text": e.get("summary") or "", "date": e.get("issued"), "next": e.get("nextIssue"),
            "url": e.get("documentUrl") or e.get("url"), "stale": bool(e.get("stale")),
            "newerListed": e.get("newerListed"), "channel": e.get("channel"), "level": e.get("level"),
        })
    n = official.get("noaa") or {}
    if n.get("status"):
        items.append({
            "group": "oficial", "id": "noaa", "source": "cpc-ensodisc", "institution": "NOAA / CPC", "kind": "discusión diagnóstica",
            "title": f"ENSO Diagnostic Discussion: {n.get('statusEs') or n['status']}",
            "text": n.get("synopsis") or "", "date": n.get("issued"), "next": n.get("nextIssue"),
            "url": n.get("url"), "stale": bool(n.get("stale")), "channel": n.get("channel"), "level": n.get("level"),
        })

    for region, w in (weekly or {}).items():
        lt = w.get("latest") or {}
        if lt.get("date") is None:
            continue
        s = src("cpc-wksst")
        items.append({
            "group": "mar", "id": f"weekly-{region}", "source": "cpc-wksst", "institution": "NOAA / CPC", "kind": "semanal",
            "title": f"{WEEKLY_LABEL.get(region, region)} semanal (OISST)", "value": lt.get("anom"), "units": "degC",
            "period": lt["date"], "periodKind": "date", "date": lt["date"], "sst": lt.get("sst"),
            "url": s.get("docs"), "channel": s.get("channel"), "stale": False,
        })

    for group, keys in SERIES_GROUPS.items():
        for k in keys:
            meta = series.get(k)
            if not meta or not meta.get("latest"):
                continue
            lt = meta["latest"]
            s = src(meta["source"])
            prev = lt.get("previous") or {}
            items.append({
                "group": group, "id": k, "source": meta["source"], "institution": s.get("institution", ""),
                "kind": meta.get("frequency", ""),
                "title": meta["label"], "value": lt.get("value"), "units": meta.get("units"),
                "period": lt.get("period"), "periodKind": meta.get("periodKind"),
                "date": _period_date(lt.get("period") or ""), "change": prev.get("change"),
                "category": (lt.get("category") or {}).get("short"), "tone": (lt.get("category") or {}).get("tone"),
                "url": s.get("docs"), "channel": s.get("channel"), "stale": bool(lt.get("stale")),
                "retrievedAt": s.get("retrievedAt"),
            })

    if relay is not None:
        for group, ok in sorted(relay.summary.items()):
            if group.startswith("enfen"):
                continue
            items.append({
                "group": "peru", "id": f"relay-{group}", "institution": group.upper(), "kind": "copia diaria",
                "title": f"{group.upper()}: páginas descargadas desde el Perú", "text": f"{ok} respondieron.",
                "date": relay.collected_at[:10], "url": None, "channel": "relay-peru", "stale": relay.age_hours > 36,
            })

    order = {g: i for i, (g, _) in enumerate(GROUPS)}
    items.sort(key=lambda i: (order[i["group"]], -(int((i.get("date") or "0000-00-00").replace("-", "")[:8] or 0))))
    groups = [{"id": g, "label": label, "items": [i for i in items if i["group"] == g]}
              for g, label in GROUPS if any(i["group"] == g for i in items) or (g == "alertas" and status)]
    for g in groups:
        if g["id"] == "alertas":
            g["sources"] = status  # aunque no haya avisos: el grupo dice qué fuentes se consultaron
            if table is not None and any(i.get("aviso") for i in g["items"]):
                g["levelsFrom"] = levels_from(table)
    return {"groups": groups}
