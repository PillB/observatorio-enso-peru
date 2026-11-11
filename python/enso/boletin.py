"""Boletín de eventos de El Niño: una hoja con lo que viene, dónde y cuándo, y lo que cambió.

Arma ``data/boletin.json`` en cada publicación, con lo que el observatorio ya tiene:

- El estado del ENFEN (comunicado oficial), su perspectiva y, si el informe técnico vigente las trae, sus
  probabilidades para el verano; el estado de la NOAA.
- Los avisos oficiales vigentes y próximos relacionados con El Niño (lluvias, huaicos, inundaciones, oleaje, calor,
  ríos), del grupo «alertas» de ``feed.json``, con **el nivel que dio cada institución** (nunca uno propio). Un mismo
  aviso del SENAMHI que también difunde el INDECI cuenta una vez («Información duplicada»).
- El escenario de riesgo por lluvias del CENEPRED (distritos en riesgo muy alto y alto, por departamento).
- Los reportes de daños del INDECI de las últimas 72 horas.

Los «segmentos» son los 25 departamentos. Su orden de criticidad no es un puntaje inventado: es un orden
lexicográfico, explicado en el boletín y en docs/boletin.md: (1) el nivel más alto de un aviso oficial vigente o
próximo, (2) si ese nivel rige ya o solo se espera, (3) cuántos avisos tienen ese nivel, (4) cuántos distritos el
CENEPRED pone en riesgo muy alto, (5) cuántos reportes de daños hubo en 72 h.

Colores: rojo, naranja y amarillo son los niveles de las instituciones (SENAMHI nivel 4, 3 y 2, o su color); gris,
avisos sin nivel en su fuente; verde, ninguna institución tiene un aviso vigente o próximo relacionado con El Niño
en el departamento (como el nivel 1 verde del SENAMHI: no quiere decir que no haya peligro).

Cada boletín tiene un número de edición. Sube solo si algo cambió respecto del boletín anterior (la publicación
anterior): un aviso nuevo o que sube de nivel, un departamento que cambia de color, otro estado del ENFEN, un
comunicado o un escenario nuevo, un aviso cancelado. Cada cambio trae su regla («inmediata» o «resumen»): el flujo
de n8n (``n8n/nodes/boletin.js``) manda el correo con eso. ``recent`` guarda los cambios de las últimas ediciones,
para que n8n no pierda ninguno aunque se publiquen dos seguidas entre dos revisiones.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

SCHEMA = "enso-boletin/1"
SITE = "https://enso-peru.pages.dev/"
LIMA = timezone(timedelta(hours=-5))
DEP_NAMES = {
    "01": "Amazonas", "02": "Áncash", "03": "Apurímac", "04": "Arequipa", "05": "Ayacucho", "06": "Cajamarca",
    "07": "Callao", "08": "Cusco", "09": "Huancavelica", "10": "Huánuco", "11": "Ica", "12": "Junín",
    "13": "La Libertad", "14": "Lambayeque", "15": "Lima", "16": "Loreto", "17": "Madre de Dios", "18": "Moquegua",
    "19": "Pasco", "20": "Piura", "21": "Puno", "22": "San Martín", "23": "Tacna", "24": "Tumbes", "25": "Ucayali",
}
# Peligros que El Niño trae o agrava en el Perú (los del grupo «alertas» de feed.json). Sismos, volcanes, incendios
# heladas y el calor de la selva y la sierra no entran: se cuentan aparte («otros avisos») y se ven en el mapa de alertas.
FEN_HAZARDS = {
    "lluvias": "lluvias intensas", "huaico": "huaicos y activación de quebradas", "inundacion": "inundaciones",
    "oleaje": "oleaje anómalo", "sequia": "caudal de ríos", "emergencia": "lluvias en curso",
}
FEN_TITLE_RE = re.compile(r"precipitaci|lluvi|quebrad|huai?co|inunda|desborde|oleaje|caudal|\brío\b|crecida", re.I)
LEVELS = {3: ("rojo", "Rojo", "#c8261b"), 2: ("naranja", "Naranja", "#ef8a2b"), 1: ("amarillo", "Amarillo", "#f5d046"),
          0: ("sin-nivel", "Sin nivel", "#8fa0b4"), -1: ("verde", "Sin avisos", "#2e8b57")}
TOP = 10
ORDER = ["el nivel más alto de un aviso oficial vigente o próximo", "si ese nivel rige ya o solo se espera",
         "cuántos avisos tienen ese nivel", "cuántos avisos relacionados con El Niño tiene en total",
         "cuántos reportes de daños del INDECI hubo en 72 horas",
         "qué parte de sus distritos el CENEPRED pone en riesgo muy alto"]
REPORT_HOURS = 72
#: Las reglas de aviso, en el orden de la propuesta: qué situación, qué regla del código y qué se hace.
RULES = [
    {"rule": "aviso-nuevo", "when": "Un aviso oficial nuevo, rojo o naranja", "tier": "inmediata"},
    {"rule": "departamento-sube", "when": "Un departamento sube a naranja o a rojo", "tier": "inmediata"},
    {"rule": "aviso-sube", "when": "Un aviso sube a naranja o a rojo", "tier": "inmediata"},
    {"rule": "aviso-empieza", "when": "Un aviso naranja o rojo que se esperaba empieza a regir", "tier": "inmediata"},
    {"rule": "enfen-estado", "when": "El ENFEN cambia de estado (por ejemplo, de Vigilancia a Alerta)", "tier": "inmediata"},
    {"rule": "aviso-cancelado", "when": "Se cancela un aviso naranja o rojo que ya se había comunicado", "tier": "inmediata"},
    {"rule": "resumen", "when": "Avisos amarillos o sin nivel, departamentos que bajan, un comunicado del ENFEN sin cambio "
                                "de estado, un escenario nuevo del CENEPRED, otro estado de la NOAA", "tier": "resumen"},
    {"rule": "duplicado", "when": "El mismo aviso difundido por dos instituciones, o una publicación sin cambios",
     "tier": "ninguna"},
]
KEEP_RECENT = 14
ACTIVE = ("vigente", "en-curso", "proxima")
MAG_ES = {"debil": "débil", "moderada": "moderada", "fuerte": "fuerte", "muy_fuerte": "muy fuerte",
          "extraordinaria": "extraordinaria"}
CAT_ES = {"fria_fuerte": "La Niña fuerte", "fria_moderada": "La Niña moderada", "fria_debil": "La Niña débil",
          "neutro": "neutro", "calida_debil": "El Niño débil", "calida_moderada": "El Niño moderado",
          "calida_fuerte": "El Niño fuerte", "calida_muy_fuerte": "El Niño muy fuerte",
          "calida_extraordinaria": "El Niño extraordinario"}
REGION_ES = {"nino12": "la costa del Perú (Niño 1+2)", "nino34": "el Pacífico central (Niño 3.4)"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


# ---------------------------------------------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------------------------------------------
def _dt(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def when(iso: Optional[str]) -> str:
    """«mar 11 nov, 23:59» en hora de Lima."""
    d = _dt(iso)
    if not d:
        return ""
    d = d.astimezone(LIMA)
    return f"{DIAS[d.weekday()]} {d.day} {MESES[d.month - 1][:3]}, {d:%H:%M}"


def day(iso: Optional[str]) -> str:
    """«30 de octubre de 2026»."""
    d = _dt(iso) if iso and len(str(iso)) > 10 else (datetime.fromisoformat(str(iso)) if iso else None)
    if not d:
        return ""
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def month(ym: Optional[str]) -> str:
    try:
        y, m = str(ym).split("-")[:2]
        return f"{MESES[int(m) - 1]} de {y}"
    except (ValueError, IndexError):
        return ""


# ---------------------------------------------------------------------------------------------------------------
# Avisos
# ---------------------------------------------------------------------------------------------------------------
def phase(it: dict, now: datetime) -> str:
    """La misma regla que ``phaseOf`` del mapa de alertas (alertmap.js) y ``severity.phase``."""
    t = _dt(it.get("date"))
    kind = it.get("kind")
    if kind == "pronostico":
        if (it.get("aviso") or {}).get("cancelled"):
            return "cancelado"
        v = it.get("valid") or {}
        a, b = _dt(v.get("from")), _dt(v.get("until"))
        if a and b:
            return "proxima" if now < a else "vigente" if now <= b else "vencida"
        return "vigente" if t and now - t <= timedelta(hours=24) else "vencida"
    if kind in ("en-curso", "deteccion"):
        return "en-curso" if t and now - t <= timedelta(hours=it.get("currentHours") or 24) else "reciente"
    if kind == "reporte":
        return "ocurrido"
    return "en-curso" if t and now - t <= timedelta(hours=24) else "reciente"


def is_fen(it: dict) -> bool:
    hz = set(it.get("hazards") or [])
    if hz & set(FEN_HAZARDS):
        return True
    return not hz and bool(FEN_TITLE_RE.search(it.get("title") or ""))


def rank_of(it: dict) -> int:
    r = (it.get("severity") or {}).get("rank")
    return r if isinstance(r, int) and r > 0 else 0


def _places(it: dict) -> tuple[list[str], list[str], bool]:
    """Departamentos, nombres más finos (provincia o distrito) y si todos los lugares son aproximados."""
    deps, fine, approx = [], [], True
    for p in (it.get("geo") or {}).get("places") or []:
        code = str(p.get("code") or "")
        if code[:2] not in DEP_NAMES:
            continue
        if code[:2] not in deps:
            deps.append(code[:2])
        if p.get("level") in ("provincia", "distrito") and p.get("name") and p["name"] not in fine:
            fine.append(p["name"])
        c = p.get("confidence")
        if c is None or c >= 0.8 or p.get("method") == "correccion" or (it.get("geo") or {}).get("reviewed"):
            approx = False
    return deps, fine, approx and bool(deps)


def hazard_text(hz: list[str], title: str = "") -> str:
    return join_es(hazard_words(hz, title))


def hazard_words(hz: list[str], title: str = "") -> list[str]:
    words = [FEN_HAZARDS[h] for h in hz if h in FEN_HAZARDS]
    if "lluvias en curso" in words and "lluvias intensas" in words:
        words.remove("lluvias en curso")
    if not words:
        t = title.lower()
        words = ["lluvias intensas" if re.search(r"precipitaci|lluvi", t) else
                 "huaicos y activación de quebradas" if re.search(r"quebrad|huai?co", t) else
                 "oleaje anómalo" if "oleaje" in t else "caudal de ríos" if re.search(r"\brío\b|caudal|crecida", t)
                 else "inundaciones"]
    return list(dict.fromkeys(words))


def join_es(xs: list[str], limit: int = 0) -> str:
    """«A, B y C»; con ``limit``, «A, B, C y otros» si hay más."""
    xs = [x for x in xs if x]
    if limit and len(xs) > limit:
        return f"{', '.join(xs[:limit])} y otros"
    return xs[0] if len(xs) == 1 else f"{', '.join(xs[:-1])} y {xs[-1]}" if xs else ""


def short(t: str, n: int = 140) -> str:
    t = re.sub(r"^Aviso del SENAMHI: ", "SENAMHI: ", t or "").strip()
    letters = re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", t)
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        t = t.lower().capitalize()
        t = re.sub(r"\b(indeci|coen|senamhi|igp|dhn)\b", lambda m: m.group(0).upper(), t)
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def events(feed: Optional[dict], now: datetime) -> tuple[list[dict], list[dict], int]:
    """(avisos activos relacionados con El Niño, reportes de daños de las últimas 72 h, otros avisos activos)."""
    group = next((g for g in (feed or {}).get("groups") or [] if g.get("id") == "alertas"), {}) or {}
    merged: dict[str, dict] = {}
    reports, others = [], 0
    for it in group.get("items") or []:
        ph = phase(it, now)
        deps, fine, approx = _places(it)
        if it.get("kind") == "reporte":
            t = _dt(it.get("date"))
            if is_fen(it) and t and now - t <= timedelta(hours=REPORT_HOURS) and deps:
                reports.append({"id": it.get("id"), "title": short(it.get("title") or "", 110), "date": it.get("date"),
                                "institution": it.get("institution"), "deps": deps, "url": it.get("url")})
            continue
        if ph not in ACTIVE and ph != "cancelado":
            continue
        if not is_fen(it):
            others += ph in ACTIVE
            continue
        av = it.get("aviso") or {}
        key = f"senamhi-aviso-{av.get('year')}-{av.get('num')}" if av.get("num") else str(it.get("id"))
        sev = it.get("severity") or {}
        ev = {
            "key": key, "id": it.get("id"), "institution": it.get("institution"), "alsoBy": [],
            "title": short(it.get("title") or ""), "hazards": [h for h in it.get("hazards") or [] if h in FEN_HAZARDS],
            "what": hazard_text(it.get("hazards") or [], it.get("title") or ""),
            "whatList": hazard_words(it.get("hazards") or [], it.get("title") or ""),
            "rank": rank_of(it), "level": sev.get("label") or None, "scale": sev.get("scaleLabel") or None,
            "kind": it.get("kind"), "phase": ph, "from": (it.get("valid") or {}).get("from"),
            "until": (it.get("valid") or {}).get("until"), "date": it.get("date"), "deps": deps, "places": fine[:8],
            "approx": approx, "url": it.get("document") or it.get("url"),
        }
        old = merged.get(key)
        if old is None:
            merged[key] = ev
            continue
        # El mismo aviso del SENAMHI difundido también por el INDECI: uno solo, con la fuente de origen primero.
        main, other = (ev, old) if ev["institution"] == "SENAMHI" and old["institution"] != "SENAMHI" else (old, ev)
        main["alsoBy"] = sorted({*main["alsoBy"], *other["alsoBy"], other["institution"]} - {main["institution"]})
        main["rank"] = max(main["rank"], other["rank"])
        if not main["level"] and other["level"]:
            main["level"], main["scale"] = other["level"], other["scale"]
        main["deps"] = list(dict.fromkeys(main["deps"] + other["deps"]))
        main["places"] = list(dict.fromkeys(main["places"] + other["places"]))[:8]
        if "cancelado" in (main["phase"], other["phase"]):
            main["phase"] = "cancelado"
        merged[key] = main
    evs = sorted(merged.values(), key=lambda e: (e["phase"] == "cancelado", -e["rank"], e["phase"] == "proxima",
                                                 -(_dt(e["date"]) or now).timestamp()))
    reports.sort(key=lambda r: r["date"] or "", reverse=True)
    return evs, reports, others


# ---------------------------------------------------------------------------------------------------------------
# Segmentos (departamentos)
# ---------------------------------------------------------------------------------------------------------------
def scenario_by_dep(esc: Optional[dict]) -> dict[str, dict]:
    out = {d: {"districts": 0, "muyAlto": 0, "alto": 0} for d in DEP_NAMES}
    for code, row in ((esc or {}).get("districts") or {}).items():
        dep = str(code)[:2]
        if dep not in out:
            continue
        lv = [r[0] for r in row or [] if isinstance(r, list) and r and isinstance(r[0], int)]
        if not lv:
            continue
        out[dep]["districts"] += 1
        worst = min(lv)
        if worst == 0:
            out[dep]["muyAlto"] += 1
        elif worst == 1:
            out[dep]["alto"] += 1
    return out


def segments(evs: list[dict], reports: list[dict], esc: Optional[dict]) -> list[dict]:
    sc = scenario_by_dep(esc)
    rows = []
    for code, name in DEP_NAMES.items():
        mine = [e for e in evs if code in e["deps"] and e["phase"] in ACTIVE]
        rep = [r for r in reports if code in r["deps"]]
        if mine:
            top = max(e["rank"] for e in mine)
            at_top = [e for e in mine if e["rank"] == top]
            now_ = any(e["phase"] != "proxima" for e in at_top)
        else:
            top, at_top, now_ = -1, [], False
        starts = [e["from"] for e in at_top if e["phase"] == "proxima" and e["from"]]
        ends = [e["until"] for e in at_top if e["phase"] != "proxima" and e["until"]]
        hz = []
        for e in mine:
            for w in e["whatList"]:
                if w and w not in hz:
                    hz.append(w)
        places = []
        for e in at_top:
            for p in e["places"]:
                if p not in places:
                    places.append(p)
        cls, label, _ = LEVELS[top]
        rows.append({
            "code": code, "name": name, "rank": top, "color": cls, "label": label, "now": now_,
            "since": min(starts) if starts and not now_ else None, "until": max(ends) if ends else None,
            "events": [e["key"] for e in sorted(mine, key=lambda e: (-e["rank"], e["phase"] == "proxima"))],
            "eventsActive": len(mine),
            "eventsAtTop": len(at_top), "hazards": hz, "places": places[:6],
            "institutions": sorted({e["institution"] for e in at_top}),
            "scenario": sc[code], "reports": len(rep), "reportTitles": [r["title"] for r in rep[:3]],
        })
    share = lambda r: r["scenario"]["muyAlto"] / r["scenario"]["districts"] if r["scenario"]["districts"] else 0
    rows.sort(key=lambda r: (-r["rank"], not r["now"], -r["eventsAtTop"], -r["eventsActive"], -r["reports"],
                             -share(r), r["name"]))
    for i, r in enumerate(rows, 1):
        r["position"] = i
    return rows


# ---------------------------------------------------------------------------------------------------------------
# El Niño: ENFEN, NOAA y escenario
# ---------------------------------------------------------------------------------------------------------------
def enso_block(official: Optional[dict], freshness: Optional[dict]) -> dict:
    off = official or {}
    e, n = off.get("enfen") or {}, off.get("noaa") or {}
    items = (freshness or {}).get("items") or {}
    out: dict[str, Any] = {"enfen": None, "noaa": None, "outlook": [], "probabilities": []}
    if e.get("status"):
        out["enfen"] = {"status": e["status"], "code": e.get("statusCode"), "number": e.get("number"),
                        "issued": e.get("issued"), "next": e.get("nextIssue"), "stale": bool(e.get("stale")),
                        "url": e.get("documentUrl") or e.get("url"),
                        "summary": re.split(r"(?<=\.)\s", e.get("summary") or "")[0][:300] or None}
        if not e.get("stale"):
            out["outlook"] = [{"region": o.get("region"), "phase": o.get("phase"), "magnitude": o.get("magnitude"),
                               "until": o.get("until"), "quote": o.get("quote")} for o in e.get("outlook") or []]
    inf = e.get("informe") or {}
    if (inf.get("probabilities") and not e.get("stale")
            and (items.get("enfen-probabilities") or {}).get("state") != "vencido"):
        for t in inf["probabilities"]:
            s = t.get("summer") or {}
            top = sorted(((v, k) for k, v in s.items() if isinstance(v, (int, float)) and v > 0), reverse=True)[:2]
            if top:
                out["probabilities"].append({
                    "region": t.get("region"), "summer": [{"category": k, "label": CAT_ES.get(k, k), "pct": v}
                                                          for v, k in top],
                    "informe": inf.get("number"), "page": (t.get("evidence") or {}).get("page"), "url": inf.get("url")})
    if n.get("status"):
        out["noaa"] = {"status": n.get("statusEs") or n["status"], "issued": n.get("issued"),
                       "stale": bool(n.get("stale")), "url": n.get("url")}
    return out


def scenario_block(esc: Optional[dict], segs: list[dict]) -> Optional[dict]:
    if not esc or not esc.get("districts"):
        return None
    sc = esc.get("scenario") or {}
    tops = sorted((s for s in segs if s["scenario"]["muyAlto"]), key=lambda s: -s["scenario"]["muyAlto"])[:5]
    return {"id": sc.get("id"), "from": sc.get("from"), "until": sc.get("until"), "prepared": sc.get("prepared"),
            "muyAlto": sum(s["scenario"]["muyAlto"] for s in segs), "alto": sum(s["scenario"]["alto"] for s in segs),
            "districts": sum(s["scenario"]["districts"] for s in segs),
            "top": [{"code": s["code"], "name": s["name"], "muyAlto": s["scenario"]["muyAlto"]} for s in tops],
            "url": esc.get("url"), "carried": bool(esc.get("carried"))}


# ---------------------------------------------------------------------------------------------------------------
# Resumen: qué se viene, en cuatro líneas
# ---------------------------------------------------------------------------------------------------------------
def headline(enso: dict, segs: list[dict], evs: list[dict], reports: list[dict], scen: Optional[dict]) -> list[dict]:
    lines = []
    e = enso.get("enfen")
    if e:
        txt = f"El ENFEN mantiene «{e['status']}» (comunicado oficial N° {e['number']}, {day(e['issued'])})."
        if e["stale"]:
            txt = (f"El último comunicado del ENFEN leído es «{e['status']}» (N° {e['number']}); "
                   "ya debió salir uno más reciente.")
        ol = next((o for o in enso["outlook"] if o["region"] == "nino12"), None)
        if ol and ol.get("magnitude"):
            txt += (f" En la costa norte, El Niño tendría magnitud {MAG_ES.get(ol['magnitude'], ol['magnitude'])}"
                    f"{' hasta ' + month(ol['until']) if ol.get('until') else ''}.")
        pr = next((p for p in enso["probabilities"] if p["region"] == "nino12"), None)
        if pr:
            txt += (" Para el verano, el ENFEN estima " + join_es([f"{x['pct']} % de {x['label']}" for x in pr["summer"]])
                    + f" en {REGION_ES['nino12']} (informe técnico N° {pr['informe']}).")
        lines.append({"id": "enso", "title": "El Niño", "text": txt})
    by = {r: [s for s in segs if s["rank"] == r] for r in (3, 2, 1, 0)}
    if any(by[r] for r in (3, 2, 1, 0)):
        parts = []
        for r, word in ((3, "rojo"), (2, "naranja"), (1, "amarillo")):
            if by[r]:
                names = [s["name"] for s in by[r]]
                parts.append(f"{len(names)} en {word} ({join_es(names, 4)})")
        if by[0]:
            parts.append(f"{len(by[0])} con avisos sin nivel")
        top = next((x for x in evs if x["phase"] in ACTIVE), None)
        txt = f"Departamentos con avisos oficiales: {join_es(parts)}."
        if top:
            w = (f"desde {when(top['from'])}" if top["phase"] == "proxima" and top["from"]
                 else f"hasta {when(top['until'])}" if top["until"] else "en curso")
            txt += (f" El más alto: {top['institution']}, {top['level'] or 'sin nivel'}, {top['what']} en "
                    f"{join_es([DEP_NAMES[d] for d in top['deps'][:3]])}{' y más' if len(top['deps']) > 3 else ''}, {w}.")
        lines.append({"id": "avisos", "title": "Qué se viene", "text": txt})
    else:
        lines.append({"id": "avisos", "title": "Qué se viene",
                      "text": "Ninguna institución tiene hoy un aviso vigente o próximo relacionado con El Niño. "
                              "Eso no quiere decir que no haya peligro: siga al SENAMHI y al INDECI."})
    if scen:
        lines.append({"id": "riesgo", "title": "Riesgo esperado",
                      "text": f"El escenario del CENEPRED para {month(scen['from'])} a {month(scen['until'])} pone "
                              f"{scen['muyAlto']} distritos en riesgo muy alto y {scen['alto']} en alto por lluvias"
                              f"{', sobre todo en ' + join_es([t['name'] for t in scen['top'][:3]]) if scen['top'] else ''}."})
    if reports:
        deps = []
        for r in reports:
            for d in r["deps"]:
                if DEP_NAMES[d] not in deps:
                    deps.append(DEP_NAMES[d])
        lines.append({"id": "danos", "title": "Daños recientes",
                      "text": f"El INDECI reportó {len(reports)} {'emergencia' if len(reports) == 1 else 'emergencias'} "
                              f"por lluvias, huaicos u oleaje en las últimas {REPORT_HOURS} horas "
                              f"({join_es(deps[:4])}{' y otros' if len(deps) > 4 else ''})."})
    return lines


# ---------------------------------------------------------------------------------------------------------------
# Cambios y ediciones
# ---------------------------------------------------------------------------------------------------------------
def state(doc: dict) -> dict:
    e = (doc.get("enso") or {}).get("enfen") or {}
    return {
        "enfen": {"status": e.get("status"), "number": e.get("number")},
        "noaa": ((doc.get("enso") or {}).get("noaa") or {}).get("status"),
        "escenario": (doc.get("scenario") or {}).get("id"),
        "deps": {s["code"]: s["rank"] for s in doc.get("segments") or []},
        "events": {e["key"]: {"rank": e["rank"], "phase": e["phase"], "title": e["title"]}
                   for e in doc.get("events") or []},
    }


def diff(prev: Optional[dict], cur: dict, doc: dict) -> list[dict]:
    """Lo que cambió entre dos estados, cada cambio con su regla: «inmediata» (se avisa al momento) o «resumen»
    (va en el resumen diario). Sin estado anterior: un solo cambio «inicial»."""
    if not prev:
        return [{"rule": "inicial", "tier": "inmediata", "text": "Primer boletín: estado actual completo."}]
    out = []
    pe, ce = prev.get("enfen") or {}, cur["enfen"]
    if ce.get("status") and pe.get("status") and ce["status"] != pe["status"]:
        out.append({"rule": "enfen-estado", "tier": "inmediata",
                    "text": f"El ENFEN cambió su estado: de «{pe['status']}» a «{ce['status']}» (comunicado N° {ce['number']})."})
    elif ce.get("number") and ce.get("number") != pe.get("number"):
        out.append({"rule": "enfen-comunicado", "tier": "resumen",
                    "text": f"Nuevo comunicado oficial del ENFEN N° {ce['number']}: mantiene «{ce['status']}»."})
    if cur.get("noaa") and prev.get("noaa") and cur["noaa"] != prev["noaa"]:
        out.append({"rule": "noaa-estado", "tier": "resumen", "text": f"La NOAA pasó de «{prev['noaa']}» a «{cur['noaa']}»."})
    if cur.get("escenario") and prev.get("escenario") and cur["escenario"] != prev["escenario"]:
        sc = doc.get("scenario") or {}
        out.append({"rule": "escenario-nuevo", "tier": "resumen",
                    "text": f"Nuevo escenario de riesgo del CENEPRED (N° {cur['escenario']}, {month(sc.get('from'))} a {month(sc.get('until'))})."})
    pd = prev.get("deps") or {}
    for s in doc.get("segments") or []:
        a, b = pd.get(s["code"], -1), s["rank"]
        if a == b:
            continue
        up = b > a
        txt = (f"{s['name']} {'sube' if up else 'baja'} de {LEVELS[a][1].lower()} a {LEVELS[b][1].lower()}"
               + (f": {join_es(s['hazards'][:3])}" if up and s["hazards"] else "") + ".")
        out.append({"rule": "departamento-sube" if up else "departamento-baja", "dep": s["code"],
                    "tier": "inmediata" if up and b >= 2 else "resumen", "rank": b, "text": txt})
    pev = prev.get("events") or {}
    for e in doc.get("events") or []:
        old = pev.get(e["key"])
        place = join_es([DEP_NAMES[d] for d in e["deps"][:3]]) + (" y más" if len(e["deps"]) > 3 else "")
        if e["phase"] == "cancelado":
            if old and old.get("phase") != "cancelado":
                out.append({"rule": "aviso-cancelado", "tier": "inmediata" if old.get("rank", 0) >= 2 else "resumen",
                            "text": f"Cancelado: {e['title']} ({e['institution']})."})
            continue
        if old is None:
            out.append({"rule": "aviso-nuevo", "tier": "inmediata" if e["rank"] >= 2 else "resumen", "rank": e["rank"],
                        "text": f"Nuevo aviso {e['level'] or 'sin nivel'} de {e['institution']}: {e['what']} en {place}"
                                + (f", desde {when(e['from'])}" if e["phase"] == "proxima" and e["from"] else
                                   f", hasta {when(e['until'])}" if e["until"] else "") + "."})
        elif e["rank"] > old.get("rank", 0):
            out.append({"rule": "aviso-sube", "tier": "inmediata" if e["rank"] >= 2 else "resumen", "rank": e["rank"],
                        "text": f"Sube a {e['level']}: {e['title']} ({e['institution']})."})
        elif old.get("phase") == "proxima" and e["phase"] in ("vigente", "en-curso"):
            # El aviso esperado ya rige: cambia el «cuándo» del departamento aunque el nivel sea el mismo.
            out.append({"rule": "aviso-empieza", "tier": "inmediata" if e["rank"] >= 2 else "resumen", "rank": e["rank"],
                        "text": f"Ya rige: {e['title']} ({e['institution']})"
                                + (f", hasta {when(e['until'])}" if e["until"] else "") + "."})
    order = {"inmediata": 0, "resumen": 1}
    out.sort(key=lambda c: (order.get(c["tier"], 2), -c.get("rank", 0)))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Textos para compartir: correo (HTML con estilos en línea y un mapa de mosaicos) y WhatsApp
# ---------------------------------------------------------------------------------------------------------------
# Mapa de mosaicos: una celda por departamento, en una posición que respeta la geografía (norte arriba, costa a la
# izquierda). Funciona en cualquier cliente de correo, sin imágenes ni SVG.
TILES = {
    "24": (0, 0), "01": (0, 2), "16": (0, 3),
    "20": (1, 0), "06": (1, 1), "22": (1, 2),
    "14": (2, 0), "13": (2, 1), "10": (2, 2), "25": (2, 3),
    "02": (3, 1), "19": (3, 2), "12": (3, 3),
    "07": (4, 0), "15": (4, 1), "09": (4, 2), "05": (4, 3), "08": (4, 4), "17": (4, 5),
    "11": (5, 1), "03": (5, 3), "21": (5, 4),
    "04": (6, 2), "18": (6, 3),
    "23": (7, 3),
}
ABBR = {"01": "AMA", "02": "ANC", "03": "APU", "04": "ARE", "05": "AYA", "06": "CAJ", "07": "CAL", "08": "CUS",
        "09": "HVC", "10": "HUC", "11": "ICA", "12": "JUN", "13": "LAL", "14": "LAM", "15": "LIM", "16": "LOR",
        "17": "MDD", "18": "MOQ", "19": "PAS", "20": "PIU", "21": "PUN", "22": "SAM", "23": "TAC", "24": "TUM",
        "25": "UCA"}
INK = {3: "#ffffff", 2: "#1f1f1f", 1: "#1f1f1f", 0: "#1f1f1f", -1: "#ffffff"}


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def tile_map(segs: list[dict]) -> str:
    by = {s["code"]: s for s in segs}
    rows = []
    for r in range(8):
        cells = []
        for c in range(6):
            code = next((k for k, v in TILES.items() if v == (r, c)), None)
            if not code:
                cells.append('<td style="width:44px;height:30px;padding:0"></td>')
                continue
            s = by[code]
            bg, ink = LEVELS[s["rank"]][2], INK[s["rank"]]
            pat = "" if s["now"] or s["rank"] < 0 else ";background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.45) 0 4px,transparent 4px 8px)"
            cells.append(f'<td title="{_e(s["name"])}: {_e(s["label"])}" style="width:44px;height:30px;padding:0;'
                         f'background:{bg}{pat};color:{ink};font:700 11px/30px Arial,sans-serif;text-align:center;'
                         f'border:2px solid #ffffff">{ABBR[code]}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return ('<table role="img" aria-label="Mapa de los departamentos del Perú coloreados por el nivel más alto de sus '
            f'avisos" cellspacing="0" cellpadding="0" style="border-collapse:collapse">{"".join(rows)}</table>')


LEGEND = [
    (3, "Rojo: aviso de nivel más alto (SENAMHI nivel 4 o rojo) vigente o próximo."),
    (2, "Naranja: aviso de nivel 3 o naranja."),
    (1, "Amarillo: aviso de nivel 2 o amarillo."),
    (0, "Gris: avisos cuya institución no les da nivel."),
    (-1, "Verde: sin avisos oficiales vigentes ni próximos sobre lluvias, huaicos, inundaciones u oleaje. "
         "No quiere decir que no haya peligro."),
]


def _when_seg(s: dict) -> str:
    if s["rank"] < 0:
        return "—"
    if not s["now"] and s.get("since"):
        return f"Desde {when(s['since'])}"
    return f"Ahora{', hasta ' + when(s['until']) if s.get('until') else ''}"


def email_html(doc: dict, site: str) -> str:
    segs, c = doc["segments"], doc["counts"]
    top = [s for s in segs if s["rank"] >= 0][:TOP]
    site = site.rstrip("/") + "/"
    link = f"{site}#/boletin"
    chip = lambda r: (f'<span style="display:inline-block;padding:1px 8px;border-radius:9px;background:{LEVELS[r][2]};'
                      f'color:{INK[r]};font:700 12px Arial,sans-serif">{LEVELS[r][1]}</span>')
    counters = "".join(
        f'<td style="padding:6px 10px;text-align:center;border-radius:6px;background:{LEVELS[r][2]};color:{INK[r]};'
        f'font:700 20px Arial,sans-serif">{c[k]}<div style="font:600 11px Arial,sans-serif">{_e(lbl)}</div></td>'
        f'<td style="width:6px"></td>'
        for r, k, lbl in ((3, "rojo", "en rojo"), (2, "naranja", "en naranja"), (1, "amarillo", "en amarillo"),
                          (0, "sinNivel", "sin nivel"), (-1, "verde", "sin avisos")))
    lines = "".join(f'<p style="margin:0 0 8px;font:14px/1.45 Arial,sans-serif"><strong>{_e(x["title"])}.</strong> '
                    f'{_e(x["text"])}</p>' for x in doc["headline"])
    legend = "".join(f'<div style="font:12px/1.4 Arial,sans-serif;margin:0 0 3px"><span style="display:inline-block;'
                     f'width:10px;height:10px;background:{LEVELS[r][2]};margin-right:6px"></span>{_e(t)}</div>'
                     for r, t in LEGEND)
    rows = "".join(
        f'<tr style="border-top:1px solid #e0e0e0"><td style="padding:6px 4px;font:700 13px Arial,sans-serif;'
        f'vertical-align:top">{s["position"]}</td><td style="padding:6px 4px;vertical-align:top;font:13px Arial,sans-serif">'
        f'<strong>{_e(s["name"])}</strong><br>{chip(s["rank"])}</td>'
        f'<td style="padding:6px 4px;vertical-align:top;font:13px/1.35 Arial,sans-serif">'
        f'{_e(join_es(s["hazards"][:3]) or "—")}{"<br><span style=color:#555>" + _e(join_es(s["places"][:4])) + "</span>" if s["places"] else ""}</td>'
        f'<td style="padding:6px 4px;vertical-align:top;font:13px Arial,sans-serif">{_e(_when_seg(s))}</td>'
        f'<td style="padding:6px 4px;vertical-align:top;font:12px Arial,sans-serif">{_e(", ".join(s["institutions"]) or "—")}</td>'
        f'<td style="padding:6px 4px;vertical-align:top;font:12px Arial,sans-serif">{s["scenario"]["muyAlto"]} muy alto · {s["scenario"]["alto"]} alto</td></tr>'
        for s in top) or ('<tr><td colspan="6" style="padding:8px;font:13px Arial,sans-serif">Ningún departamento tiene '
                          'avisos vigentes o próximos relacionados con El Niño.</td></tr>')
    wa = "https://wa.me/?text=" + urllib.parse.quote(doc["whatsapp"])
    changes = doc.get("changes") or []
    ch = "".join(f'<li style="margin:0 0 4px">{_e(x["text"])}</li>' for x in changes[:8])
    ch_block = (f'<div style="background:#fff8e1;border-left:4px solid #ef6c00;padding:8px 12px;margin:0 0 12px">'
                f'<div style="font:700 13px Arial,sans-serif;margin:0 0 4px">Qué cambió en esta edición</div>'
                f'<ul style="margin:0;padding-left:18px;font:13px/1.4 Arial,sans-serif">{ch}</ul></div>'
                if ch and changes[0]["rule"] != "inicial" else "")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{_e(doc["email"]["subject"])}</title></head>
<body style="margin:0;padding:0;background:#f2f4f6">
<div style="display:none;max-height:0;overflow:hidden">{_e(doc["headline"][1]["text"] if len(doc["headline"]) > 1 else "")}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f2f4f6"><tr><td align="center" style="padding:12px">
<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden">
<tr><td style="background:#0b4f71;color:#ffffff;padding:14px 18px">
<div style="font:700 19px Arial,sans-serif">Boletín de eventos El Niño · Perú</div>
<div style="font:13px Arial,sans-serif;opacity:.9">Edición N° {doc["edition"]} · corte {_e(when(doc["cutoff"]))} (hora de Lima)</div></td></tr>
<tr><td style="padding:14px 18px"><!--cambios-->{ch_block}<!--/cambios-->
<table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 12px"><tr>{counters}</tr></table>
<div style="font:12px Arial,sans-serif;color:#555;margin:0 0 12px">Departamentos según el nivel más alto de sus avisos oficiales vigentes o próximos.</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>
<td valign="top" style="width:280px;padding-right:12px">{tile_map(segs)}<div style="margin-top:8px">{legend}</div></td>
<td valign="top">{lines}</td></tr></table>
<h2 style="font:700 15px Arial,sans-serif;margin:14px 0 6px">Los {len(top) or ""} departamentos más críticos</h2>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse">
<tr style="background:#eef3f6"><th align="left" style="padding:5px 4px;font:700 12px Arial,sans-serif">#</th><th align="left" style="padding:5px 4px;font:700 12px Arial,sans-serif">Departamento</th><th align="left" style="padding:5px 4px;font:700 12px Arial,sans-serif">Qué podría pasar · dónde</th><th align="left" style="padding:5px 4px;font:700 12px Arial,sans-serif">Cuándo</th><th align="left" style="padding:5px 4px;font:700 12px Arial,sans-serif">Fuente</th><th align="left" style="padding:5px 4px;font:700 12px Arial,sans-serif">Distritos en riesgo (CENEPRED)</th></tr>
{rows}</table>
<p style="margin:14px 0 0"><a href="{_e(link)}" style="display:inline-block;background:#0b4f71;color:#ffffff;padding:9px 14px;border-radius:6px;font:700 14px Arial,sans-serif;text-decoration:none">Ver el boletín y el detalle</a>
&nbsp; <a href="{_e(wa)}" style="font:14px Arial,sans-serif;color:#0b4f71">Compartir el resumen por WhatsApp</a></p>
<p style="margin:14px 0 0;font:11px/1.45 Arial,sans-serif;color:#666">Orden: {_e("; ".join(ORDER))}. Rayado: el nivel solo se espera (aviso próximo). Los niveles son los de cada institución (SENAMHI, INDECI, DHN, IGP); el boletín no emite alertas propias. Ante una emergencia, siga al INDECI, al SENAMHI y a su municipalidad.</p>
<p style="margin:6px 0 0;font:11px Arial,sans-serif;color:#666">Observatorio ENSO Perú · <a href="{_e(site)}" style="color:#0b4f71">{_e(site)}</a> · datos abiertos: <a href="{_e(site)}data/boletin.json" style="color:#0b4f71">boletin.json</a></p>
</td></tr></table></td></tr></table></body></html>
"""


def whatsapp_text(doc: dict, site: str) -> str:
    c = doc["counts"]
    segs = [s for s in doc["segments"] if s["rank"] >= 1][:5]
    emo = {3: "🔴", 2: "🟠", 1: "🟡"}
    lines = [f"*Boletín El Niño · Perú* (N° {doc['edition']}, {when(doc['cutoff'])})"]
    e = (doc["enso"] or {}).get("enfen")
    if e:
        lines.append(f"ENFEN: {e['status']} (comunicado N° {e['number']}).")
    lines.append(f"Departamentos: {c['rojo']} en rojo, {c['naranja']} en naranja, {c['amarillo']} en amarillo.")
    for s in segs:
        lines.append(f"{emo[s['rank']]} {s['name']}: {join_es(s['hazards'][:2])} · {_when_seg(s).lower()}")
    lines.append(f"Detalle: {site.rstrip('/')}/#/boletin")
    return "\n".join(lines)


def subject(doc: dict) -> str:
    c = doc["counts"]
    worst = next((s for s in doc["segments"] if s["rank"] >= 1), None)
    head = f"{c['rojo']} en rojo, {c['naranja']} en naranja" if (c["rojo"] or c["naranja"]) else "sin avisos rojos ni naranjas"
    return (f"Boletín El Niño N° {doc['edition']}: {head}"
            + (f" · {worst['name']} {worst['label'].lower()}" if worst and worst["rank"] >= 2 else ""))


def email_text(doc: dict, site: str) -> str:
    out = [f"Boletín de eventos El Niño · Perú — Edición N° {doc['edition']}, corte {when(doc['cutoff'])} (Lima)", ""]
    ch = [x for x in doc.get("changes") or [] if x["rule"] != "inicial"]
    if ch:
        out += ["Qué cambió:"] + [f"- {x['text']}" for x in ch[:8]] + [""]
    out += [f"{x['title']}: {x['text']}" for x in doc["headline"]] + ["", "Los más críticos:"]
    for s in [s for s in doc["segments"] if s["rank"] >= 0][:TOP]:
        out.append(f"{s['position']}. {s['name']} — {s['label']} — {join_es(s['hazards'][:3])} — {_when_seg(s)}")
    out += ["", f"Detalle: {site.rstrip('/')}/#/boletin",
            "Los niveles son los de cada institución; el boletín no emite alertas propias."]
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------------------------
# Armado
# ---------------------------------------------------------------------------------------------------------------
def build(feed: Optional[dict], official: Optional[dict], escenario: Optional[dict], now: datetime,
          previous: Optional[dict] = None, freshness: Optional[dict] = None,
          site: str = SITE) -> dict:
    evs, reports, others = events(feed, now)
    segs = segments(evs, reports, escenario)
    enso = enso_block(official, freshness)
    scen = scenario_block(escenario, segs)
    counts = {k: sum(1 for s in segs if s["rank"] == r)
              for k, r in (("rojo", 3), ("naranja", 2), ("amarillo", 1), ("sinNivel", 0), ("verde", -1))}
    counts.update({"avisos": sum(1 for e in evs if e["phase"] in ACTIVE),
                   "avisosAhora": sum(1 for e in evs if e["phase"] in ("vigente", "en-curso")),
                   "avisosProximos": sum(1 for e in evs if e["phase"] == "proxima"),
                   "reportes72h": len(reports), "otrosAvisos": others})
    group = next((g for g in (feed or {}).get("groups") or [] if g.get("id") == "alertas"), {}) or {}
    src = group.get("sources") or []
    doc: dict[str, Any] = {
        "schema": SCHEMA, "cutoff": now.isoformat(timespec="seconds"), "feedAt": (feed or {}).get("generatedAt"),
        "sources": {"ok": sum(1 for s in src if s.get("ok")), "total": len(src)},
        "enso": enso, "scenario": scen, "counts": counts, "segments": segs, "events": evs, "reports": reports[:30],
        "top": TOP, "legend": [{"rank": r, "color": LEVELS[r][0], "label": LEVELS[r][1], "text": t} for r, t in LEGEND],
        "order": ORDER, "rules": RULES,
    }
    doc["headline"] = headline(enso, segs, evs, reports, scen)
    st = state(doc)
    prev_state = (previous or {}).get("state") if isinstance(previous, dict) and previous.get("schema") == SCHEMA else None
    changes = diff(prev_state, st, doc)
    prev_ed = int((previous or {}).get("edition") or 0) if prev_state else 0
    if prev_state and not changes:
        # Nada cambió: la misma edición, con su fecha y sus cambios.
        doc["edition"] = prev_ed
        doc["editionAt"] = previous.get("editionAt") or previous.get("cutoff")
        doc["changes"] = previous.get("changes") or []
    else:
        doc["edition"] = prev_ed + 1
        doc["editionAt"] = doc["cutoff"]
        doc["changes"] = changes
    recent = [r for r in ((previous or {}).get("recent") or []) if r.get("edition") != doc["edition"]] if prev_state else []
    recent.insert(0, {"edition": doc["edition"], "at": doc["editionAt"], "changes": doc["changes"]})
    doc["recent"] = recent[:KEEP_RECENT]
    doc["alert"] = any(c["tier"] == "inmediata" for c in doc["changes"])
    doc["state"] = st
    doc["stateHash"] = hashlib.sha256(json.dumps(st, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    doc["whatsapp"] = whatsapp_text(doc, site)
    doc["email"] = {"subject": subject(doc), "text": email_text(doc, site)}
    doc["email"]["html"] = email_html(doc, site)
    return doc


def csv_segments(doc: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["edicion", "corte", "posicion", "ubigeo", "departamento", "nivel", "rige_ahora", "desde", "hasta",
                "peligros", "lugares", "instituciones", "avisos_en_ese_nivel", "distritos_riesgo_muy_alto",
                "distritos_riesgo_alto", "reportes_danos_72h"])
    for s in doc["segments"]:
        w.writerow([doc["edition"], doc["cutoff"], s["position"], s["code"], s["name"], s["label"], int(s["now"]),
                    s.get("since") or "", s.get("until") or "", "; ".join(s["hazards"]), "; ".join(s["places"]),
                    "; ".join(s["institutions"]), s["eventsAtTop"], s["scenario"]["muyAlto"], s["scenario"]["alto"],
                    s["reports"]])
    return buf.getvalue()


def _cell(v: Any) -> str:
    s = str(v if v is not None else "")
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s  # sin fórmulas al abrir en Excel o Power BI


def csv_events(doc: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["edicion", "clave", "institucion", "tambien_difunde", "nivel", "rango", "momento", "desde", "hasta",
                "peligros", "departamentos", "lugares", "titulo", "enlace"])
    for e in doc["events"]:
        w.writerow([doc["edition"], e["key"], e["institution"], "; ".join(e["alsoBy"]), e["level"] or "Sin nivel",
                    e["rank"], e["phase"], e["from"] or "", e["until"] or "", e["what"],
                    "; ".join(DEP_NAMES[d] for d in e["deps"]), _cell("; ".join(e["places"])), _cell(e["title"]),
                    e["url"] or ""])
    return buf.getvalue()
