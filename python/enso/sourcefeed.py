"""Feed de las fuentes oficiales: la última novedad de cada una, agrupada por tipo.

Se arma con los mismos datos de la publicación (no descarga nada): cada
entrada dice qué publicó la institución, cuándo, con qué valor y categoría,
y enlaza al documento o archivo original.
"""

from __future__ import annotations

import calendar
from typing import Optional

GROUPS = [
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


def build(official: dict, series: dict, weekly: Optional[dict], sources: dict, relay=None) -> dict:
    """``sources``: id → {institution, docs, retrievedAt, channel, status}."""
    items: list[dict] = []

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
    return {"groups": [{"id": g, "label": label, "items": [i for i in items if i["group"] == g]}
                       for g, label in GROUPS if any(i["group"] == g for i in items)]}
