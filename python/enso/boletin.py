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
          0: ("sin-nivel", "Sin nivel", "#8fa0b4"), -1: ("verde", "Sin avisos", "#1f7a4c")}
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
    """«30 de octubre de 2026». Vacío si la fecha no se entiende (nunca una excepción: un comunicado con la fecha mal
    escrita no puede dejar el sitio sin boletín)."""
    if not iso:
        return ""
    s = str(iso)
    d = _dt(s) if len(s) > 10 else None
    if d is None:
        try:
            d = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return ""
    elif len(s) > 10:
        d = d.astimezone(LIMA)
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def iso(v: Any) -> Optional[str]:
    """Una fecha en ISO 8601 con zona (la que entienden Safari y Firefox), o None si no se entiende."""
    d = _dt(v) if v else None
    return d.isoformat(timespec="seconds") if d else None


def safe_url(u: Any) -> Optional[str]:
    """Solo enlaces http(s): un «javascript:» o «data:» de una fuente no llega al sitio, al correo ni al CSV."""
    s = str(u or "").strip()
    return s if re.match(r"^https?://[^\s<>\"']+$", s, re.I) else None


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
                reports.append({"id": it.get("id"), "title": short(it.get("title") or "", 110), "date": iso(it.get("date")),
                                "institution": it.get("institution"), "deps": deps, "url": safe_url(it.get("url"))})
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
            "kind": it.get("kind"), "phase": ph, "from": iso((it.get("valid") or {}).get("from")),
            "until": iso((it.get("valid") or {}).get("until")), "date": iso(it.get("date")), "deps": deps,
            "places": fine[:8], "approx": approx, "url": safe_url(it.get("document")) or safe_url(it.get("url")),
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
            # Todas las instituciones con avisos aquí: la columna «Fuente» del sitio y del correo (antes el correo
            # mostraba solo las del nivel más alto y el sitio todas, y no coincidían).
            "institutionsAll": sorted({i for e in mine for i in [e["institution"], *e["alsoBy"]] if i}),
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
        code = e.get("statusCode")
        out["enfen"] = {"status": e["status"], "code": code, "number": e.get("number"),
                        "issued": e.get("issued"), "next": e.get("nextIssue"), "stale": bool(e.get("stale")),
                        "url": safe_url(e.get("documentUrl")) or safe_url(e.get("url")),
                        # Escalón del sistema de alerta del ENFEN (No activo → Vigilancia → Alerta), para la escala
                        # de la versión C. Sale del código de estado que ya lee el pipeline, no de un cálculo propio.
                        "step": 2 if str(code or "").startswith("alerta") else 1 if str(code or "").startswith("vigilancia")
                        else 0 if code == "no_activo" else None,
                        "phase": "nina" if str(code or "").endswith("_nina") else "nino" if code and code != "no_activo" else None,
                        "summary": re.split(r"(?<=\.)\s", e.get("summary") or "")[0][:300] or None}
        if not e.get("stale"):
            out["outlook"] = [{"region": o.get("region"), "phase": o.get("phase"), "magnitude": o.get("magnitude"),
                               "until": o.get("until"), "quote": o.get("quote")} for o in e.get("outlook") or []]
    inf = e.get("informe") or {}
    if (inf.get("probabilities") and not e.get("stale")
            and (items.get("enfen-probabilities") or {}).get("state") != "vencido"):
        for t in inf["probabilities"]:
            s = t.get("summer") or {}
            ok = {k: v for k, v in s.items() if k in CAT_ES and isinstance(v, (int, float)) and not isinstance(v, bool)
                  and 0 < v <= 100}
            top = sorted(((v, k) for k, v in ok.items()), reverse=True)[:2]
            if top:
                out["probabilities"].append({
                    "region": t.get("region"), "summer": [{"category": k, "label": CAT_ES.get(k, k), "pct": v}
                                                          for v, k in top],
                    # La distribución completa, de frío a cálido (el orden de CAT_ES), y lo que no entra en las dos
                    # primeras: sin esto, «65 % y 30 %» se leía como si el resto fuera imposible.
                    "all": [{"category": k, "label": CAT_ES[k], "pct": ok[k]} for k in CAT_ES if k in ok],
                    "other": max(0, round(sum(ok.values()) - sum(v for v, _ in top), 1)),
                    "informe": inf.get("number"), "page": (t.get("evidence") or {}).get("page"),
                    "url": safe_url(inf.get("url"))})
    if n.get("status"):
        out["noaa"] = {"status": n.get("statusEs") or n["status"], "issued": n.get("issued"),
                       "next": n.get("nextIssue"), "stale": bool(n.get("stale")), "url": safe_url(n.get("url"))}
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
        ref = join_es([f"comunicado oficial N° {e['number']}" if e.get("number") else "comunicado oficial",
                       day(e.get("issued"))]).replace(" y ", ", ", 1)
        txt = f"El ENFEN mantiene «{e['status']}» ({ref})."
        if e["stale"]:
            txt = (f"El último comunicado del ENFEN leído es «{e['status']}»"
                   f"{' (N° ' + str(e['number']) + ')' if e.get('number') else ''}; ya debió salir uno más reciente.")
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
            lvl = (top["level"].lower() if re.match(r"nivel", top["level"] or "", re.I)
                   else f"nivel {top['level'].lower()}" if top["level"] else "sin nivel")
            txt += (f" El aviso más alto es del {top['institution']} ({lvl}): {top['what']} en "
                    f"{join_es([DEP_NAMES[d] for d in top['deps']], 3)}, {w}.")
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
                              f"({join_es(deps, 4)})."})
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


def clean_state(st: Any) -> Optional[dict]:
    """El estado del boletín anterior, tal como se publicó, con los tipos que espera ``diff``. Un archivo anterior roto
    (a mano, a medio escribir o de un esquema viejo) no puede tumbar la edición de hoy: lo que no se entiende se
    descarta y, si no queda nada usable, se toma como si no hubiera anterior (incidencia ``boletin-sin-anterior``)."""
    if not isinstance(st, dict):
        return None
    rk = lambda v: v if isinstance(v, int) and not isinstance(v, bool) and -1 <= v <= 3 else None  # noqa: E731
    deps = {str(k): rk(v) for k, v in (st.get("deps") or {}).items()} if isinstance(st.get("deps"), dict) else {}
    evs = {}
    for k, v in (st.get("events") or {}).items() if isinstance(st.get("events"), dict) else []:
        if isinstance(v, dict):
            evs[str(k)] = {"rank": rk(v.get("rank")) or 0, "phase": str(v.get("phase") or ""),
                           "title": str(v.get("title") or "")}
    en = st.get("enfen") if isinstance(st.get("enfen"), dict) else {}
    out = {"enfen": {"status": en.get("status") if isinstance(en.get("status"), str) else None,
                     "number": en.get("number")},
           "noaa": st.get("noaa") if isinstance(st.get("noaa"), str) else None,
           "escenario": st.get("escenario"), "deps": {k: v for k, v in deps.items() if v is not None}, "events": evs}
    return out if out["deps"] or out["events"] or out["enfen"]["status"] else None


def diff(prev: Optional[dict], cur: dict, doc: dict) -> list[dict]:
    """Lo que cambió entre dos estados, cada cambio con su regla: «inmediata» (se avisa al momento) o «resumen»
    (va en el resumen diario). Sin estado anterior: un solo cambio «inicial»."""
    if not prev:
        return [{"rule": "inicial", "tier": "inmediata", "text": "Primer boletín: estado actual completo."}]
    out = []
    pe, ce = prev.get("enfen") or {}, cur["enfen"]
    if ce.get("status") and pe.get("status") and ce["status"] != pe["status"]:
        out.append({"rule": "enfen-estado", "tier": "inmediata", "deps": [],
                    "text": f"El ENFEN cambió su estado: de «{pe['status']}» a «{ce['status']}»"
                            + (f" (comunicado N° {ce['number']})." if ce.get("number") else ".")})
    elif ce.get("number") and ce.get("number") != pe.get("number"):
        out.append({"rule": "enfen-comunicado", "tier": "resumen", "deps": [],
                    "text": f"Nuevo comunicado oficial del ENFEN N° {ce['number']}: mantiene «{ce['status']}»."})
    if cur.get("noaa") and prev.get("noaa") and cur["noaa"] != prev["noaa"]:
        out.append({"rule": "noaa-estado", "tier": "resumen", "deps": [], "text": f"La NOAA pasó de «{prev['noaa']}» a «{cur['noaa']}»."})
    if cur.get("escenario") and prev.get("escenario") and cur["escenario"] != prev["escenario"]:
        sc = doc.get("scenario") or {}
        out.append({"rule": "escenario-nuevo", "tier": "resumen", "deps": [],
                    "text": f"Nuevo escenario de riesgo del CENEPRED (N° {cur['escenario']}, {month(sc.get('from'))} a {month(sc.get('until'))})."})
    pd = prev.get("deps") or {}
    for s in doc.get("segments") or []:
        a, b = pd.get(s["code"], -1), s["rank"]
        if a == b:
            continue
        up = b > a
        txt = (f"{s['name']} {'sube' if up else 'baja'} de {LEVELS[a][1].lower()} a {LEVELS[b][1].lower()}"
               + (f": {join_es(s['hazards'][:3])}" if up and s["hazards"] else "") + ".")
        out.append({"rule": "departamento-sube" if up else "departamento-baja", "dep": s["code"], "deps": [s["code"]],
                    "tier": "inmediata" if up and b >= 2 else "resumen", "rank": b, "text": txt})
    pev = prev.get("events") or {}
    for e in doc.get("events") or []:
        old = pev.get(e["key"])
        place = join_es([DEP_NAMES[d] for d in e["deps"][:3]]) + (" y más" if len(e["deps"]) > 3 else "")
        if e["phase"] == "cancelado":
            if old and old.get("phase") != "cancelado":
                out.append({"rule": "aviso-cancelado", "tier": "inmediata" if old.get("rank", 0) >= 2 else "resumen",
                            "deps": e["deps"],
                            "text": f"Cancelado: {e['title']} ({e['institution']})."})
            continue
        if old is None:
            out.append({"rule": "aviso-nuevo", "tier": "inmediata" if e["rank"] >= 2 else "resumen", "rank": e["rank"],
                        "deps": e["deps"],
                        "text": f"Nuevo aviso {e['level'] or 'sin nivel'} de {e['institution']}: {e['what']} en {place}"
                                + (f", desde {when(e['from'])}" if e["phase"] == "proxima" and e["from"] else
                                   f", hasta {when(e['until'])}" if e["until"] else "") + "."})
        elif e["rank"] > old.get("rank", 0):
            out.append({"rule": "aviso-sube", "tier": "inmediata" if e["rank"] >= 2 else "resumen", "rank": e["rank"],
                        "deps": e["deps"],
                        "text": f"Sube a {e['level']}: {e['title']} ({e['institution']})."})
        elif old.get("phase") == "proxima" and e["phase"] in ("vigente", "en-curso"):
            # El aviso esperado ya rige: cambia el «cuándo» del departamento aunque el nivel sea el mismo.
            out.append({"rule": "aviso-empieza", "tier": "inmediata" if e["rank"] >= 2 else "resumen", "rank": e["rank"],
                        "deps": e["deps"],
                        "text": f"Ya rige: {e['title']} ({e['institution']})"
                                + (f", hasta {when(e['until'])}" if e["until"] else "") + "."})
    order = {"inmediata": 0, "resumen": 1}
    out.sort(key=lambda c: (order.get(c["tier"], 2), -c.get("rank", 0)))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Lectura rápida: una frase, qué hacer según el color y cuándo
# ---------------------------------------------------------------------------------------------------------------
#: Qué esperar y qué hacer con cada color, como piden las guías de avisos basados en impactos (OMM, 2021; la matriz de
#: avisos de la Met Office; los niveles de Meteoalarm): el color solo no le dice a nadie qué hacer. Son pautas generales
#: tomadas de las recomendaciones del INDECI ante lluvias intensas y de la escala de colores de los avisos del SENAMHI;
#: no son una alerta propia ni reemplazan lo que diga la autoridad local.
GUIDANCE = [
    {"rank": 3, "label": "Rojo", "expect": "Peligro alto: lluvias, huaicos, inundaciones u oleaje con daños probables a "
                                           "viviendas, vías y servicios.",
     "do": "Siga las indicaciones de su municipalidad y del INDECI. Aléjese de quebradas, cauces y riberas, y tenga a "
           "mano su mochila de emergencia y su ruta de evacuación."},
    {"rank": 2, "label": "Naranja", "expect": "Peligro: eventos que pueden causar daños y cortar vías o servicios.",
     "do": "Prepárese: limpie techos y desagües, ubique las zonas seguras de su barrio y revise los avisos del SENAMHI "
           "y del INDECI."},
    {"rank": 1, "label": "Amarillo", "expect": "Eventos posibles, con daños localizados.",
     "do": "Esté atento a los avisos y a si suben de nivel."},
    {"rank": -1, "label": "Sin avisos", "expect": "Ninguna institución tiene un aviso de El Niño vigente o próximo.",
     "do": "No quiere decir que no haya riesgo: siga los comunicados del ENFEN y del SENAMHI."},
]
GUIDANCE_SOURCE = ("Pautas generales basadas en las recomendaciones del INDECI ante lluvias intensas y en la escala de "
                   "colores de los avisos del SENAMHI. Manda siempre lo que diga la autoridad local.")
#: Ventanas de la línea de tiempo, en horas desde el corte.
WINDOWS = [("ahora", "Ahora", None, None), ("24h", "Próximas 24 h", 0, 24), ("72h", "De 24 a 72 h", 24, 72),
           ("despues", "Más adelante", 72, None)]


def timeline(evs: list[dict], now: datetime) -> list[dict]:
    """Qué departamentos tienen avisos que rigen ahora o que empiezan en 24 h, en 72 h o después (con el nivel más
    alto de cada uno en esa ventana). Solo ordena lo que dicen los avisos: no pronostica nada."""
    out = []
    for wid, label, a, b in WINDOWS:
        best: dict[str, int] = {}
        for e in evs:
            if e["phase"] not in ACTIVE:
                continue
            if wid == "ahora":
                hit = e["phase"] != "proxima"
            else:
                t = _dt(e["from"])
                h = (t - now).total_seconds() / 3600 if t else None
                hit = e["phase"] == "proxima" and h is not None and h >= a and (b is None or h < b)
            if hit:
                for d in e["deps"]:
                    best[d] = max(best.get(d, -1), e["rank"])
        deps = sorted(best.items(), key=lambda kv: (-kv[1], DEP_NAMES[kv[0]]))
        out.append({"id": wid, "label": label,
                    "deps": [{"code": d, "name": DEP_NAMES[d], "rank": r, "color": LEVELS[r][0]} for d, r in deps]})
    return out


def summary_line(enso: dict, segs: list[dict], counts: dict) -> str:
    """El boletín en una frase: cuántos departamentos en cada color, por qué y en qué estado está el ENFEN."""
    present = [k for k in ("rojo", "naranja", "amarillo") if counts[k]]
    parts = [f"{counts[k]} en {k}" for k in present]
    if parts:
        parts[0] = f"{counts[present[0]]} {'departamento' if counts[present[0]] == 1 else 'departamentos'} en {present[0]}"
    hz: dict[str, int] = {}
    for s in segs:
        if s["rank"] >= 1:
            for h in s["hazards"]:
                hz[h] = hz.get(h, 0) + 1
    top_hz = [h for h, _ in sorted(hz.items(), key=lambda kv: -kv[1])[:3]]
    if parts:
        txt = f"{join_es(parts)} con avisos oficiales" + (f" por {join_es(top_hz)}" if top_hz else "") + "."
    else:
        txt = "Ningún departamento tiene avisos oficiales de lluvias, huaicos, inundaciones u oleaje."
    e = enso.get("enfen")
    if e:
        txt += f" El ENFEN {'mantenía' if e['stale'] else 'mantiene'} el estado «{e['status']}»."
    return txt[0].upper() + txt[1:]


# ---------------------------------------------------------------------------------------------------------------
# Textos para compartir: correo (HTML con estilos en línea y un mapa de mosaicos), WhatsApp y Atom
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
#: Pila de letras del correo: las del sistema primero (se leen mejor en el teléfono) y Arial para Outlook.
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
BRAND = "#0b4f71"
MUTED = "#4a5560"  # 7,4:1 sobre blanco


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def tile_map(segs: list[dict]) -> str:
    """Mosaico fluido: una tabla de 6 columnas al 100 % de un ancho máximo de 300 px, así cabe en una pantalla de
    320 px sin desbordar. «Solo se espera» va con una marca de texto (·), no con un degradado: Gmail y Outlook
    quitan ``background-image`` con degradados y el rayado desaparecía."""
    by = {s["code"]: s for s in segs}
    rows = []
    for r in range(8):
        cells = []
        for c in range(6):
            code = next((k for k, v in TILES.items() if v == (r, c)), None)
            if not code or code not in by:
                cells.append('<td width="16%" style="width:16.66%;height:30px;padding:0;font-size:0;line-height:0">&nbsp;</td>')
                continue
            s = by[code]
            bg, ink = LEVELS[s["rank"]][2], INK[s["rank"]]
            soon = s["rank"] >= 0 and not s["now"]
            border = f"2px dashed {ink}" if soon else "2px solid #ffffff"
            cells.append(f'<td width="16%" bgcolor="{bg}" title="{_e(s["name"])}: {_e(s["label"])}{" (se espera)" if soon else ""}" '
                         f'style="width:16.66%;height:30px;padding:0;background-color:{bg};color:{ink};'
                         f'font:700 11px/30px {FONT};text-align:center;border:{border}">'
                         f'{ABBR[code]}{"&middot;" if soon else ""}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return ('<table role="img" aria-label="Mapa de cuadros de los departamentos del Perú, norte arriba y costa a la '
            'izquierda, cada uno con el color del nivel más alto de sus avisos" width="100%" cellspacing="0" '
            f'cellpadding="0" style="border-collapse:collapse;max-width:300px;margin:0 auto">{"".join(rows)}</table>')


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


def _chip(r: int) -> str:
    return (f'<span style="display:inline-block;padding:1px 8px;border-radius:9px;background-color:{LEVELS[r][2]};'
            f'color:{INK[r]};font:700 12px/18px {FONT};white-space:nowrap">{LEVELS[r][1]}</span>')


def _p(text: str, size: int = 15, color: str = "#1f1f1f", margin: str = "0 0 10px", weight: int = 400) -> str:
    return f'<p style="margin:{margin};font:{weight} {size}px/1.5 {FONT};color:{color}">{text}</p>'


def unsubscribe_footer(site: str) -> str:
    """Pie de la baja, el que ve quien abre «Ver como correo» en el sitio. n8n lo reemplaza, para cada persona, por su
    enlace de baja y de preferencias (``n8n/lib/boletin.js``)."""
    return _p(f'¿Recibió este correo de otra persona? <a href="{_e(site)}#/boletin?suscribir" style="color:{BRAND}">'
              f'Suscríbase al boletín</a>. Cada correo trae su enlace para darse de baja o elegir departamentos.',
              12, MUTED, "8px 0 0")


def email_html(doc: dict, site: str) -> str:
    """Correo del boletín: una columna fluida de 600 px como máximo (se lee igual en 320 px que en una pantalla
    grande sin media queries, que Gmail quita en cuentas que no son de Google), tablas para la estructura (Outlook
    para Windows usa el motor de Word), colores con ``bgcolor`` además de CSS, contraste AA y modo oscuro declarado.
    Los bloques ``<!--cambios-->`` y ``<!--baja-->`` los reemplaza n8n para cada envío."""
    segs, c = doc["segments"], doc["counts"]
    top = [s for s in segs if s["rank"] >= 0][:TOP]
    site = site.rstrip("/") + "/"
    link = f"{site}#/boletin"
    counters = "".join(
        f'<td width="20%" align="center" bgcolor="{LEVELS[r][2]}" style="width:20%;padding:6px 2px;background-color:'
        f'{LEVELS[r][2]};color:{INK[r]};border:3px solid #ffffff;border-radius:8px">'
        f'<div style="font:700 22px/1.1 {FONT};color:{INK[r]}">{c[k]}</div>'
        f'<div style="font:600 12px/1.2 {FONT};color:{INK[r]}">{_e(lbl)}</div></td>'
        for r, k, lbl in ((3, "rojo", "en rojo"), (2, "naranja", "en naranja"), (1, "amarillo", "en amarillo"),
                          (0, "sinNivel", "sin nivel"), (-1, "verde", "sin avisos")))
    lines = "".join(_p(f'<strong>{_e(x["title"])}.</strong> {_e(x["text"])}', 15) for x in doc["headline"])
    legend = "".join(f'<div class="tx" style="font:12px/1.45 {FONT};color:#333333;margin:0 0 3px"><span style="display:inline-block;'
                     f'width:10px;height:10px;background-color:{LEVELS[r][2]};margin-right:6px"></span>{_e(t)}</div>'
                     for r, t in LEGEND) + (f'<div class="tx" style="font:12px/1.45 {FONT};color:#333333">Con «&middot;» y borde '
                                            f'punteado: ese nivel solo se espera (aviso próximo).</div>')
    events = {e["key"]: e for e in doc.get("events") or []}

    def card(s: dict) -> str:
        sc = s["scenario"]
        evs = [events[k] for k in s["events"] if k in events]
        risk = (f'{sc["muyAlto"]} muy alto · {sc["alto"]} alto de {sc["districts"]} distritos' if sc["districts"]
                else "sin escenario")
        src = ", ".join(s.get("institutionsAll") or s["institutions"]) or "—"
        first = next((e for e in evs if e.get("url")), None)
        src_html = (f'<a href="{_e(first["url"])}" style="color:{BRAND}">{_e(src)}</a>' if first else _e(src))
        return (f'<tr><td style="padding:10px 0;border-top:1px solid #e3e7eb">'
                f'<div class="tx" style="font:700 15px/1.4 {FONT};color:#1f1f1f">{s["position"]}. {_e(s["name"])} &nbsp;{_chip(s["rank"])}</div>'
                f'<div class="tx" style="font:14px/1.45 {FONT};color:#1f1f1f">{_e(join_es(s["hazards"][:3]) or "—")}'
                f'{" · " + _e(join_es(s["places"][:4])) if s["places"] else ""}</div>'
                f'<div class="tx" style="font:13px/1.45 {FONT};color:{MUTED}"><strong>Cuándo:</strong> {_e(_when_seg(s))} · '
                f'<strong>Fuente:</strong> {src_html} ({len(evs)} {"aviso" if len(evs) == 1 else "avisos"})<br>'
                f'<strong>Riesgo CENEPRED:</strong> {_e(risk)} · <strong>Daños 72 h:</strong> {s["reports"]}</div></td></tr>')

    cards = "".join(card(s) for s in top) or (
        f'<tr><td class="tx" style="padding:8px 0;font:14px {FONT}">Ningún departamento tiene avisos vigentes o próximos '
        'relacionados con El Niño.</td></tr>')
    more = len([s for s in segs if s["rank"] >= 0]) - len(top)
    green = [s["name"] for s in segs if s["rank"] < 0]
    wa = "https://wa.me/?text=" + urllib.parse.quote(doc["whatsapp"])
    changes = doc.get("changes") or []
    ch = "".join(f'<li style="margin:0 0 4px">{_e(x["text"])}</li>' for x in changes[:8])
    ch_block = (f'<div class="warn" style="background-color:#fff4e0;border-left:4px solid #b85c00;padding:10px 12px;margin:0 0 14px">'
                f'<div class="tx" style="font:700 14px {FONT};color:#1f1f1f;margin:0 0 4px">Qué cambió en esta edición</div>'
                f'<ul style="margin:0;padding-left:18px;font:14px/1.45 {FONT};color:#1f1f1f">{ch}</ul></div>'
                if ch and changes[0]["rule"] != "inicial" else "")
    e = (doc.get("enso") or {}).get("enfen")
    pr = next((p for p in (doc.get("enso") or {}).get("probabilities") or [] if p["region"] == "nino12"), None)
    bars = ""
    if pr:
        bars = "".join(
            f'<tr><td class="tx" style="font:13px/1.3 {FONT};color:#1f1f1f;padding:2px 8px 2px 0;white-space:nowrap">{_e(x["label"])}</td>'
            f'<td width="100%" style="padding:2px 0"><table role="presentation" width="100%" cellspacing="0" cellpadding="0">'
            f'<tr><td width="{max(1, int(x["pct"]))}%" bgcolor="#c8261b" style="height:10px;background-color:#c8261b;'
            f'font-size:0;line-height:0">&nbsp;</td><td bgcolor="#e3e7eb" style="background-color:#e3e7eb;font-size:0;'
            f'line-height:0">&nbsp;</td></tr></table></td><td style="font:700 13px {FONT};padding-left:8px;'
            f'white-space:nowrap" class="tx">{x["pct"]} %</td></tr>' for x in pr["summer"])
        bars = (f'<div class="tx" style="font:600 13px/1.4 {FONT};color:#1f1f1f;margin:4px 0 4px">Probabilidad para el verano según '
                f'el ENFEN (costa del Perú, informe técnico N° {_e(pr["informe"])})</div>'
                f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0">{bars}</table>'
                + (_p(f'Otras categorías: {pr["other"]:g} %.', 12, MUTED, "2px 0 0") if pr.get("other") else ""))
    enfen = (f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 14px">'
             f'<tr><td class="soft" bgcolor="#eef3f6" style="background-color:#eef3f6;padding:10px 12px;border-radius:6px">'
             f'<div class="tx" style="font:600 12px {FONT};color:{MUTED};letter-spacing:.04em">ESTADO OFICIAL DEL ENFEN</div>'
             f'<div class="tx" style="font:700 17px/1.35 {FONT};color:#1f1f1f">{_e(e["status"])}</div>'
             f'<div class="tx" style="font:13px/1.4 {FONT};color:{MUTED}">'
             + (f'<a href="{_e(e["url"])}" style="color:{BRAND}">Comunicado oficial N° {_e(e["number"])}</a>' if e.get("url") and e.get("number")
                else f'Comunicado oficial N° {_e(e["number"])}' if e.get("number") else "Comunicado oficial")
             + (f', {_e(day(e["issued"]))}' if e.get("issued") else "")
             + (f' · próximo: {_e(day(e["next"]))}' if e.get("next") else "")
             + f'</div>{bars}</td></tr></table>') if e else ""
    present = {s["rank"] for s in segs}
    guide = "".join(
        f'<tr><td valign="top" style="padding:4px 8px 4px 0;white-space:nowrap">{_chip(g["rank"])}</td>'
        f'<td class="tx" style="padding:4px 0;font:13px/1.45 {FONT};color:#1f1f1f"><strong>{_e(g["do"])}</strong> {_e(g["expect"])}</td></tr>'
        for g in GUIDANCE if g["rank"] in present and g["rank"] >= 1)
    guide_block = (f'<h2 style="font:700 16px/1.3 {FONT};color:#1f1f1f;margin:18px 0 6px">Qué hacer según el color</h2>'
                   f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0">{guide}</table>'
                   + _p(_e(GUIDANCE_SOURCE), 12, MUTED, "4px 0 0")) if guide else ""
    pre = _e(doc.get("summary") or (doc["headline"][1]["text"] if len(doc["headline"]) > 1 else ""))
    button = (f'<table role="presentation" cellspacing="0" cellpadding="0" style="margin:16px 0 0"><tr>'
              f'<td bgcolor="{BRAND}" style="border-radius:6px;background-color:{BRAND}">'
              f'<a href="{_e(link)}" style="display:inline-block;padding:12px 18px;font:700 15px {FONT};color:#ffffff;'
              f'text-decoration:none;border-radius:6px">Ver el boletín completo</a></td></tr></table>')
    return f"""<!doctype html>
<html lang="es" xmlns="http://www.w3.org/1999/xhtml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge"><meta name="x-apple-disable-message-reformatting">
<meta name="format-detection" content="telephone=no,address=no,email=no,date=no">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>{_e(doc["email"]["subject"])}</title>
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
<style>
:root{{color-scheme:light dark;supported-color-schemes:light dark}}
body{{margin:0!important;padding:0!important;width:100%!important;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}}
table{{border-collapse:collapse;mso-table-lspace:0;mso-table-rspace:0}}
a{{color:{BRAND}}}
@media (max-width:480px){{.pad{{padding-left:14px!important;padding-right:14px!important}}.h1{{font-size:19px!important}}}}
@media (prefers-color-scheme:dark){{.bg{{background-color:#10161b!important}}.card{{background-color:#1a2229!important}}
.card p,.card li,.card h2,.card .tx{{color:#e8edf1!important}}.card a{{color:#8cc8ea!important}}
.soft{{background-color:#24303a!important}}.warn{{background-color:#3a2a10!important}}}}
[data-ogsc] .card p,[data-ogsc] .card li,[data-ogsc] .card h2,[data-ogsc] .card .tx{{color:#e8edf1!important}}
[data-ogsc] .soft{{background-color:#24303a!important}}[data-ogsc] .warn{{background-color:#3a2a10!important}}
</style></head>
<body class="bg" style="margin:0;padding:0;background-color:#f2f4f6">
<div style="display:none;max-height:0;max-width:0;overflow:hidden;opacity:0;mso-hide:all;font-size:1px;line-height:1px;color:#f2f4f6">{pre}{"&#847;&zwnj;&nbsp;" * 60}</div>
<div role="article" aria-roledescription="email" aria-label="{_e(doc["email"]["subject"])}" lang="es">
<table role="presentation" class="bg" width="100%" cellspacing="0" cellpadding="0" bgcolor="#f2f4f6" style="background-color:#f2f4f6"><tr><td align="center" style="padding:12px 8px">
<!--[if mso]><table role="presentation" width="600" cellspacing="0" cellpadding="0"><tr><td><![endif]-->
<table role="presentation" class="card" width="100%" cellspacing="0" cellpadding="0" bgcolor="#ffffff" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:8px">
<tr><td class="pad" bgcolor="{BRAND}" style="background-color:{BRAND};padding:16px 20px;border-radius:8px 8px 0 0">
<div class="h1" style="font:700 21px/1.3 {FONT};color:#ffffff">Boletín de eventos El Niño · Perú</div>
<div style="font:14px/1.4 {FONT};color:#ffffff">Edición N° {doc["edition"]} · corte {_e(when(doc["cutoff"]))} (hora de Lima)</div></td></tr>
<tr><td class="pad" style="padding:16px 20px">
<!--cambios-->{ch_block}<!--/cambios-->
{_p("<strong>En una frase:</strong> " + _e(doc.get("summary") or ""), 16, "#1f1f1f", "0 0 14px") if doc.get("summary") else ""}
<table role="presentation" class="lv" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 6px;table-layout:fixed"><tr>{counters}</tr></table>
{_p("Departamentos según el nivel más alto de sus avisos oficiales vigentes o próximos (de 25).", 12, MUTED, "0 0 14px")}
{enfen}
<h2 style="font:700 16px/1.3 {FONT};color:#1f1f1f;margin:4px 0 8px">Mapa del Perú por departamento</h2>
{tile_map(segs)}
<div style="margin:10px 0 14px">{legend}</div>
<h2 style="font:700 16px/1.3 {FONT};color:#1f1f1f;margin:14px 0 8px">Qué se viene</h2>
{lines}
{guide_block}
<h2 style="font:700 16px/1.3 {FONT};color:#1f1f1f;margin:18px 0 4px">Los {len(top) or ""} departamentos más críticos</h2>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0">{cards}</table>
{_p(f"Y {more} departamentos más con avisos: véalos todos en el sitio.", 13, MUTED, "6px 0 0") if more > 0 else ""}
{_p("Sin avisos relacionados con El Niño: " + _e(join_es(green)) + ".", 13, MUTED, "6px 0 0") if green else ""}
{button}
{_p(f'<a href="{_e(wa)}" style="color:{BRAND}">Compartir el resumen por WhatsApp</a>', 14, "#1f1f1f", "12px 0 0")}
<p style="margin:18px 0 0;font:12px/1.5 {FONT};color:{MUTED}"><strong>Este boletín no es una alerta oficial.</strong> Los niveles son los de cada institución (SENAMHI, INDECI, DHN, IGP, ANA); las probabilidades, las del ENFEN. Ante una emergencia, siga al INDECI, al SENAMHI y a su municipalidad. Orden de la lista: {_e("; ".join(ORDER))}.</p>
<p style="margin:8px 0 0;font:12px/1.5 {FONT};color:{MUTED}">Observatorio ENSO Perú · <a href="{_e(site)}" style="color:{BRAND}">{_e(site)}</a> · datos abiertos: <a href="{_e(site)}data/boletin.json" style="color:{BRAND}">boletin.json</a></p>
<!--baja-->{unsubscribe_footer(site)}<!--/baja-->
</td></tr></table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table></div></body></html>
"""


def whatsapp_text(doc: dict, site: str) -> str:
    c = doc["counts"]
    rated = [s for s in doc["segments"] if s["rank"] >= 1]
    emo = {3: "🔴", 2: "🟠", 1: "🟡"}
    lines = [f"*Boletín El Niño · Perú* (N° {doc['edition']}, {when(doc['cutoff'])}, hora de Lima)"]
    e = (doc["enso"] or {}).get("enfen")
    if e:
        lines.append(f"ENFEN: {e['status']}" + (f" (comunicado N° {e['number']})." if e.get("number") else "."))
    lines.append(f"Departamentos: {c['rojo']} en rojo, {c['naranja']} en naranja, {c['amarillo']} en amarillo.")
    for s in rated[:5]:
        lines.append(f"{emo[s['rank']]} {s['name']}: {join_es(s['hazards'][:2])} · {_when_seg(s).lower()}")
    if len(rated) > 5:
        lines.append(f"… y {len(rated) - 5} departamentos más con avisos.")
    lines.append("No es una alerta oficial: siga al SENAMHI, al INDECI y a su municipalidad.")
    lines.append(f"Detalle: {site.rstrip('/')}/#/boletin")
    return "\n".join(lines)


def subject(doc: dict) -> str:
    c = doc["counts"]
    worst = next((s for s in doc["segments"] if s["rank"] >= 1), None)
    head = f"{c['rojo']} en rojo, {c['naranja']} en naranja" if (c["rojo"] or c["naranja"]) else "sin avisos rojos ni naranjas"
    out = (f"Boletín El Niño N° {doc['edition']}: {head}"
           + (f" · {worst['name']} {worst['label'].lower()}" if worst and worst["rank"] >= 2 else ""))
    return re.sub(r"[\r\n]+", " ", out)  # una cabecera nunca lleva saltos de línea


def email_text(doc: dict, site: str) -> str:
    out = [f"Boletín de eventos El Niño · Perú — Edición N° {doc['edition']}, corte {when(doc['cutoff'])} (hora de Lima)", ""]
    if doc.get("summary"):
        out += [f"En una frase: {doc['summary']}", ""]
    ch = [x for x in doc.get("changes") or [] if x["rule"] != "inicial"]
    if ch:
        out += ["Qué cambió:"] + [f"- {x['text']}" for x in ch[:8]] + [""]
    out += [f"{x['title']}: {x['text']}" for x in doc["headline"]] + ["", "Los más críticos:"]
    for s in [s for s in doc["segments"] if s["rank"] >= 0][:TOP]:
        out.append(f"{s['position']}. {s['name']} — {s['label']} — {join_es(s['hazards'][:3])} — {_when_seg(s)}")
    out += ["", f"Detalle: {site.rstrip('/')}/#/boletin",
            "Este boletín no es una alerta oficial: los niveles son los de cada institución."]
    return "\n".join(out)


def atom_feed(doc: dict, site: str) -> str:
    """Las últimas ediciones como canal Atom (RFC 4287), para lectores de noticias, Slack, Teams o IFTTT: la vía de
    suscripción que no pide ningún dato personal."""
    site = site.rstrip("/") + "/"
    link = f"{site}#/boletin"
    x = lambda v: html.escape(str(v or ""), quote=False)  # noqa: E731
    entries = []
    for r in doc.get("recent") or []:
        ch = [c for c in r.get("changes") or [] if isinstance(c, dict) and c.get("text")]
        title = (doc["email"]["subject"] if r["edition"] == doc["edition"] else
                 f"Boletín El Niño N° {r['edition']}: {ch[0]['text'] if ch else 'sin cambios'}")
        body = "".join(f"<li>{x(c['text'])}</li>" for c in ch) or "<li>Sin cambios.</li>"
        entries.append(
            f"<entry><id>{x(site)}boletin/{r['edition']}</id><title>{x(title)}</title><updated>{x(iso(r.get('at')) or doc['cutoff'])}</updated>"
            f'<link rel="alternate" type="text/html" href="{x(link)}"/>'
            f'<content type="html">{x("<ul>" + body + "</ul>")}</content></entry>')
    return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="es">'
            f"<id>{x(site)}boletin</id><title>Boletín de eventos El Niño · Perú</title>"
            f'<subtitle>Una edición nueva cada vez que cambia algo en los avisos oficiales, el ENFEN o el CENEPRED.</subtitle>'
            f"<updated>{x(iso(doc.get('editionAt')) or doc['cutoff'])}</updated>"
            f'<link rel="alternate" type="text/html" href="{x(link)}"/><link rel="self" href="{x(site)}data/boletin.xml"/>'
            f"<author><name>Observatorio ENSO Perú</name></author>{''.join(entries)}</feed>\n")


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
    group = next((g for g in (feed or {}).get("groups") or [] if isinstance(g, dict) and g.get("id") == "alertas"), {}) or {}
    src = [x for x in group.get("sources") or [] if isinstance(x, dict)]
    doc: dict[str, Any] = {
        "schema": SCHEMA, "cutoff": now.isoformat(timespec="seconds"), "feedAt": (feed or {}).get("generatedAt"),
        "sources": {"ok": sum(1 for s in src if s.get("ok")), "total": len(src),
                    "failed": sorted({str(s.get("name") or s.get("id")) for s in src if not s.get("ok") and (s.get("name") or s.get("id"))})[:10]},
        "enso": enso, "scenario": scen, "counts": counts, "segments": segs, "events": evs, "reports": reports[:30],
        "top": TOP, "legend": [{"rank": r, "color": LEVELS[r][0], "label": LEVELS[r][1], "text": t} for r, t in LEGEND],
        "order": ORDER, "rules": RULES, "guidance": GUIDANCE, "guidanceSource": GUIDANCE_SOURCE,
        "timeline": timeline(evs, now),
    }
    doc["summary"] = summary_line(enso, segs, counts)
    doc["headline"] = headline(enso, segs, evs, reports, scen)
    st = state(doc)
    prev_state = (clean_state(previous.get("state")) if isinstance(previous, dict) and previous.get("schema") == SCHEMA
                  else None)
    try:
        prev_ed = int((previous or {}).get("edition") or 0) if prev_state else 0
    except (TypeError, ValueError):
        prev_state, prev_ed = None, 0
    changes = diff(prev_state, st, doc)
    if prev_state and not changes:
        # Nada cambió: la misma edición, con su fecha y sus cambios.
        doc["edition"] = prev_ed
        doc["editionAt"] = iso(previous.get("editionAt")) or iso(previous.get("cutoff")) or doc["cutoff"]
        doc["changes"] = [c for c in previous.get("changes") or [] if isinstance(c, dict) and c.get("text")]
    else:
        doc["edition"] = prev_ed + 1
        doc["editionAt"] = doc["cutoff"]
        doc["changes"] = changes
    recent = ([r for r in ((previous or {}).get("recent") or []) if isinstance(r, dict) and isinstance(r.get("edition"), int)
               and r["edition"] < doc["edition"]] if prev_state else [])
    recent.insert(0, {"edition": doc["edition"], "at": doc["editionAt"], "changes": doc["changes"]})
    doc["recent"] = recent[:KEEP_RECENT]
    doc["alert"] = any(c.get("tier") == "inmediata" for c in doc["changes"])
    doc["state"] = st
    doc["stateHash"] = hashlib.sha256(json.dumps(st, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    doc["whatsapp"] = whatsapp_text(doc, site)
    doc["email"] = {"subject": subject(doc), "text": email_text(doc, site)}
    doc["email"]["html"] = email_html(doc, site)
    return doc


def _cell(v: Any) -> str:
    """Texto de una celda sin fórmulas al abrir en Excel, LibreOffice o Power BI (inyección CSV, OWASP): un valor que
    empieza con =, +, -, @, tabulador o retorno de carro va precedido de un apóstrofo."""
    s = str(v if v is not None else "")
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def csv_segments(doc: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["edicion", "corte", "posicion", "ubigeo", "departamento", "nivel", "rige_ahora", "desde", "hasta",
                "peligros", "lugares", "instituciones", "avisos_en_ese_nivel", "distritos_riesgo_muy_alto",
                "distritos_riesgo_alto", "reportes_danos_72h"])
    for s in doc["segments"]:
        w.writerow([doc["edition"], doc["cutoff"], s["position"], s["code"], s["name"], s["label"], int(s["now"]),
                    s.get("since") or "", s.get("until") or "", _cell("; ".join(s["hazards"])),
                    _cell("; ".join(s["places"])), _cell("; ".join(s["institutions"])), s["eventsAtTop"],
                    s["scenario"]["muyAlto"], s["scenario"]["alto"], s["reports"]])
    return buf.getvalue()


def csv_events(doc: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["edicion", "clave", "institucion", "tambien_difunde", "nivel", "rango", "momento", "desde", "hasta",
                "peligros", "departamentos", "lugares", "titulo", "enlace"])
    for e in doc["events"]:
        w.writerow([doc["edition"], _cell(e["key"]), _cell(e["institution"]), _cell("; ".join(e["alsoBy"])),
                    _cell(e["level"] or "Sin nivel"), e["rank"], e["phase"], e["from"] or "", e["until"] or "",
                    _cell(e["what"]), "; ".join(DEP_NAMES[d] for d in e["deps"]), _cell("; ".join(e["places"])),
                    _cell(e["title"]), e["url"] or ""])
    return buf.getvalue()
