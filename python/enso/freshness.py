"""Vigencia de cada dato que muestra el sitio, agrupada por vista.

Para cada panel del sitio dice qué dato muestra, de qué fuente, de qué fecha es (el periodo observado o la
fecha de emisión), cuándo lo bajó el observatorio, cuándo debería llegar el siguiente según el calendario de
la institución y, con eso, su estado:

* ``al-dia``: es el más reciente que la institución debía haber publicado;
* ``atrasado``: ya pasó la fecha en que la institución suele publicar el siguiente (más un margen) y aún
  no llegó, o llegó de una copia o del último dato conservado;
* ``vencido``: supera la antigüedad máxima de su fuente y el sitio no lo usa como actual;
* ``sin-dato``: la fuente no dio nada en esta publicación.

El calendario de cada producto (cuándo aparece el dato de un mes) es el que se observa en las fuentes:
NOAA publica los índices mensuales hacia el día 10 del mes siguiente; el IGP actualiza el ICEN cuando
llega el ERSST del mes posterior (por eso va dos meses detrás); el OISST semanal se publica el lunes
siguiente a la semana centrada en el miércoles; ENFEN y NOAA anuncian la fecha de su próximo comunicado.
El sitio solo presenta este resultado: no recalcula estados.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

STATES = ("al-dia", "atrasado", "vencido", "sin-dato")
#: Margen tras la fecha esperada antes de considerar atrasado un dato (días).
GRACE_DAYS = {"monthly": 5, "weekly": 2, "official": 1}
#: Día del mes en que suele estar el dato del mes M (en el mes M + desfase).
MONTHLY_DUE = {"default": (2, 10), "igp-icen": (3, 15),
               # RONI y ONI: el trimestre va con su mes central, que necesita el mes siguiente (JAS: octubre).
               "season": (3, 10)}

# Paneles de cada vista (rutas del sitio). Las series se nombran por su id en series.json.
VIEWS: dict[str, list[str]] = {
    "": ["enfen", "noaa", "weekly", "icen", "icen-provisional", "nino12_oisst", "roni", "nino34_oisst",
         "cpac850_anom", "heat_180w100w", "soi_troup", "epac850_anom"],
    "costero": ["enfen", "enfen-outlook", "enfen-probabilities", "icen", "icen-provisional", "weekly"],
    "pacifico": ["noaa", "roni", "oni", "nino3_oisst", "nino34_oisst", "nino4_oisst", "nino12_oisst"],
    "oceano": ["weekly", "nino12", "nino34", "nino12_oisst", "nino34_oisst", "wpac850", "cpac850", "epac850",
               "heat_180w100w", "heat_160e80w", "soi_troup"],
    "mapa": ["weekly"],  # el mapa dibuja solo las anomalías semanales
    "historia": ["icen"],
    "noticias": ["enfen", "noaa", "alerts", "news"],
}


#: Nombre de cada serie de las vistas, para la fila «sin dato» cuando la publicación no la trae.
SERIES_LABELS = {
    "icen": "ICEN oficial", "roni": "RONI", "oni": "ONI", "nino12": "Niño 1+2 (ERSSTv6)", "nino34": "Niño 3.4 (ERSSTv6)",
    "nino12_oisst": "Niño 1+2 (OISST)", "nino3_oisst": "Niño 3 (OISST)", "nino34_oisst": "Niño 3.4 (OISST)",
    "nino4_oisst": "Niño 4 (OISST)", "soi_troup": "SOI escala Troup", "wpac850": "Viento 850 hPa, Pacífico occidental",
    "cpac850": "Viento 850 hPa, Pacífico central", "epac850": "Viento 850 hPa, Pacífico oriental",
    "cpac850_anom": "Viento 850 hPa, Pacífico central (anomalía)",
    "epac850_anom": "Viento 850 hPa, Pacífico oriental (anomalía)",
    "heat_180w100w": "Contenido de calor 0–300 m (180°–100° O)", "heat_160e80w": "Contenido de calor 0–300 m (160° E–80° O)",
}


def _months(period: str, n: int) -> date:
    y, m = map(int, period[:7].split("-"))
    m += n
    y += (m - 1) // 12
    return date(y, (m - 1) % 12 + 1, 1)


def _state(today: date, due: Optional[date], grace: int, *, stale: bool = False, degraded: bool = False) -> str:
    if stale:
        return "vencido"
    if (due and today > due + timedelta(days=grace)) or degraded:
        return "atrasado"
    return "al-dia"


def _series_item(key: str, s: dict, today: date, meta: dict) -> dict:
    l = s.get("latest") or {}
    period = l.get("period")
    if not period or l.get("value") is None:
        return {"id": key, "label": s.get("label", key), "state": "sin-dato", "source": s.get("source")}
    lag, day = MONTHLY_DUE.get(s.get("source"), MONTHLY_DUE["season" if s.get("periodKind") == "season" else "default"])
    due = _months(period, lag).replace(day=day)
    m = meta.get(s.get("source")) or {}
    degraded = bool(l.get("carried")) or (m.get("channel") or "").startswith("archive")
    return {"id": key, "label": s.get("label", key), "kind": "serie", "observed": period,
            "observedKind": s.get("periodKind", "month"), "expectedNext": due.isoformat(),
            "state": _state(today, due, GRACE_DAYS["monthly"], stale=bool(l.get("stale")), degraded=degraded),
            "source": s.get("source"), "institution": m.get("institution"), "retrievedAt": m.get("retrievedAt"),
            "channel": m.get("channel"), "carried": bool(l.get("carried")), "sloDays": s.get("sloDays")}


def _official_item(key: str, o: Optional[dict], today: date, label: str, source: str) -> dict:
    if not o or not o.get("status"):
        return {"id": key, "label": label, "state": "sin-dato", "source": source}
    nxt = o.get("nextIssue")
    due = date.fromisoformat(nxt) if nxt else None
    return {"id": key, "label": label, "kind": "comunicado", "observed": o.get("issued"), "observedKind": "date",
            "document": o.get("number") or o.get("status"), "expectedNext": nxt,
            "expectedNextEstimated": bool(o.get("nextIssueEstimated")),
            "state": _state(today, due, GRACE_DAYS["official"], stale=bool(o.get("stale")),
                            degraded=bool(o.get("carried")) or (o.get("channel") or "").startswith("archive")),
            "source": source, "retrievedAt": o.get("retrievedAt"), "channel": o.get("channel"),
            "carried": bool(o.get("carried"))}


def build(series: dict, weekly: Optional[dict], official: dict, meta: dict, feed: Optional[dict],
          news_feeds: Optional[list[dict]], today: date, now: datetime) -> dict:
    """``meta``: id de fuente → {institution, retrievedAt, channel}; ``feed``: feed.json; ``news_feeds``: el
    estado de cada feed (news/feeds.json)."""
    items: dict[str, dict] = {}
    for key, s in series.items():
        items[key] = _series_item(key, s, today, meta)

    if weekly:
        last = max((w["latest"]["date"] for w in weekly.values() if w.get("latest")), default=None)
        if last:
            d = date.fromisoformat(last)
            m = meta.get("cpc-wksst") or {}
            items["weekly"] = {
                "id": "weekly", "label": "Temperatura del mar semanal (OISST)", "kind": "serie", "observed": last,
                "observedKind": "week", "expectedNext": (d + timedelta(days=12)).isoformat(),
                "state": _state(today, d + timedelta(days=12), GRACE_DAYS["weekly"], stale=(today - d).days > 16,
                                degraded=(m.get("channel") or "") == "previous-publication"
                                or (m.get("channel") or "").startswith("archive")),
                "source": "cpc-wksst", "institution": m.get("institution"), "retrievedAt": m.get("retrievedAt"),
                "channel": m.get("channel"), "carried": (m.get("channel") or "") == "previous-publication"}
    if "weekly" not in items:
        items["weekly"] = {"id": "weekly", "label": "Temperatura del mar semanal (OISST)", "state": "sin-dato",
                           "source": "cpc-wksst"}

    e = official.get("enfen") or {}
    items["enfen"] = _official_item("enfen", e, today, "Comunicado oficial del ENFEN", "enfen-comunicados")
    items["noaa"] = _official_item("noaa", official.get("noaa"), today, "Discusión diagnóstica de NOAA",
                                   "cpc-ensodisc")
    base = items["enfen"]
    if e.get("outlook"):
        items["enfen-outlook"] = {**base, "id": "enfen-outlook", "label": "Perspectiva del ENFEN (magnitud esperada)"}
    else:
        items["enfen-outlook"] = {"id": "enfen-outlook", "label": "Perspectiva del ENFEN (magnitud esperada)",
                                  "state": "sin-dato", "source": "enfen-comunicados"}
        if e.get("status") and not e.get("outlookUnread"):
            # Un comunicado sin perspectiva de magnitud (p. ej. «No activo») no deja un dato faltante.
            items["enfen-outlook"].update(optional=True, note="El comunicado vigente no trae una perspectiva de "
                                                              "magnitud por región.")
        elif e.get("outlookUnread"):
            items["enfen-outlook"]["note"] = "El comunicado trae una perspectiva que no se pudo leer (queda una incidencia)."
    inf = e.get("informe") or {}
    if inf.get("probabilities") or inf.get("icenProvisional") or inf.get("lastOfficial"):
        inf_state = "atrasado" if inf.get("carried") or (inf.get("communique") and e.get("number")
                                                          and inf["communique"] != e["number"]) else base["state"]
        withheld = sorted({i["message"] for i in inf.get("issues") or [] if i.get("severity") == "error"})
        common = {"kind": "informe", "observedKind": "date", "observed": inf.get("dataTo"),
                  "document": f"Informe técnico N° {inf.get('number')}", "expectedNext": e.get("nextIssue"),
                  "source": "enfen-informe", "url": inf.get("url"), "retrievedAt": inf.get("retrievedAt"),
                  "channel": inf.get("channel"), "carried": bool(inf.get("carried"))}
        items["enfen-probabilities"] = {**common, "id": "enfen-probabilities",
                                        "label": "Probabilidades mensuales del ENFEN",
                                        "state": inf_state if inf.get("probabilities") else "sin-dato"}
        if withheld:
            items["enfen-probabilities"]["note"] = ("Parte del informe no pasó la validación y no se publica: "
                                                    + "; ".join(withheld)[:400])
        tmp = inf.get("icenProvisional")
        items["icen-provisional"] = ({**common, "id": "icen-provisional", "label": "ICEN temporal (ENFEN)",
                                      "observed": tmp["period"], "observedKind": "month", "state": inf_state}
                                     if tmp else {"id": "icen-provisional", "label": "ICEN temporal (ENFEN)",
                                                  "state": "sin-dato", "source": "enfen-informe",
                                                  "note": "El informe no trae un valor válido del ICEN temporal."})
        if not tmp and inf.get("icenSuperseded"):
            # Se retira solo cuando el IGP publica el oficial de ese mes: no es un dato faltante.
            items["icen-provisional"].update(optional=True, note="El IGP ya publicó el ICEN oficial de ese mes; "
                                                                 "el temporal ya no hace falta.")
    else:
        for k, lbl in (("enfen-probabilities", "Probabilidades mensuales del ENFEN"),
                       ("icen-provisional", "ICEN temporal (ENFEN)")):
            items[k] = {"id": k, "label": lbl, "state": "sin-dato", "source": "enfen-informe"}

    alert_group = next((g for g in (feed or {}).get("groups", []) if g.get("id") == "alertas"), None)
    if alert_group is not None:
        src = alert_group.get("sources") or []
        ok = [s for s in src if s.get("ok")]
        dates = [i.get("date") for i in alert_group.get("items") or [] if i.get("date")]
        state = "vencido" if src and not ok else "atrasado" if len(ok) < len(src) else "al-dia"
        items["alerts"] = {"id": "alerts", "label": "Alertas de peligros (SENAMHI, INDECI, IGP, DHN y otras)",
                           "kind": "alertas", "observed": max(dates) if dates else None, "observedKind": "datetime",
                           "state": state if src else "sin-dato", "sourcesOk": len(ok), "sourcesTotal": len(src),
                           "retrievedAt": now.isoformat(timespec="seconds")}
    else:
        items["alerts"] = {"id": "alerts", "label": "Alertas de peligros", "state": "sin-dato"}
    if news_feeds:
        asked = [f for f in news_feeds if not f.get("skipped")]  # «omitido» por servidor caído o tiempo: falló
        ok = [f for f in asked if f.get("ok")]
        latest = max((f.get("latest") or "" for f in ok), default="") or None
        items["news"] = {"id": "news", "label": "Noticias de medios y del Estado", "kind": "noticias",
                         "observed": latest, "observedKind": "datetime",
                         "state": "vencido" if asked and not ok else "atrasado" if len(ok) < 0.6 * len(asked) else "al-dia",
                         "sourcesOk": len(ok), "sourcesTotal": len(asked),
                         "retrievedAt": now.isoformat(timespec="seconds")}
    else:
        items["news"] = {"id": "news", "label": "Noticias de medios y del Estado", "state": "sin-dato"}

    for keys in VIEWS.values():
        for k in keys:
            if k not in items:  # una serie que esta publicación no trae: fila «sin dato», no se omite
                items[k] = {"id": k, "label": SERIES_LABELS.get(k, k), "kind": "serie", "state": "sin-dato"}
    views = {}
    for view, keys in VIEWS.items():
        rows = [items[k] for k in keys]
        views[view] = {"items": [r["id"] for r in rows],
                       "worst": _worst(r["state"] for r in rows if not r.get("optional"))}
    views["datos"] = {"items": sorted(series), "worst": _worst(items[k]["state"] for k in series)}
    return {"today": today.isoformat(), "items": items, "views": views,
            "counts": {s: sum(1 for i in items.values() if i["state"] == s) for s in STATES}}


def _worst(states) -> str:
    order = {"al-dia": 0, "sin-dato": 1, "atrasado": 2, "vencido": 3}
    return max(states, key=lambda s: order.get(s, 0), default="al-dia")


def log_late(fresh: dict, log) -> None:
    """Cada dato atrasado queda como incidencia (y así como issue en GitHub). Los vencidos ya la tienen
    (``stale-*``, ``official-overdue``)."""
    for it in fresh["items"].values():
        if it["state"] == "atrasado" and it.get("kind") in ("comunicado", "informe", "serie"):
            exp = f"; se esperaba el siguiente hacia el {it['expectedNext']}" if it.get("expectedNext") else ""
            log.add("warning", it.get("source") or it["id"], "validate", f"late-{it['id']}",
                    f"{it['label']}: el dato más reciente es de {it.get('observed') or '—'} ({it['state']}){exp}.")
