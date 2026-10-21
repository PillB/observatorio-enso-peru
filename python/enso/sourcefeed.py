"""Feed de las fuentes oficiales: la última novedad de cada una, agrupada por tipo.

Se arma con los mismos datos de la publicación (no descarga nada): cada
entrada dice qué publicó la institución, cuándo, con qué valor y categoría,
y enlaza al documento o archivo original.
"""

from __future__ import annotations

import calendar
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


def alerts(news_items: list[dict], now: datetime) -> list[dict]:
    """Lo último de las fuentes oficiales de peligros (INDECI, SENAMHI, IGP, DHN, USGS…), sin agrupar.

    Cada aviso enlaza a la fuente en vivo y a la página del archivo del día en que se vio."""
    from .archive import news_page
    from .geo import department_names
    from .hazardparse import TG_KINDS
    from .news import FEED_BY_ID
    from .severity import assess

    since = (now - timedelta(days=ALERTS_DAYS)).isoformat()
    deps = department_names()
    out, seen = [], set()
    for i in sorted(news_items, key=lambda i: i.get("published") or i["first_seen"], reverse=True):
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
                    **assess(f.id, i["title"], i.get("summary") or "", when, now)})
        if len(out) >= ALERTS_MAX:
            break
    return out


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
            if st.get("channel"):  # respondió una copia (Perú, n8n), no la fuente: de cuándo es
                row.update({"channel": st["channel"], "copyAt": st.get("copyAt")})
            out.append(row)
    return out


def build(official: dict, series: dict, weekly: Optional[dict], sources: dict, relay=None,
          news_items: Optional[list[dict]] = None, now: Optional[datetime] = None,
          feed_status: Optional[list[dict]] = None) -> dict:
    """``sources``: id → {institution, docs, retrievedAt, channel, status}; ``news_items``: el histórico
    de noticias, del que salen las alertas de las fuentes oficiales de peligros; ``feed_status``: el
    estado de cada feed en esta corrida (``news/feeds.json``)."""
    items: list[dict] = alerts(news_items, now) if news_items and now else []
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
    return {"groups": groups}
