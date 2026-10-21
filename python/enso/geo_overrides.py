"""Ubicación de todo el histórico de noticias y correcciones hechas a mano en la consola.

En cada corrida:

1. Se vuelve a ubicar cada nota del histórico con el nomenclátor actual (``geo.locate_item``), así una
   mejora de las reglas llega también a las notas viejas. Si la nota no guardó sus pistas (``geoHint``)
   y la nueva ubicación sale vacía, se conserva la que tenía.
2. Se aplican las correcciones de la consola (``/api/geo/overrides`` del sitio en Cloudflare). Si la
   consola no responde se usan las de la publicación anterior (``geo/overrides.json``): una corrección
   nunca se pierde porque un servicio esté caído.
3. Se publican ``geo/items.json`` (lo que la consola revisa), ``geo/overrides.json`` (lo aplicado, sin
   nombres de usuarios) y ``geo/quality.json`` (cuántas notas tienen lugar, con qué método y confianza).

Formato de una corrección (lo que devuelve la consola)::

    {"id": "<id de la nota>", "action": "set" | "confirm" | "none" | "foreign",
     "places": ["150101", "1501"], "rev": 3, "at": "2026-10-21T15:04:05Z"}

``set`` reemplaza los lugares; ``confirm`` deja los que hay y los marca revisados; ``none`` dice que la nota
no es de un lugar (alcance nacional o sin lugar); ``foreign`` dice que no ocurre en el Perú.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Optional

from .geo import GEO_VERSION, PUBLISH_MIN, gazetteer, legacy_fields, locate_item

ACTIONS = {"set", "confirm", "none", "foreign"}
#: Dirección de las correcciones; vacía, solo se usan las de la publicación anterior.
OVERRIDES_URL_ENV = "GEO_OVERRIDES_URL"
#: Notas que la consola recibe: las de los últimos días, hasta un máximo.
CONSOLE_DAYS = 120
CONSOLE_MAX = 4000
#: Por debajo de esta confianza una nota entra en la cola de revisión de la consola.
REVIEW_BELOW = 0.8


def _legacy_geo(item: dict) -> Optional[dict]:
    """El objeto ``geo`` de una nota guardada antes de que existiera (solo ``places``/``departments``)."""
    gz = gazetteer()
    if item.get("geoSource") == "medio":
        return None  # el departamento del medio no es evidencia: la versión nueva decide
    places = [gz.label(p["code"]) for p in item.get("places") or [] if gz.valid(p.get("code", ""))]
    if not places:
        return None
    conf = 0.7
    for p in places:
        p.update(confidence=conf, method="anterior", evidence="ubicación guardada por una versión anterior")
    return {"country": "PE", "scope": "local" if any(p["level"] != "departamento" for p in places) else "regional",
            "places": places, "departments": list(dict.fromkeys(p["code"][:2] for p in places)), "suggested": [],
            "confidence": conf, "method": "anterior", "v": 0}


def relocate(item: dict, feeds: dict) -> Optional[dict]:
    """Ubica de nuevo una nota del histórico."""
    hint = item.get("geoHint") or {}
    entry = {"title": item.get("title") or "", "summary": item.get("summary") or "", "outlet": item.get("outlet") or "",
             **hint}
    f = feeds.get(item.get("feed") or "")
    try:
        g = locate_item(entry, f, item.get("region") or "peru")
    except Exception:  # noqa: BLE001 — una nota rara conserva lo que tenía
        g = None
    old = item.get("geo") if (item.get("geo") or {}).get("places") else _legacy_geo(item)
    if (not g or not g["places"]) and old and not hint:
        return old
    return g


def _apply(item: dict, ov: dict) -> bool:
    gz = gazetteer()
    action = ov.get("action")
    stamp = {"rev": ov.get("rev"), "at": ov.get("at")}
    g = dict(item.get("geo") or {"country": "PE", "places": [], "departments": [], "suggested": []})
    if action == "set":
        codes = [c for c in dict.fromkeys(str(c) for c in ov.get("places") or []) if gz.valid(c)]
        if not codes:
            return False
        codes = [c for c in codes if not any(o != c and o.startswith(c) for o in codes)]
        places = []
        for c in codes:
            p = gz.label(c)
            p.update(confidence=1.0, method="correccion", evidence="corrección en la consola")
            places.append(p)
        g.update(country="PE", places=places, departments=list(dict.fromkeys(c[:2] for c in codes)),
                 suggested=[], confidence=1.0, method="correccion",
                 scope="local" if any(p["level"] != "departamento" for p in places) else
                 "regional" if len({c[:2] for c in codes}) <= 3 else "nacional")
    elif action == "confirm":
        if not g.get("places"):
            return False
        g["places"] = [dict(p, confidence=1.0) for p in g["places"]]
        g.update(confidence=1.0, suggested=[])
    elif action == "none":
        g.update(country="PE", scope="nacional", places=[], departments=[], suggested=[], confidence=None,
                 method="correccion")
    elif action == "foreign":
        g.update(country=None, scope="internacional", places=[], departments=[], suggested=[], confidence=None,
                 method="correccion")
    else:
        return False
    g["review"] = {"action": action, **stamp}
    item["geo"] = g
    for k in ("departments", "places", "geoSource"):
        item.pop(k, None)
    item.update(legacy_fields(g))
    return True


def valid_overrides(data: Any) -> list[dict]:
    """Correcciones bien formadas, la última revisión de cada nota."""
    rows = (data or {}).get("overrides") if isinstance(data, dict) else None
    out: dict[str, dict] = {}
    for r in rows or []:
        if not isinstance(r, dict) or r.get("action") not in ACTIONS or not isinstance(r.get("id"), str):
            continue
        if r["action"] == "set" and not isinstance(r.get("places"), list):
            continue
        prev = out.get(r["id"])
        if prev is None or (r.get("rev") or 0) >= (prev.get("rev") or 0):
            out[r["id"]] = {k: r.get(k) for k in ("id", "action", "places", "rev", "at")}
    return list(out.values())


def fetch_overrides(client, previous, log, url: Optional[str] = None) -> tuple[list[dict], str]:
    """(correcciones, origen). ``client`` es un ``httpx.Client`` o ``None`` (sin red)."""
    url = url if url is not None else os.environ.get(OVERRIDES_URL_ENV, "")
    if url and client is not None:
        try:
            r = client.get(url, headers={"Accept": "application/json"}, timeout=20)
            if r.status_code == 200:
                return valid_overrides(r.json()), "consola"
            log.add("warning", "geo", "fetch", "overrides-http",
                    f"La consola de lugares respondió HTTP {r.status_code}; se usan las correcciones anteriores.")
        except Exception as exc:  # noqa: BLE001
            log.add("warning", "geo", "fetch", "overrides-down",
                    f"No se pudo leer la consola de lugares ({type(exc).__name__}); se usan las correcciones anteriores.")
    prev = previous.get("geo/overrides.json") if previous is not None else None
    return valid_overrides(prev), "publicacion-anterior" if prev else "ninguna"


def apply_all(items: list[dict], overrides: list[dict], feeds: dict) -> dict:
    """Ubica de nuevo cada nota y aplica las correcciones. Devuelve la calidad de la ubicación."""
    for it in items:
        g = relocate(it, feeds)
        for k in ("departments", "places", "geoSource"):
            it.pop(k, None)
        it.pop("geo", None)
        if g:
            it["geo"] = g
            it.update(legacy_fields(g))
    by_id = {i["id"]: i for i in items}
    applied = unknown = rejected = 0
    for ov in overrides:
        it = by_id.get(ov["id"])
        if it is None:
            unknown += 1
        elif _apply(it, ov):
            applied += 1
        else:
            rejected += 1
    return quality(items, {"applied": applied, "unknownItem": unknown, "rejected": rejected})


def quality(items: list[dict], ov_stats: dict) -> dict:
    peru = [i for i in items if (i.get("geo") or {}).get("country") == "PE" or i.get("region") == "peru"]
    placed = [i for i in peru if (i.get("geo") or {}).get("places")]
    methods = Counter(p["method"] for i in placed for p in i["geo"]["places"])
    levels = Counter(max((p["level"] for p in i["geo"]["places"]), key=["departamento", "provincia", "distrito"].index)
                     for i in placed)
    low = sum(1 for i in placed if (i["geo"].get("confidence") or 0) < REVIEW_BELOW)
    return {"version": GEO_VERSION, "items": len(items), "peru": len(peru), "placed": len(placed),
            "nationalScope": sum(1 for i in peru if (i.get("geo") or {}).get("scope") == "nacional"),
            "finestLevel": dict(levels), "methods": dict(methods), "needsReview": low,
            "withSuggestions": sum(1 for i in peru if (i.get("geo") or {}).get("suggested")),
            "reviewed": sum(1 for i in items if (i.get("geo") or {}).get("review")),
            "overrides": ov_stats, "publishMin": PUBLISH_MIN, "reviewBelow": REVIEW_BELOW}


def console_items(items: list[dict], now: datetime) -> list[dict]:
    """Las notas recientes con su ubicación, para la consola (``geo/items.json``)."""
    since = (now - timedelta(days=CONSOLE_DAYS)).isoformat()
    recent = [i for i in items if (i.get("published") or i.get("first_seen") or "") >= since]
    recent.sort(key=lambda i: i.get("published") or i.get("first_seen") or "", reverse=True)
    out = []
    for i in recent[:CONSOLE_MAX]:
        out.append({"id": i["id"], "title": i.get("title") or "", "summary": (i.get("summary") or "")[:400],
                    "link": i.get("link") or "", "outlet": i.get("outlet") or "", "feed": i.get("feed") or "",
                    "kind": i.get("kind") or "", "region": i.get("region") or "", "relevance": i.get("relevance") or "",
                    "published": i.get("published") or i.get("first_seen"), "geo": i.get("geo")})
    return out


def console_gazetteer() -> dict:
    """Departamentos, provincias y distritos con sus nombres, para los selectores de la consola (``geo/ubigeo.json``)."""
    gz = gazetteer()
    return {"source": "INEI (UBIGEO)", "departments": {c: d["name"] for c, d in sorted(gz.deps.items())},
            "provinces": {c: d["name"] for c, d in sorted(gz.provs.items())},
            "districts": {c: d["name"] for c, d in sorted(gz.dists.items())}}

