"""Lectores de la segunda ronda de fuentes: COEN, decretos, prensa, evaluaciones, inventarios, IFRC y GLOF.

Estas fuentes no son una serie homogénea como DesInventar o el SINPAD: cuentan lo mismo desde otro lado.
Por eso cada lector devuelve *candidatos* (filas completas de ``registro.make`` con algunos campos privados que
empiezan con ``_``), y ``enlace.link`` decide con cada uno si corrobora una fila que ya está (y entonces suma su
enlace, y sus cifras de daños si la fila no las tiene) o si es un evento que ninguna otra fuente registró.

* **COEN (INDECI)**: cada entrada del listado de reportes preliminares y complementarios es una emergencia, con
  el título de su último reporte. El título da el peligro, el distrito y el departamento; la dirección, la
  fecha del primer reporte. El PDF (si se bajó) da la fecha de ocurrencia, la descripción, el código SINPAD, el
  cuadro de daños y, a veces, el decreto de estado de emergencia que ya regía en el distrito.
* **Decretos supremos de estado de emergencia** (El Peruano): no son eventos sino declaratorias, y se leen
  aparte (``decrees``): «por peligro inminente» es prevención; «por impacto de daños», respuesta.
* **Prensa**: titular, fecha y extracto de notas de medios regionales y nacionales. El lugar lo pone el mismo
  ubicador de noticias del observatorio (``enso.geo.locate_item``) y el peligro, el texto.
* **Periódicos antiguos digitalizados** (``hemeroteca``): páginas de Chronicling America (Biblioteca del Congreso
  de EE. UU., 1836-1963) que cuentan inundaciones, lluvias, huaicos o aludes en el Perú, con el mismo ubicador.
* **Evaluaciones de peligros** (INGEMMET, IGP): informes técnicos de un lugar. Son evidencia de que el peligro
  se conocía, no eventos (``evaluations``).
* **Inventario de peligros del INGEMMET con fecha** (``inventory_dated``): cuántos puntos de cada grupo de peligro
  había inventariados en cada distrito y desde qué año. También evidencia, no eventos.
* **Llamamientos de la Cruz Roja** (IFRC GO, ``appeals``): solo los metadatos de cada llamamiento del Perú.
* **Base mundial de desbordes de lagunas glaciares** (``glof``): aluviones por desborde de lagunas desde 1702, con
  la laguna, el mecanismo y los fallecidos; se ubican por las coordenadas de la laguna. Los que desató un sismo
  no entran.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import date
from types import SimpleNamespace
from typing import Iterator, Optional

from . import esquema as E
from .registro import make

COEN_PAGE = "https://portal.indeci.gob.pe/informe/reportes-preliminares-complementarios-emergencias/"
COEN_LICENSE = "Reportes del COEN (INDECI), información pública (Ley N° 27806)"
ELPERUANO_LICENSE = "Normas legales del diario oficial El Peruano, dominio público (D. Leg. 822, art. 9)"
PRESS_LICENSE = ("Titular, fecha y extracto de hasta 200 caracteres con enlace a la nota (cita, D. Leg. 822, "
                 "art. 44); el texto completo es del medio")
#: Extracto de prensa que se publica, como mucho (caracteres).
PRESS_EXCERPT = 200

# ---------------------------------------------------------------------------
# Peligros con el vocabulario del INDECI
# ---------------------------------------------------------------------------
#: Nombres del peligro en los títulos del COEN que no están, tal cual, en el portal del SINPAD (singulares,
#: erratas) → DangerType. Lo que no está aquí se busca en ``fuentes.SINPAD_API_TYPES``.
COEN_TYPES = {
    "granizada": "Granizada", "helada": "Helada/Friaje", "tormenta electrica": "Tormenta electrica",
    "derrumbe de cerro": "Deslizamiento", "derrumbe de roca": "Deslizamiento", "derrumbe de cerros": "Deslizamiento",
    "deslizamientos": "Deslizamiento", "deslizamiento de tierra": "Deslizamiento",
    "inundacion por desborde de canal": "Inundacion", "inundacion por deborde de canales": "Inundacion",
    "inundacion por desborde de lago": "Inundacion", "inundacion por desborde rio": "Inundacion fluvial",
    "inundacion por saturacion de suelo": "Inundacion pluvial",
    "inundacion por saturacion del suelo para drenaje": "Inundacion pluvial",
    "oleajes anomalos": "Oleaje anomalo", "incendio forestal": "Incendio forestal", "huayco": "Huayco/Alud",
    "lluvia intensa": "Lluvias intensas", "precipitaciones intensas": "Lluvias intensas",
}


def indeci_type(name: str) -> tuple[Optional[str], str]:
    """(DangerType, método) de un peligro con el vocabulario del INDECI (SINPAD o COEN), o (None, motivo)."""
    from .fuentes import SINPAD_API_TYPES

    k = E.key(re.sub(r"\s+", " ", name or ""))
    dt = COEN_TYPES.get(k, SINPAD_API_TYPES.get(k, "no"))
    if dt == "no":
        return None, "no climático"
    if dt in ("Epidemia", "Plaga"):
        return None, "sin causa climática"
    return (dt, "fuente") if dt else (None, "sin tipo")


# ---------------------------------------------------------------------------
# COEN: título, dirección y PDF
# ---------------------------------------------------------------------------
_COEN_TITLE = re.compile(
    r"(?:HORAS?|HRS?\.?)\s*(?:\(?\s*(?:REPORTE|INFORME)\s*N[^)]{0,12}\)\s*)?"
    r"(?P<haz>[A-ZÁÉÍÓÚÑÜ][^()]*?)\s+(?:EN\s+)?(?:EL|LA|LOS|LAS)\s+"
    r"(?P<lvl>DISTRITOS?|PROVINCIAS?|DEPARTAMENTOS?)\s+(?:DE\s+)?(?P<place>.+)$", re.I)
_COEN_SLUG = re.compile(r"/emergencias/(?:reporte|informe)-(?P<kind>preliminar|complementario|de-emergencia)?-?"
                        r"n-(?:o-)?(?P<num>\d+)-(?P<d>\d{1,2})-(?P<m>\d{1,2})-(?P<y>20\d\d)(?!\d)")
_COEN_TITLE_DATE = re.compile(r"N[.°º\s]*\s*(?P<num>\d+)\s*[–-]\s*(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>20\d\d)(?!\d)")
_DASH = re.compile(r"\s+[–—-]\s+|\s*[–—]\s*")
_LIST = re.compile(r"\s*,\s*|\s+Y\s+", re.I)


def coen_title(title: str) -> Optional[dict]:
    """Peligro, nivel y lugares del título de un reporte del COEN («… LLUVIAS INTENSAS EN EL DISTRITO DE PÁUCAR –
    PASCO»): {"peligro", "nivel", "lugares": [nombre, …], "departamento"}, o None si no tiene esa forma (boletines,
    sismos con epicentro en el mar)."""
    m = _COEN_TITLE.search(re.sub(r"\s+", " ", title or "").strip())
    if not m:
        return None
    haz = re.sub(r"^\(?(?:REPORTE|INFORME)\s*N[^)]*\)\s*", "", m.group("haz").strip(), flags=re.I)
    parts = [p.strip(" .") for p in _DASH.split(m.group("place")) if p.strip(" .")]
    if len(parts) < 2:
        return None
    lvl = m.group("lvl").lower().rstrip("s")
    places = [n.strip() for n in _LIST.split(parts[0]) if n.strip()]
    return {"peligro": haz, "nivel": lvl, "lugares": places, "provincia": parts[1] if len(parts) > 2 else "",
            "departamento": parts[-1]}


def coen_first_report(url: str, title: str = "") -> Optional[dict]:
    """Número, tipo y fecha del primer reporte de la emergencia (de su dirección), o del último (del título)."""
    # Si la fecha de la dirección no existe o es futura (un año mal escrito, «8-7-2028»), vale la del título.
    for m, first in ((_COEN_SLUG.search(url or ""), True), (_COEN_TITLE_DATE.search(title or ""), False)):
        if not m:
            continue
        try:
            day = date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        except ValueError:
            continue
        if day <= date.today():
            break
    else:
        return None
    kind = (m.groupdict().get("kind") or "").replace("de-emergencia", "informe")
    return {"numero": m.group("num"), "tipo": kind or ("complementario" if "COMPLEMENTARIO" in title.upper() else
                                                       "preliminar" if "PRELIMINAR" in title.upper() else ""),
            "fecha": day.isoformat(), "primero": first}


_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/((?:19|20)\d\d)(?![\d/])")
_SINPAD = re.compile(r"SINPAD\s*(?:N\.?\s*[°º]?|N[°º])?\s*:?\s*(\d{5,7})\b", re.I)
_NO_SINPAD = re.compile(r"no\s+registrad[ao]\s+en\s+el\s+SINPAD", re.I)
_DECREE = re.compile(r"Decreto\s+Supremo\s+N\.?\s*[°º]?\s*(\d{1,3}-(?:19|20)\d\d-PCM)", re.I)
_DECREE_IMMINENT = re.compile(r"peligro\s+inminente", re.I)


def _section(text: str, start: str, end: str) -> str:
    m = re.search(start + r"(.*?)(?=" + end + r"|\Z)", text, re.S | re.I)
    return m.group(1) if m else ""


def coen_pdf(text: str) -> dict:
    """Lo que dice el texto (``pdftotext -layout``) de un reporte del COEN: fecha de ocurrencia, descripción, código
    SINPAD (o que no está registrada), ubicación (departamento, provincia, distrito), cuadro de daños por
    distrito y los decretos de emergencia que menciona."""
    out: dict = {}
    if not text:
        return out
    facts = _section(text, r"1\.\s*HECHOS", r"\n\s*2\.\s*UBICACI")
    m = _DATE.search(facts)
    if m:
        try:
            out["fecha"] = date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass
    desc = []
    for line in facts.splitlines():
        line = _DATE.sub(" ", line)
        line = re.sub(r"\b\d{1,2}:\d{2}\s*(?:horas|hrs?\.?|h)\b|Fecha y hora de|la ocurrencia|Descripci[oó]n", " ", line,
                      flags=re.I)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            desc.append(line)
    if desc:
        out["descripcion"] = re.sub(r"\s+", " ", " ".join(desc)).strip(" :;.,") + "."
    if _NO_SINPAD.search(text):
        out["sinpad"] = None
    else:
        m = _SINPAD.search(text)
        if m:
            out["sinpad"] = m.group(1)
    loc = _section(text, r"2\.\s*UBICACI[OÓ]N:?", r"Distribuci[oó]n:|\n\s*3\.\s*EVALUACI")
    out["ubicacion"] = _location_rows(loc)
    if not out.get("sinpad") and out.get("sinpad", "") is not None:
        m = re.search(r"SINPAD", loc)
        if m:  # columna SINPAD del cuadro de ubicación
            codes = re.findall(r"(?<!\d)(\d{5,7})(?!\d)", loc[m.end():])
            if codes:
                out["sinpad"] = codes[0]
    decrees = []
    for m in _DECREE.finditer(re.sub(r"\s+", " ", text)):
        around = re.sub(r"\s+", " ", text)[max(0, m.start() - 200):m.end() + 200]
        decrees.append({"numero": m.group(1).upper(), "inminente": bool(_DECREE_IMMINENT.search(around))})
    if decrees:
        out["decretos"] = list({d["numero"]: d for d in decrees}.values())
    out["danos"] = coen_damages(_section(text, r"3\.1\s*Reporte de da[ñn]os", r"\n\s*3\.2|\n\s*(?:4\.\s*)?ACCIONES"))
    return out


def _location_rows(block: str) -> list[tuple[str, str, str]]:
    """(departamento, provincia, distrito) de las filas del cuadro «2. UBICACIÓN» (columnas separadas por espacios)."""
    rows = []
    lines = block.splitlines()
    head = next((i for i, l in enumerate(lines) if re.search(r"DEPARTAMENTO\s{2,}PROVINCIA", l)), None)
    if head is None:
        return rows
    for line in lines[head + 1:]:
        cells = [c.strip() for c in re.split(r"\s{2,}", line.strip()) if c.strip()]
        if len(cells) >= 3 and not re.search(r"\d", " ".join(cells[:3])) and cells[0].upper() == cells[0]:
            rows.append((cells[0], cells[1], cells[2]))
        elif rows and len(cells) <= 1:
            continue
    return rows


# --- Cuadro de daños ---------------------------------------------------------
_NUM = re.compile(r"(?<!\S)(\d{1,3}(?:[ ,.]\d{3})+|\d+(?:[.,]\d+)?)(?!\S)")
_ROW = re.compile(r"^\s*(DPTO|DEP|DEPARTAMENTO|PROV|PROVINCIA|DIST|DISTRITO|TOTAL)\b\.?\s*(.*)$", re.I)


def _cells(line: str) -> list[tuple[int, int, str]]:
    """Frases de una línea de encabezado (separadas por dos o más espacios) con su columna inicial y final."""
    return [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\S+(?: \S+)*", line)]


def _number(raw: str, decimals: bool) -> Optional[float]:
    s = raw.replace(" ", "")
    if decimals and re.fullmatch(r"\d+[.,]\d{1,2}", s):
        return float(s.replace(",", "."))
    s = re.sub(r"[.,]", "", s)
    return float(s) if s.isdigit() else None


#: Grupos del encabezado del cuadro de daños (el más cercano a una cifra decide de qué es).
_GROUPS = [("persona", r"\bvida\b|persona"), ("vivienda", r"vivienda"),
           ("agricultura", r"agricultur|agrari|agropecuari|cultivo"),
           ("transporte", r"transporte|\bvial\b|\bvias?\b|puente|carretera"), ("educacion", r"educa"),
           ("salud", r"salud")]


def _column(group: str, leaf: str) -> Optional[tuple[str, float]]:
    """Columna del catálogo (y factor) de una columna del cuadro de daños del COEN, por su grupo («persona»,
    «vivienda»…) y las palabras de su encabezado."""
    k = E.key(leaf)
    if group == "vivienda":
        if re.search(r"colapsad|destruid", k):
            return "ViviendasDestruidas", 1
        if re.search(r"inhabitable|afectad", k):
            return "ViviendasAfectadas", 1
        return None
    if group == "persona" or (not group and re.search(r"fallecid|desaparecid|herid|lesionad|damnificad", k)):
        for pat, col in (("fallecid", "Fallecidos"), ("desaparecid", "Desaparecidos"), ("herid|lesionad", "Heridos"),
                         ("damnificad", "Damnificados"), ("afectad", "Afectados")):
            if re.search(pat, k):
                return col, 1
        return None
    if re.search(r"cultivo|hectarea|\(ha\)", k) or (group == "agricultura" and re.search(r"\(ha\)|hectarea", k)):
        return "HectareasCultivo", 1
    if re.search(r"\bvias?\b|carretera|camino|trocha", k) and re.search(r"\((?:m|km)\)|metros|kilometros", k):
        return "KmVias", 0.001 if re.search(r"\(m\)|metros", k) else 1
    if re.search(r"educativ", k) or (group == "educacion" and re.search(r"afectad|colapsad|inhabitable", k)):
        return "CentrosEducativos", 1
    if re.search(r"establecimientos? de salud|\beess\b|ipress", k) or (
            group == "salud" and re.search(r"establecimiento|afectad|colapsad|inhabitable", k)):
        return "CentrosSalud", 1
    return None


def coen_damages(block: str) -> dict[str, dict]:
    """Cuadro «3.1 Reporte de daños» de un reporte del COEN → {fila: {columna del catálogo: valor}}, con fila
    ``total`` (la primera con cifras, la del nivel más alto) y una por distrito (``key`` de su nombre). Cada cifra
    toma las palabras del encabezado que tiene justo encima y el grupo («VIDA Y SALUD», «VIVIENDA»…) más cercano;
    un encabezado que no se entiende no se asigna."""
    lines = [l.rstrip() for l in block.splitlines() if l.strip()]
    first = next((i for i, l in enumerate(lines) if _ROW.match(l)), None)
    if first is None:
        return {}
    header = [l for l in lines[:first] if not re.match(r"\s*Actualizado", l, re.I)]
    phrases = [(a, b, w) for h in header for a, b, w in _cells(h)]
    groups = [((a + b) / 2, g) for a, b, w in phrases for g, pat in _GROUPS if re.search(pat, E.key(w))
              and not (g == "salud" and re.search(r"\bvida\b", E.key(w)))]
    rows: dict[str, dict] = {}
    for line in lines[first:]:
        if re.match(r"\s*(?:Nota|Fuente)\b", line, re.I):
            break
        m = _ROW.match(line)
        if not m:
            continue
        label_end = m.start(2) + len(re.split(r"\s{3,}", m.group(2))[0])
        values: dict[str, float] = {}
        for n in _NUM.finditer(line):
            if n.start() < label_end:
                continue
            x = (n.start() + n.end()) / 2
            leaf = []
            for h in header:
                near = [(abs((a + b) / 2 - x), w) for a, b, w in _cells(h) if a - 3 <= x <= b + 3]
                if near:
                    leaf.append(min(near)[1])
            group = min(((abs(c - x), g) for c, g in groups), default=(0, ""))[1]
            col = _column(group, " ".join(leaf))
            if not col:
                continue
            v = _number(n.group(1), decimals=col[0] in ("HectareasCultivo", "KmVias"))
            if v is not None:
                values[col[0]] = round(values.get(col[0], 0) + v * col[1], 3)
        if not values:
            continue
        name = re.split(r"\s{3,}", m.group(2))[0].strip()
        if "total" not in rows:
            rows["total"] = values
        if m.group(1).upper().startswith("DIST"):
            rows[E.key(name)] = values
    return rows


def coen(doc: dict, territory, calendar, since: str = "2003-01-01", skipped: Optional[Counter] = None) -> Iterator[dict]:
    """Candidatos del listado de emergencias del COEN: uno por emergencia y distrito (o provincia) del título. Con
    el texto del PDF, la fecha es la de ocurrencia y van la descripción, el código SINPAD (``_sinpad``), las
    cifras del cuadro de daños y los decretos mencionados (``_decretos``); sin él, la fecha es la del primer
    reporte."""
    skipped = skipped if skipped is not None else Counter()
    seen: set[str] = set()
    for e in doc.get("entradas", []):
        t = coen_title(e.get("titulo", ""))
        if not t:
            skipped["sin peligro ni lugar en el título"] += 1
            continue
        dt, method = indeci_type(t["peligro"])
        if not dt:
            skipped[method] += 1
            continue
        rep = coen_first_report(e.get("url", ""), e.get("titulo", ""))
        if not rep:
            skipped["sin fecha"] += 1
            continue
        pdf = coen_pdf(e.get("texto") or "")
        day, fecha_tipo = (pdf["fecha"], "evento") if pdf.get("fecha") else (rep["fecha"], "informe")
        if day < since or day > rep["fecha"][:4] + "-12-31":
            day, fecha_tipo = rep["fecha"], "informe"  # fecha de ocurrencia ilegible o de otro año
        provinces = {E.key(d): p for _, p, d in pdf.get("ubicacion", [])}
        sid_base = f"{rep['tipo'][:1] or 'r'}{rep['numero']}-{rep['fecha'][:4]}"
        if sid_base in seen:  # dos emergencias con el mismo número de primer reporte (erratas del portal)
            sid_base += "-" + hashlib.sha1(e["url"].encode()).hexdigest()[:6]
        seen.add(sid_base)
        codes = []
        for name in t["lugares"]:
            if t["nivel"] == "distrito":
                code = territory.resolve(t["departamento"], provinces.get(E.key(name), t["provincia"]), name)
            elif t["nivel"] == "provincia":
                code = territory.resolve(t["departamento"], name, "")
            else:
                code = territory.resolve(name if name else t["departamento"])
            if code and code not in codes:
                codes.append(code)
        if not codes:
            skipped["sin lugar"] += 1
            continue
        damages = pdf.get("danos") or {}
        for code in codes:
            dep, prov, dist = territory.names(code)
            imp = damages.get(E.key(dist)) if dist and len(codes) > 1 else damages.get(E.key(dist)) or (
                damages.get("total") if len(codes) == 1 else None)
            sid = sid_base if len(codes) == 1 else f"{sid_base}-{code}"
            where = ", ".join(x for x in (dist, prov, dep) if x)
            desc = pdf.get("descripcion") or f"Emergencia por {t['peligro'].lower()} en {where}, reportada por el COEN."
            title = re.sub(r"\s+", " ", e.get("titulo", "")).strip()
            rec = make(territory, calendar, code=code, day=day, precision="dia", danger=dt, origin="coen", source_id=sid,
                       url=e["url"], license=COEN_LICENSE, cite=f"COEN (INDECI), {title}",
                       description=desc[:600], source_type=t["peligro"].title(), danger_method=method, impacts=imp,
                       icen=False)
            rec["FechaTipo"] = fecha_tipo
            rec["_sinpad"] = pdf.get("sinpad")
            rec["_decretos"] = pdf.get("decretos") or []
            rec["_pdf"] = e.get("pdf") or ""
            rec["_relato"] = bool(pdf.get("descripcion"))
            yield rec


# ---------------------------------------------------------------------------
# Decretos supremos de estado de emergencia (El Peruano)
# ---------------------------------------------------------------------------
_DS_NUMBER = re.compile(r"N[°º.\s]*\s*(\d{1,3}-(?:19|20)\d\d-[A-Z]+)", re.I)
_PRORROGA = re.compile(r"\bprorroga\w*\b", re.I)
_IMPACT = re.compile(r"impacto de da[ñn]os|por\s+(?:los\s+)?da[ñn]os|como consecuencia de|a consecuencia de|"
                     r"ocasionad[oa]s? por|producid[oa]s? por", re.I)
#: Peligro de la sumilla de un decreto → DangerType (la primera que coincide).
DECREE_HAZARDS = [
    (r"huaic|huayc|aluvi[oó]n|flujo de detritos|movimientos? en masa|deslizamiento|derrumbe|ca[ií]da de rocas|"
     r"reptaci[oó]n|geodin[aá]mica", "Deslizamiento"),
    (r"inundaci[oó]n|desborde|crecida|colapso de (?:la )?defensa", "Inundacion"),
    (r"d[eé]ficit h[ií]drico|sequ[ií]a|escasez h[ií]drica", "Sequias"),
    (r"helada|friaje|bajas temperaturas|descenso de temperatura|nevada", "Helada/Friaje"),
    (r"oleaje|maretazo|marejada", "Oleaje anomalo"),
    (r"incendio forestal|incendios forestales", "Incendio forestal"),
    (r"erosi[oó]n", "Erosion"),
    (r"vientos? fuertes", "Vientos fuertes"),
    (r"precipitaciones|lluvias", "Lluvias intensas"),
    (r"fen[oó]meno (?:de )?el ni[ñn]o|ni[ñn]o costero", "Lluvias intensas"),
]
def scope_places(scope: str, territory) -> list[str]:
    """Provincias y distritos que nombra el texto de un decreto (ya normalizado con ``esquema.key``): «en las
    provincias de Nazca, Palpa y San Juan de Marcona del departamento de Ica», «en los distritos de A y B de la
    provincia de C del departamento de D». Un nombre que no es provincia se busca como distrito del departamento."""
    deps = sorted((E.key(d["name"]) for d in territory.dep.values()), key=len, reverse=True)
    dep_re = "(?P<dep>" + "|".join(re.escape(d) for d in deps) + ")"
    split = lambda names: [x.strip() for x in re.split(r",\s*|\s+y\s+", names) if x.strip()]  # noqa: E731
    codes: list[str] = []

    def add(code):
        if code and len(code) >= 4 and code not in codes:
            codes.append(code)

    taken = []
    for m in re.finditer(r"distritos? (?:de |del )?(?P<d>[a-z ,]+?) (?:de|en) la provincia (?:de )?(?P<p>[a-z ]+?) "
                         r"(?:del|en el) departamento (?:de )?" + dep_re, scope):
        taken.append(m.span())
        for name in split(m.group("d")):
            add(territory.resolve(m.group("dep"), m.group("p"), name))
    for m in re.finditer(r"provincias? (?:de |del )?(?P<p>[a-z ,]+?) (?:del|en el) departamento (?:de )?" + dep_re, scope):
        if any(a <= m.start() < b for a, b in taken):
            continue
        for name in split(m.group("p")):
            add(territory.resolve(m.group("dep"), name, "") if territory.resolve(m.group("dep"), name, "") not in
                (None, territory.resolve(m.group("dep"))) else territory.resolve(m.group("dep"), "", name))
    return codes


_NOT_CLIMATE_DECREE = re.compile(r"sism|terremot|volc|derrame|contaminaci|orden interno|criminalidad|inseguridad|"
                                 r"narcotr|conflicto|epidemi|dengue|covid|influenza|sanitari|agua para consumo|"
                                 r"servicio de agua|electric|energ", re.I)
_ANNEX_ROW = re.compile(r"^\s*(?:\d+\s+)?(?P<a>[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ .'\-]+?)\s{2,}(?P<b>[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ .'\-]+?)"
                        r"\s{2,}(?P<c>[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ .'\-]+?)\s*$")


def decree_kind(sumilla: str) -> tuple[str, str]:
    """(tipo, peligro) de un decreto: tipo «prorroga», «inminente» (prevención) o «impacto» (respuesta)."""
    s = sumilla or ""
    kind = "prorroga" if _PRORROGA.search(s[:120]) else "inminente" if _DECREE_IMMINENT.search(s) else \
        "impacto" if _IMPACT.search(s) else "otro"
    hazard = next((dt for pat, dt in DECREE_HAZARDS if re.search(pat, s, re.I)), "")
    return kind, hazard


def decree_places(text: str, territory, sumilla: str = "") -> list[str]:
    """Distritos (UBIGEO) del anexo de un decreto: filas «DEPARTAMENTO  PROVINCIA  DISTRITO» del texto con
    columnas. Si no hay anexo legible, los departamentos o provincias que nombra el artículo 1 o la sumilla."""
    codes: list[str] = []
    for line in (text or "").splitlines():
        m = _ANNEX_ROW.match(line)
        if not m:
            continue
        code = territory.resolve(m.group("a"), m.group("b"), m.group("c"))
        if code and len(code) == 6 and code not in codes:
            codes.append(code)
    if codes:
        return codes
    art = re.search(r"Art[ií]culo 1\.?[^\n]*\n?(.{0,900})", text or "", re.S)
    scope = E.key((art.group(0) if art else "") + " " + (sumilla or ""))
    codes = scope_places(scope, territory)
    if codes:
        return codes
    for code, d in territory.dep.items():
        if re.search(r"\b(?:departamentos?|region(?:es)?) (?:de )?(?:[a-z ,]+ y )?" + re.escape(E.key(d["name"])) + r"\b", scope) \
                or re.search(r"\b(?:de|del departamento de) " + re.escape(E.key(d["name"])) + r"\b", scope):
            codes.append(code)
    return codes


_CLIMATE_DECREE = re.compile(r"lluvi|precipitac|huaic|huayc|inundac|desborde|helad|friaje|nevad|d[eé]ficit h[ií]drico|"
                             r"sequ[ií]a|ni[ñn]o|movimientos? en masa|deslizamiento|oleaje|incendio forestal", re.I)


def decrees(doc: dict, territory) -> list[dict]:
    """Declaratorias de estado de emergencia de origen climático: una por decreto, con sus distritos. El peligro y
    el tipo salen de la sumilla y, si hace falta, del texto (los considerandos dicen «por peligro inminente ante
    intensas precipitaciones pluviales»); un decreto de orden interno (VRAEM, criminalidad) o sanitario no entra."""
    out = []
    for n in doc.get("normas", []):
        s = re.sub(r"\s+", " ", n.get("sumilla") or "").strip()
        body = re.sub(r"\s+", " ", (n.get("texto") or "")[:6000])
        both = f"{s} {body}"
        if not _CLIMATE_DECREE.search(both) or (_NOT_CLIMATE_DECREE.search(s) and not _CLIMATE_DECREE.search(s)):
            continue
        if re.search(r"orden interno|narcotr[aá]fico|terroris|criminalidad", both, re.I) and not _CLIMATE_DECREE.search(s):
            continue
        kind, hazard = decree_kind(s)
        k2, h2 = decree_kind(body)
        if kind == "otro":
            kind = k2
        hazard = hazard or h2
        if not hazard:
            continue
        when = (n.get("fechaPublicacion") or "")[:10]
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", when) or re.match(r"(\d{4})(\d{2})(\d{2})$", when)
        if m and len(m.group(1)) == 4:
            when = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        elif m:
            when = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        num = _DS_NUMBER.search(n.get("numeroDispositivo") or "")
        codes = decree_places(n.get("texto") or "", territory, s)
        if not codes:
            continue
        out.append({"fecha": when, "numero": (num.group(1).upper() if num else (n.get("numeroDispositivo") or "").strip()),
                    "tipo": kind, "peligro": hazard, "grupo": E.danger_group(hazard), "sumilla": s[:400],
                    "url": "https://busquedas.elperuano.pe" + n["urlPDF"] if n.get("urlPDF") else "",
                    "ubigeos": codes})
    return sorted(out, key=lambda d: (d["fecha"], d["numero"]))


# ---------------------------------------------------------------------------
# Prensa
# ---------------------------------------------------------------------------
#: Peligro del titular o el extracto → DangerType, en orden de prioridad.
PRESS_HAZARDS = [
    (r"huaic|huayc|aluvi[oó]n|lloclla|activaci[oó]n de (?:la |las )?quebradas?|quebradas? (?:se )?activ", "Huayco/Alud"),
    (r"maretazo|oleaje", "Oleaje anomalo"),
    (r"desbord", "Desborde de rio"),
    (r"inundaci[oó]n|inundad|inunda\b|inundan|inundaron|aniego|anegad", "Inundacion"),
    (r"deslizamiento|derrumbe|ca[ií]da de rocas|desprendimiento de rocas", "Deslizamiento"),
    (r"nevada", "Nevada"),
    (r"granizad|granizo", "Granizada"),
    (r"helada|friaje|bajas temperaturas", "Helada/Friaje"),
    (r"incendio forestal|incendios forestales", "Incendio forestal"),
    (r"sequ[ií]a|d[eé]ficit h[ií]drico", "Sequias"),
    (r"tormenta el[eé]ctrica|descarga el[eé]ctrica|\brayos?\b", "Tormenta electrica"),
    (r"vientos? fuertes|ventarr[oó]n|vendaval", "Vientos fuertes"),
    (r"lluvias?|precipitaciones|aguacero|tormenta", "Lluvias intensas"),
]
#: Algo pasó (no un pronóstico ni una obra): daño, muerte, afectación, un río que se desborda.
_HAPPENED = re.compile(
    r"\bdej[aóo]|\bdejan\b|\bdejaron\b|afect[aóo]\b|afectan\b|afectaron|afectad|damnificad|destru|colaps|arras|sepult|"
    r"\bmuer[et]|fallec|v[ií]ctimas?|desaparecid|herid|aislad|incomunicad|bloque|interrump|evacu|"
    r"\bcae\b|\bcay[oó]\b|caen\b|cayeron|se desbord|desbord[oóa]\b|desbordan|inund[oó]|inundan|inundaron|inundad|"
    r"se registr|ocasion|causa\b|causan|causaron|provoc|azot|golpe|estragos|emergencia en|en emergencia|"
    r"pierden|perdieron|p[eé]rdidas|da[ñn]os?\b|da[ñn]ad", re.I)
#: Daño concreto: lo que hace falta para que lluvias, vientos o tormentas cuenten como evento.
_DAMAGE = re.compile(
    r"\bdej[aóo]|\bdejan\b|\bdejaron\b|afect[aóo]\b|afectan\b|afectaron|afectad|damnificad|destru|colaps|arras|sepult|"
    r"\bmuer[et]|fallec|v[ií]ctimas?|desaparecid|herid|aislad|incomunicad|bloque|interrump|evacu|inund|desbord|"
    r"p[eé]rdidas|da[ñn]os?\b|da[ñn]ad|derrumb|huaic|huayc|desliz|techos?\b|viviendas?\b|cultivos?\b", re.I)
#: Tipos que no son un evento por sí mismos (llueve sin que pase nada).
_NEEDS_DAMAGE = {"Lluvias intensas", "Vientos fuertes", "Tormenta electrica", "Helada/Friaje"}
#: Pronósticos, avisos, obras, declaratorias y prevención: no cuentan como evento si el titular no dice además que
#: algo pasó.
_NOT_EVENT = re.compile(
    r"pron[oó]stic|\bpodr[ií]an?\b|afectar[ií]an?|causar[ií]an?|llegar[ií]an?|ser[ií]an?\b|habr[ií]an?\b|"
    r"\bprev[eé]n?\b|advierte|alerta|aviso|riesgo de|ante (?:la |las |el |los |posibles )|"
    r"para prevenir|prevenci[oó]n|simulacro|limpieza|descolmat|defensas? ribere|obras?\b|licitaci|presupuesto|"
    r"inversi[oó]n|plan de contingencia|se espera|esperan|llegar[aá]|continuar[aá]n?|temporada|kits?\b|"
    r"declar\w+ (?:en )?(?:estado de )?emergencia|estado de emergencia|declaratoria|\bno afectad|"
    r"\bno (?:se )?(?:registr|report|hubo|dej)|\bsin (?:da[ñn]os|afectad|v[ií]ctimas)|"
    r"\b(?:minsa|ministerio)\b.*\b(?:recomienda|recomendaciones)|c[oó]mo (?:protegerse|prepararse)|consejos", re.I)
_OFF = re.compile(r"\bcovid|coronavirus|vacun|elecci|candidat|congres|f[uú]tbol|selecci[oó]n peruana|concierto|"
                  r"aguas? servidas|aguas residuales|aguas negras|aguas pestilentes|desag[üu]es?\b|alcantarill|"
                  r"\bbuz[oó]n|tuber[ií]a|matriz de agua|\bsismo|terremoto|temblor|relaves?\b|derrame de (?:petr|crudo)|colapso de (?:las )?redes|"
                  r"\blluvias? de (?!granizo|nieve|agua)\w+|"
                  r"\bpolic[ií]a (?:captura|detiene)|asesinat|sicari|extorsi|robo\b|delincu|tr[aá]nsito vehicular|"
                  r"acribill|balacera|balead|disparo|"
                  r"(?:barrio|sector|asentamiento|urbanizaci[oó]n|calle|avenida|jr\.?|av\.?)\s+(?:el\s+)?huayc|"
                  r"choque|despiste|volcadura|accidente de tr[aá]nsito|incendio (?:urbano|en vivienda|de vivienda)|"
                  r"estados unidos|eeuu|espa[ñn]a|m[eé]xico|argentina|chile\b|colombia|ecuador|bolivia|brasil|"
                  r"venezuela|europa|china|jap[oó]n|india|guatemala|honduras|filipinas|indonesia", re.I)


def press_hazard(text: str) -> Optional[str]:
    k = text or ""
    for pat, dt in PRESS_HAZARDS:
        if re.search(pat, k, re.I):
            if dt == "Inundacion":
                return E.classify_flood([k], "")[0]
            return dt
    return None


def _clean(s: str) -> str:
    import html

    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\s*(?:PUEDES LEER|LEE TAMBI[EÉ]N|Lee también|Te puede interesar)\b.*$", "", s, flags=re.I).strip()


def _excerpt(s: str, n: int = PRESS_EXCERPT) -> str:
    s = _clean(s)
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.") + "…"


def _slug_title(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-n?\d{4,}$|-noticia-\d+$|\.html?$", "", slug)
    return slug.replace("-", " ").strip().capitalize()


_MONTHS = {m: i + 1 for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                            "septiembre", "octubre", "noviembre", "diciembre"))}
_MONTHS["setiembre"] = 9
_TEXT_DATE = re.compile(r"\b(\d{1,2})(?:\s*(?:y|al|-)\s*\d{1,2})?\s+de\s+(" + "|".join(_MONTHS) +
                        r")(?:\s+(?:de|del)\s+((?:19|20)\d\d))?\b", re.I)
#: Hasta cuántos días antes de la publicación puede estar la fecha que cita la nota.
TEXT_DATE_DAYS = 60


#: Lo que hace climático un derrumbe o una nota cuyo peligro sale del primer párrafo: la lluvia, un río, una quebrada.
_CLIMATE_DRIVER = re.compile(r"lluvi|precipitaci|aguacero|tormenta|huaic|huayc|aluvi|desbord|\br[ií]os?\b|quebrada|"
                             r"crecida|caudal|friaje|helada|graniz|nevada|incendio forestal|sequ[ií]a|oleaje|maretazo|"
                             r"viento", re.I)
#: Derrumbes que casi nunca son climáticos (una pared, una mina, una obra).
_STRUCTURAL = re.compile(r"socav[oó]n|\bminas?\b|\bmineros?\b|\bpared|\bmuros?\b|excavaci|zanja|\bobra\b|"
                         r"construcci[oó]n|\bobrer[oa]s?\b|\bpozo\b|[de]n su (?:vivienda|casa)", re.I)
#: Temor o riesgo: ni un «colapso» en el titular lo vuelve un evento («vecinos temen colapso de torrenteras»).
_FEAR = re.compile(r"\btem(?:e|en|or|ores)\b|\ben riesgo\b|riesgo de|\bamenaza|invocan", re.I)
#: Un evento de otro año que la nota recuerda («avenidas afectadas por el huaico de 2017»).
_PAST_EVENT = re.compile(r"(?:huaic\w*|huayc\w*|lluvias|ni[ñn]o(?: costero)?|inundaci\w+|desborde)\s+(?:de|del)\s+((?:19|20)\d\d)\b",
                         re.I)
#: Botones de compartir que algunos medios dejan en el extracto («0 Facebook 0 Twitter…»).
_SHARE = re.compile(r"(?:\b\d+\s+)?\b(?:Facebook|Twitter|LinkedIn|Pinterest|WhatsApp|Telegram|Email)\b", re.I)


def text_date(text: str, published: str) -> Optional[str]:
    """La fecha más temprana que cita la nota («desde el 10 de abril», «los días 4 y 5 de febrero de 2023») si cae
    hasta ``TEXT_DATE_DAYS`` antes de la publicación: una nota que cuenta un huaico de hace dos semanas no lo
    fecha el día que se publicó. Sin año, el de la publicación (o el anterior si el mes aún no llegó)."""
    pub = date.fromisoformat(published)
    found = []
    for m in _TEXT_DATE.finditer(text or ""):
        day, month = int(m.group(1)), _MONTHS[m.group(2).lower()]
        year = int(m.group(3)) if m.group(3) else pub.year - (month > pub.month)
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if 0 < (pub - d).days <= TEXT_DATE_DAYS:
            found.append(d)
    return min(found).isoformat() if found else None


def press(doc: dict, territory, calendar, outlet: str, departments: Optional[list[str]] = None,
          skipped: Optional[Counter] = None, since: str = "1990-01-01") -> Iterator[dict]:
    """Candidatos de notas de prensa (WordPress, archivo de RPP o sitemaps): las que dicen que un peligro
    climático causó algo en un lugar del Perú. El lugar es el del ubicador de noticias del observatorio (texto
    del titular y el extracto; con un medio regional, su departamento ayuda a desempatar); solo cuentan los
    lugares con la confianza que el sitio exige para publicar, y al menos de provincia. La fecha es la de
    publicación (``FechaTipo = publicacion``)."""
    from ..geo import PUBLISH_MIN, locate_item

    skipped = skipped if skipped is not None else Counter()
    dep = departments[0] if departments and len(departments) == 1 else None
    feed = SimpleNamespace(department=dep, kind="digital")
    seen: set[str] = set()
    for n in doc.get("notas", []):
        url = n.get("url") or ""
        title = _clean(n.get("titulo") or "") or _slug_title(url)
        body = re.sub(r"\s+", " ", _SHARE.sub(" ", _clean(n.get("extracto") or ""))).strip()
        when = (n.get("fecha") or "")[:10]
        precision = "dia"
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
            m = re.search(r"(20\d\d)(\d\d)\.xml", n.get("sitemap") or "")
            if not m:
                skipped["sin fecha"] += 1
                continue
            when, precision = f"{m.group(1)}-{m.group(2)}-01", "mes"
        if when < since:
            continue
        text = f"{title}. {body}"
        if _OFF.search(title):
            skipped["otro tema"] += 1
            continue
        lead = re.split(r"(?<=[.!?])\s", body, maxsplit=1)[0][:200]
        dt = press_hazard(title) or (press_hazard(lead) if _HAPPENED.search(title)
                                     and not re.search(r"incendio|cortocircuito|accidente", title, re.I) else None)
        if not dt:
            skipped["sin peligro climático en el titular"] += 1
            continue
        # Un peligro que sale del primer párrafo, o un derrumbe en una mina o una obra, cuenta solo si hay una causa
        # climática a la vista.
        driver = _CLIMATE_DRIVER.search(f"{title} {lead}")
        if not driver and (not press_hazard(title) or (dt == "Deslizamiento" and _STRUCTURAL.search(f"{title} {lead}"))):
            skipped["sin causa climática a la vista"] += 1
            continue
        if _FEAR.search(title):
            skipped["no dice que algo pasó"] += 1
            continue
        past = _PAST_EVENT.search(title)
        if past and int(past.group(1)) < int(when[:4]):
            skipped["recuerda un evento de otro año"] += 1
            continue
        recap = re.match(r"(" + "|".join(_MONTHS) + r")\s*:", title, re.I)
        if recap and _MONTHS[recap.group(1).lower()] != int(when[5:7]):
            skipped["resumen del año"] += 1
            continue
        strong = re.search(r"\bdej[aóo]|damnificad|\bmuer[et]|fallec|destru|colaps|sepult|desaparecid", title, re.I)
        if not _HAPPENED.search(title) or (_NOT_EVENT.search(title) and not strong) \
                or (dt in _NEEDS_DAMAGE and not _DAMAGE.search(title)):
            skipped["no dice que algo pasó"] += 1
            continue
        geo = locate_item({"title": title, "summary": body[:300]},
                          SimpleNamespace(department=dep, kind=feed.kind))
        places = [p for p in (geo or {}).get("places", []) if p["confidence"] >= PUBLISH_MIN
                  and p["level"] in ("distrito", "provincia") and p["method"] != "medio"]
        if departments and len(departments) > 1:
            places = [p for p in places if p["code"][:2] in departments] or places
        if not places:
            skipped["sin lugar (distrito o provincia)"] += 1
            continue
        # El lugar más seguro (un distrito si empatan): «carretera hacia Tarma» pesa menos que «distrito de Marco».
        p = max(places, key=lambda x: (x["confidence"], x["level"] == "distrito"))
        code = territory.normalize(p["code"])
        if not code:
            skipped["sin lugar (distrito o provincia)"] += 1
            continue
        host = re.sub(r"^www\.", "", url.lower().split("//", 1)[-1].split("/", 1)[0])
        src_id = f"{re.sub(r'[^a-z0-9]+', '-', host).strip('-')}-{hashlib.sha1(url.encode()).hexdigest()[:12]}"
        if src_id in seen:
            skipped["nota repetida"] += 1
            continue
        seen.add(src_id)
        excerpt = _excerpt(body) if body else ""
        told = text_date(text, when) if precision == "dia" else None
        rec = make(territory, calendar, code=code, day=told or when, precision=precision, danger=dt, origin="prensa",
                   source_id=src_id, url=url, license=PRESS_LICENSE,
                   cite=f"{outlet}, {when if precision == 'dia' else when[:7]}: «{title}»",
                   description=(f"«{title}»" + (f" {excerpt}" if excerpt else "") +
                                f" (nota de {outlet}" + (f" publicada el {when}; fecha del evento según el texto"
                                                         if told else "") +
                                f"; lugar según el texto: {p.get('evidence', '')})"),
                   source_type=dt, danger_method="texto", icen=False,
                   confidence="baja" if p["confidence"] < 0.7 or precision != "dia" else "media")
        rec["FechaTipo"] = "texto" if told else "publicacion"
        rec["_publicado"] = when
        rec["_medio"] = outlet
        yield rec


# ---------------------------------------------------------------------------
# Hemerotecas: periódicos antiguos digitalizados
# ---------------------------------------------------------------------------
ARCHIVE_LICENSE = ("Página de periódico digitalizada por la Biblioteca del Congreso de EE. UU. (Chronicling America); "
                   "extracto de hasta 200 caracteres del texto OCR con enlace a la página")
#: Las menciones del Perú anclan el texto que se lee: el fragmento de la página junta varias notas.
_PERU = re.compile(r"\bper[uú]\b|\bperuvian|\bp[eé]rou\b|\bp[eé]ruvien", re.I)
#: Caracteres que se leen antes y después de cada mención del Perú.
ARCHIVE_BEFORE, ARCHIVE_AFTER = 200, 500
#: Los Perú y las Lima de EE. UU. («floods in Peru, Ind.» son las del río Wabash en 1913).
_US_PERU = re.compile(r"\bperu,?\s+(?:ind|ill|indiana|illinois|neb|nebr|nebraska|n\.\s?y|vt|vermont|kan|kans|kansas|mass|"
                      r"me|maine|iowa|mo|ohio|wis|pa)\b|\blima,?\s+(?:o|ohio|n\.\s?y|pa|ind)\b|\bwabash\b|\bindiana\b|"
                      r"\billinois\b|\bmiami county\b", re.I)
#: La geografía de los libros de texto, no un evento («it never rains in Peru»).
_GENERIC = re.compile(r"never rains|rain is unknown|no rain|seldom rains|rarely rains|rainless|il ne pleut", re.I)
#: Sismos, maremotos y volcanes: no son climáticos, aunque el sismo desate un alud (Yungay, 1970).
_SEISMIC = re.compile(r"earthquake|quake|tremor|seismic|tidal wave|tsunami|volcan|eruption|tremblement de terre|"
                      r"s[eé]isme|terremoto|\bsismo|temblor", re.I)
#: Peligro del texto (inglés, francés o castellano) → DangerType, en orden de prioridad.
ARCHIVE_HAZARDS = [
    (r"avalanche|alluvion|aluvi[oó]n|huayco|huaico|mud ?slides?|mud ?flows?|torrents? of mud|lave torrentielle", "Huayco/Alud"),
    (r"overflow|out of (?:its|their) banks|burst (?:its|their) banks|d[ée]bord", "Desborde de rio"),
    (r"\bflood|inundat|freshet|deluge|inond|\bcrues?\b|inundaci", "Inundacion"),
    (r"land ?slides?|land ?slips?|\bslides?\b|glissements? de terrain|[ée]boulement|derrumbe|deslizamiento", "Deslizamiento"),
    (r"drought|s[ée]cheresse|sequ[ií]a", "Sequias"),
    (r"\bhail(?:storms?|stones?|s)?\b|gr[êe]le|granizo", "Granizada"),
    (r"snow ?storm|blizzard|heavy snow|snowfall|nevada", "Nevada"),
    (r"\bfrosts?\b|cold wave|helada|gel[ée]es?\b", "Helada/Friaje"),
    (r"cloud-?burst|\brain|downpour|washouts?|washed out|pluies?\b|\borages?\b|lluvia|aguacero", "Lluvias intensas"),
]
#: Algo pasó: daño, muertes, gente sin casa, el tren detenido.
_ARCHIVE_DAMAGE = re.compile(
    r"damag|destroy|destruct|devastat|disast|havoc|\bruin|wreck|swept away|washed away|carried away|wiped out|"
    r"\bkill|\bdead\b|\bdeaths?\b|\bdied\b|perish|drown|lives (?:were )?lost|loss of life|victims|injur|missing|"
    r"homeless|refugees|\bfled\b|buried|inundated|flooded|\blosses\b|\bloss\b|estimated at|wiped off|survivors|"
    r"common grave|\bbodies\b|rescue|relief|sufferers|distress|"
    r"traffic|interrupt|suspended|cut off|isolated|blocked|washouts?|washed out|famine|starv|"
    r"d[ée]g[âa]ts|d[ée]trui|victimes|\bmorts?\b|noy[ée]s|ravag|sinistr|"
    r"da[ñn]os|destru|muert|v[ií]ctimas|damnificad|arras", re.I)
_ARCHIVE_STRONG = re.compile(r"destroy|swept away|washed away|wiped out|\bkill|\bdead\b|drown|perish|homeless|buried", re.I)
_ARCHIVE_NOT = re.compile(r"\bno (?:serious |great |disastrous |destructive )?(?:damage|rains?|floods?)\b|"
                          r"without (?:any )?damage", re.I)
#: Encabezado del cable («LIMA, Peru, March 20.—»): dice desde dónde se envió, no dónde pasó.
_DATELINE = re.compile(r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][a-z]+)?[,.]\s*(?:Peru|PERU|P[ée]rou)\b[,.]?\s*"
                       r"(?:\((?:AP|UP|UPI|INS)\)\.?\s*)?(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{1,2}"
                       r"(?:\s*\((?:AP|UP|UPI|INS)\))?)?[.,:]?\s*[-—–]*")
#: Nombres de la época o en inglés → los de hoy, para el ubicador.
_OLD_NAMES = [(re.compile(p, re.I), n) for p, n in (
    (r"\bHuaras\b", "Huaraz"), (r"\bTruxillo\b", "Trujillo"), (r"\bPayta\b", "Paita"), (r"\bTumbez\b", "Tumbes"),
    (r"\bCuzco\b", "Cusco"), (r"(?<!La )\bOroya\b", "La Oroya"), (r"\bHuanuco\b", "Huánuco"),
    (r"\bFerrenafe\b", "Ferreñafe"), (r"\bSana\b(?= valley)", "Saña"),
    # Las palabras de nivel que el ubicador entiende («town of Conchucos» es «ciudad de Conchucos»).
    (r"\b(?:the\s+)?department\s+of\b|\bd[ée]partement\s+de\b", "departamento de"),
    (r"\bprovince\s+(?:of|de)\b", "provincia de"), (r"\bdistrict\s+of\b", "distrito de"),
    (r"\b(?:the\s+)?(?:town|city|village|port)\s+of\b|\b(?:ville|port)\s+de\b", "ciudad de"))]


def archive_hazard(text: str) -> Optional[str]:
    for pat, dt in ARCHIVE_HAZARDS:
        if re.search(pat, text, re.I):
            return dt
    return None


def _windows(text: str) -> list[str]:
    """Los tramos del fragmento alrededor de cada mención del Perú (unidos si se tocan)."""
    spans: list[list[int]] = []
    for m in _PERU.finditer(text):
        a, b = max(0, m.start() - ARCHIVE_BEFORE), min(len(text), m.end() + ARCHIVE_AFTER)
        if spans and a <= spans[-1][1]:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    return [text[a:b] for a, b in spans]


def hemeroteca(doc: dict, territory, calendar, archive: str = "Chronicling America (Biblioteca del Congreso de EE. UU.)",
               skipped: Optional[Counter] = None) -> Iterator[dict]:
    """Candidatos de páginas de periódicos antiguos digitalizados (``tools.build_historico.loc_chronam``): el
    fragmento del texto OCR donde la página nombra el Perú y cuenta que un peligro climático causó daños en un
    lugar que el ubicador de noticias reconoce (distrito, provincia o departamento; el lugar del encabezado del cable
    no cuenta). Las páginas son sobre todo de periódicos de EE. UU. que reproducían cables y cartas de cónsules: la
    fecha es la de publicación (``FechaTipo = publicacion``) y el evento pudo ser semanas antes; la confianza, baja."""
    from ..geo import PUBLISH_MIN, key, locate_item

    skipped = skipped if skipped is not None else Counter()
    feed = SimpleNamespace(department=None, kind="digital")
    for p in doc.get("paginas", []):
        url, when = p.get("url") or "", (p.get("fecha") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
            skipped["sin fecha"] += 1
            continue
        if p.get("fragmento") is None:
            skipped["fragmento aún no leído"] += 1
            continue
        text = re.sub(r"\s+", " ", re.sub(r"\[\[/?tag\]\]", "", p["fragmento"])).strip()
        found = None
        why = "no nombra el Perú"
        for w in _windows(text):
            if _US_PERU.search(w):
                why = "Perú o Lima de EE. UU."
            elif _GENERIC.search(w):
                why = "descripción general del país"
            elif _SEISMIC.search(w):
                why = "sismo, maremoto o volcán"
            elif not (dt := archive_hazard(w)):
                why = "sin peligro climático"
            elif not _ARCHIVE_DAMAGE.search(w) or (_ARCHIVE_NOT.search(w) and not _ARCHIVE_STRONG.search(w)):
                why = "no dice que algo pasó"
            else:
                found = (w, dt)
                break
        if not found:
            skipped[why] += 1
            continue
        w, dt = found
        if dt == "Inundacion":
            dt = "Desborde de rio" if re.search(r"\briver\b[^.;]{0,40}\b(?:rose|overflow)|out of its banks", w, re.I) \
                else "Inundacion fluvial" if re.search(r"\brivers?\b", w, re.I) else dt
        clean = _DATELINE.sub(" ", w)
        for pat, new in _OLD_NAMES:
            clean = pat.sub(new, clean)
        geo = locate_item({"title": "", "summary": clean}, feed)
        places = [x for x in (geo or {}).get("places", []) if x["confidence"] >= PUBLISH_MIN and x["method"] != "medio"
                  and x["level"] in ("distrito", "provincia", "departamento")]
        if not places:
            skipped["sin lugar"] += 1
            continue
        # El primer lugar que nombra la nota: el del evento suele ir antes que los de quienes lo informan («hacia
        # el pueblo de Conchucos… dijo el prefecto desde Huaraz»).
        k = key(clean)
        best = min(places, key=lambda x: (k.find(key(x["name"])) % (len(k) + 1), -x["confidence"], -len(x["code"])))
        code = territory.normalize(best["code"])
        if not code:
            skipped["sin lugar"] += 1
            continue
        paper = re.sub(r"\s*\(.*$|\s+\d{4}-.*$", "", p.get("periodico") or "").strip().title() or "periódico sin nombre"
        where = p.get("lugar") or ""
        excerpt = _excerpt(w)
        rec = make(territory, calendar, code=code, day=when, precision="dia", danger=dt, origin="hemeroteca",
                   source_id=f"loc-{hashlib.sha1(url.encode()).hexdigest()[:12]}", url=url, license=ARCHIVE_LICENSE,
                   cite=f"{paper}" + (f" ({where.title()})" if where else "") + f", {when}, vía {archive}",
                   description=(f"«{excerpt}» (página de {paper} publicada el {when}; el evento pudo ser semanas antes; "
                                f"lugar según el texto: {best.get('evidence', '')}; texto OCR de la página digitalizada)"),
                   source_type=dt, danger_method="texto", icen=False, confidence="baja")
        rec["FechaTipo"] = "publicacion"
        rec["_publicado"] = when
        rec["_medio"] = paper
        yield rec


# ---------------------------------------------------------------------------
# Evaluaciones de peligros (INGEMMET, IGP)
# ---------------------------------------------------------------------------
_EVAL_HAZARD = re.compile(r"movimientos? en masa|deslizamiento|huaic|huayc|flujo|aluvi|derrumbe|ca[ií]da|reptaci|"
                          r"inundaci|erosi|geodin[aá]mic|peligros? geol[oó]gic|quebrada|lluvi", re.I)
_SPATIAL = re.compile(r"^(?P<dist>[^,;]+?)\s*[,;]\s*(?P<prov>[^,;]+?)\s*[,;]\s*(?P<dep>[^,;]+?)\s*$")


def evaluations_dspace(doc: dict, territory, institution: str = "INGEMMET") -> list[dict]:
    """Informes técnicos de un repositorio DSpace con lugar (``dc.coverage.spatial``: «distrito, provincia,
    departamento», o los nombres en el título) y año."""
    out = []
    for it in doc.get("items", []):
        dc = it.get("dc") or {}
        title = " ".join(dc.get("dc.title") or [])
        if not _EVAL_HAZARD.search(title + " " + " ".join(dc.get("dc.subject") or [])):
            continue
        year = next((m.group(0) for v in dc.get("dc.date.issued", []) for m in [re.search(r"(19|20)\d\d", v)] if m), "")
        codes = []
        spatial = [s for s in dc.get("dc.coverage.spatial") or [] if E.key(s) not in ("peru", "")]
        if spatial:
            dep = spatial[-1]
            first = spatial[0] if len(spatial) > 1 else ""
            mid = spatial[1] if len(spatial) > 2 else ""
            code = (territory.resolve(dep, mid, first) if first else territory.resolve(dep))
            if code and len(code) < 6 and first:
                code = max((territory.resolve(dep, "", first) or "", territory.resolve(dep, first, "") or "", code), key=len)
            if code and len(code) < 6:
                dm = re.search(r"(?i:distritos?|dist\.)(?:\s+de)?\s+([A-ZÁÉÍÓÚÑ][^,.;:()–-]+?)"
                               r"(?=\s*[,.;:)–-]|\s+(?i:provinc)|\s+y\s|$)", title)
                pm = re.search(r"(?i:provinc\w*|prov\.)(?:\s+de)?\s+([A-ZÁÉÍÓÚÑ][^,.;:()–-]+?)"
                               r"(?=\s*[,.;:)–-]|\s+y\s|\s+(?i:regi|depart)|$)", title)
                better = territory.resolve(dep, pm.group(1) if pm else "", dm.group(1) if dm else "") if (dm or pm) else None
                if better and better.startswith(code) and len(better) > len(code):
                    code = better
            if code:
                codes.append(code)
        if not codes:
            m = re.search(r"distrito(?: de)? ([^,]+), provincia(?: de)? ([^,]+), (?:departamento|regi[oó]n)(?: de)? ([^,.;]+)",
                          title, re.I)
            code = territory.resolve(m.group(3), m.group(2), m.group(1)) if m else None
            if code:
                codes.append(code)
        if not codes or not year:
            continue
        out.append({"anio": int(year), "titulo": title[:300], "url": it.get("url", ""), "institucion": institution,
                    "ubigeos": codes, "grupo": "geologico-hidro" if not re.search(r"inundaci|lluvi", title, re.I)
                    else "hidrometeorologico"})
    return out


def evaluations_geocatmin(doc: dict, territory, layer_url: str = "") -> list[dict]:
    """Evaluaciones de peligros geológicos de GEOCATMIN (INGEMMET, capa «Cartografía de peligros»): una por informe
    (``CODIGO``) y distrito, con el año de la evaluación (``FECHA_EVAL`` o ``AÑO``, «Septiembre 2020») y el
    peligro."""
    seen: dict[tuple, dict] = {}
    for f in doc.get("features", []):
        a = f.get("attributes") or {}
        m = re.search(r"(19|20)\d\d", f"{a.get('FECHA_EVAL') or ''} {a.get('AÑO') or ''}")
        if not m:
            continue
        code = territory.resolve(a.get("DEPARTAMENTO") or "", a.get("PROVINCIA") or "", a.get("DISTRITO") or "")
        if not code or len(code) != 6:
            continue
        rep = str(a.get("CODIGO") or a.get("TITULO") or "").strip()
        hazard = f"{a.get('PELIGRO') or ''} {a.get('PELIGRO_ES') or ''}".strip()
        k = (rep, code)
        if k in seen:
            continue
        url = str(a.get("URL") or "").strip()
        seen[k] = {"anio": int(m.group(0)), "titulo": re.sub(r"\s+", " ", str(a.get("TITULO") or "")).strip()[:300],
                   "url": url if url.startswith("http") else (f"{layer_url}/query?where=CODIGO%3D%27{rep}%27&outFields=*&f=html"
                                                             if layer_url and rep else ""),
                   "institucion": "INGEMMET", "codigo": rep, "ubigeos": [code], "peligro": hazard,
                   "grupo": "hidrometeorologico" if re.search(r"inundaci|fluvial", hazard, re.I) else "geologico-hidro"}
    return sorted(seen.values(), key=lambda e: (e["anio"], e["codigo"], e["ubigeos"][0]))


_NOT_CLIMATE_EVAL = re.compile(r"s[ií]smic|sismo|tsunami|volc[aá]n|eruptiv|geot[eé]cnic|microzonific", re.I)


def evaluations_oai(doc: dict, territory, institution: str = "IGP") -> list[dict]:
    """Informes técnicos de peligros climáticos de un repositorio OAI-PMH (IGP): los que en el título hablan de
    huaicos, deslizamientos, inundaciones o heladas de un lugar. El lugar sale del título («distrito de X,
    provincia de Y») o, si no, del ubicador de noticias (al menos provincia)."""
    from ..geo import PUBLISH_MIN, locate_item

    out = []
    for rec in doc.get("records", []):
        dc = rec.get("dc") or {}
        title = re.sub(r"\s+", " ", " ".join(dc.get("title") or [])).strip()
        if not _EVAL_HAZARD.search(title) or _NOT_CLIMATE_EVAL.search(title):
            continue
        years = [int(m.group(0)) for v in dc.get("date") or [] for m in [re.search(r"(19|20)\d\d", v)] if m]
        if not years:
            continue
        m = re.search(r"distrito(?: de)? ([^,]+), provincia(?: de)? ([^,]+), (?:departamento|regi[oó]n)(?: de)? ([^,.;]+)",
                      title, re.I)
        code = territory.resolve(m.group(3), m.group(2), m.group(1)) if m else None
        if not code:
            geo = locate_item({"title": title, "summary": " ".join(dc.get("coverage") or [])}, None)
            places = [p for p in (geo or {}).get("places", []) if p["confidence"] >= PUBLISH_MIN
                      and p["level"] in ("distrito", "provincia")]
            code = places[0]["code"] if places else None
        if not code:
            continue
        ident = next((v for v in dc.get("identifier") or [] if v.startswith("http")), "")
        out.append({"anio": min(years), "titulo": title[:300], "url": ident, "institucion": institution,
                    "ubigeos": [code], "grupo": "hidrometeorologico" if re.search(r"inundaci|lluvi|helad|friaje", title, re.I)
                    else "geologico-hidro"})
    return out


#: Clases del inventario de peligros de INGEMMET (``TIP_PELIGRO``, primer nivel) y su grupo de peligro.
INVENTORY_CLASSES = {"1000": ("movimientos en masa", "geologico-hidro"),
                     "2000": ("otros peligros geológicos", "geologico-hidro"),
                     "3000": ("peligros geohidrológicos", "hidrometeorologico")}


def inventory_dated(doc: dict, territory, layer_url: str = "") -> list[dict]:
    """Puntos del inventario de peligros geológicos de INGEMMET con la fecha en que se inventariaron (``FECHA``):
    uno por distrito, año y clase, con cuántos puntos. Es evidencia de que el peligro ya estaba documentado en el
    distrito ese año (``tipo = inventario``), no un evento. Solo los registros que INGEMMET publica."""
    from datetime import datetime, timezone

    seen: dict[tuple, dict] = {}
    for f in doc.get("features", []):
        a = f.get("attributes") or {}
        if (a.get("REGISTRO") or "") == "NoMostrarWEB" or not a.get("FECHA"):
            continue
        year = datetime.fromtimestamp(a["FECHA"] / 1000, timezone.utc).year
        code = territory.normalize(str(a.get("UBIGEO") or "")) or territory.resolve(
            a.get("NM_DPTO") or "", a.get("NM_PROV") or "", a.get("NM_DIST") or "")
        cls = INVENTORY_CLASSES.get(str(a.get("TIP_PELIGRO") or "").split("|")[0])
        if not code or len(code) != 6 or not cls or not 1900 < year <= date.today().year:
            continue
        k = (code, year, cls[0])
        if k not in seen:
            seen[k] = {"anio": year, "titulo": "", "url": f"{layer_url}/query?where=UBIGEO%3D%27{code}%27&outFields=*&f=html"
                       if layer_url else "", "institucion": "INGEMMET", "ubigeos": [code], "grupo": cls[1],
                       "tipo": "inventario", "clase": cls[0], "puntos": 0}
        seen[k]["puntos"] += 1
    for e in seen.values():
        e["titulo"] = f"Inventario de peligros geológicos: {e['puntos']} punto(s) de {e['clase']}"
    return sorted(seen.values(), key=lambda e: (e["anio"], e["ubigeos"][0], e["clase"]))


# ---------------------------------------------------------------------------
# Llamamientos internacionales (IFRC GO)
# ---------------------------------------------------------------------------
#: Tipos de desastre de IFRC GO que son climáticos (el resto: sismos, epidemias, movimientos de población…).
IFRC_CLIMATE = {"Flood", "Flash Flood", "Cold Wave", "Drought", "Storm Surge", "Cyclone", "Heat Wave", "Landslide",
                "Fire", "Extreme temperature", "Pluvial/Flash Flood", "Fluvial Flood"}


def appeals(doc: dict, page: str = "https://go.ifrc.org/countries/135") -> list[dict]:
    """Llamamientos de emergencia y DREF de la Federación Internacional de la Cruz Roja para el Perú: fecha,
    código, nombre, tipo de desastre, monto pedido y personas a asistir. Solo los metadatos del llamamiento (no
    los informes de campo ni sus contactos). ``clima`` dice si el desastre es climático."""
    out = []
    for a in doc.get("results", []):
        dtype = (a.get("dtype") or {}).get("name") or ""
        start = (a.get("start_date") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
            continue
        name = re.sub(r"\s+", " ", a.get("name") or "").strip()
        out.append({"fecha": start, "codigo": a.get("code") or "", "nombre": name, "tipo": dtype,
                    "modalidad": a.get("atype_display") or "", "clima": dtype in IFRC_CLIMATE
                    or bool(re.search(r"flood|inundac|cold|fr[ií]o|snow|nevad|drought|sequ[ií]a|landslide|huaic",
                                      name, re.I)),
                    "montoCHF": a.get("amount_requested") or None, "beneficiarios": a.get("num_beneficiaries") or None,
                    "url": f"https://go.ifrc.org/emergencies/{a['event']}" if a.get("event") else page})
    return sorted(out, key=lambda e: (e["fecha"], e["codigo"]))


# ---------------------------------------------------------------------------
# Desbordes de lagunas glaciares (base global de GLOF)
# ---------------------------------------------------------------------------
GLOF_LICENSE = "CC BY 4.0; citar Lützow, N. y Veh, G., Glacial Lake Outburst Flood Database (Zenodo)"
#: Detonantes de la base, en castellano.
GLOF_TRIGGERS = [(r"calving|ice dam", "desprendimiento o avalancha de hielo y roca, o falla de un dique de hielo"),
                 (r"landslide|rockfall|debris", "deslizamiento, caída de rocas o flujo de detritos"),
                 (r"precipitation|snowmelt|upstream", "lluvia extrema, deshielo o crecida aguas arriba")]
GLOF_MECHANISM = {"breach": "rotura del dique", "overtopping": "desborde sobre el dique",
                  "piping": "tubificación del dique", "breach/overtopping": "desborde y rotura del dique"}


def ods_rows(content: bytes) -> dict[str, list[dict]]:
    """Las hojas de una planilla OpenDocument (.ods) como listas de filas {columna: texto}: la primera fila con
    datos es el encabezado. Sin dependencias (el .ods es un zip con ``content.xml``)."""
    import io
    import xml.etree.ElementTree as ET
    import zipfile

    tns = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
    office = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
    text_p = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(content)).read("content.xml"))
    out = {}
    for t in root.iter(tns + "table"):
        rows = []
        for r in t.iter(tns + "table-row"):
            cells = []
            for c in r:
                if c.tag not in (tns + "table-cell", tns + "covered-table-cell"):
                    continue
                n = min(int(c.get(tns + "number-columns-repeated", "1")), 256)
                # Algunas celdas de la base de GLOF empiezan con una marca de orden de bytes (U+FEFF).
                txt = " ".join("".join(p.itertext()) for p in c.iter(text_p)).replace("\ufeff", "").strip()
                cells += [txt or c.get(office + "date-value") or c.get(office + "value") or ""] * n
            while cells and not cells[-1]:
                cells.pop()
            if cells:
                rows.append(cells)
        if rows:
            head = [h.strip() for h in rows[0]]
            out[t.get(tns + "name")] = [dict(zip(head, r)) for r in rows[1:]]
    return out


def _glof_date(d: dict) -> tuple[Optional[str], str]:
    """(fecha «AAAA-MM-DD», precisión) de un GLOF: la fecha si la base la da (día, mes o año); si solo da una
    ventana (entre dos imágenes de satélite), su punto medio si dura hasta dos meses (precisión mes) o un año
    (precisión año). Ventanas más largas, décadas («1940s») o solo un límite: sin fecha."""
    raw = (d.get("Date") or "").strip()
    m = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", raw)
    if m:
        y, mo, dd = m.groups()
        return (f"{y}-{mo or '01'}-{dd or '01'}", "dia" if dd else "mes" if mo else "anio")
    lo, hi = (d.get("Date_Min") or "").strip(), (d.get("Date_Max") or "").strip()

    def parse(s: str, end: bool) -> Optional[date]:
        m = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", s)
        if not m:
            return None
        y, mo, dd = int(m.group(1)), int(m.group(2) or (12 if end else 1)), int(m.group(3) or (28 if end else 1))
        return date(y, mo, dd)

    a, b = parse(lo, False), parse(hi, True)
    if not a or not b or b < a:
        return None, ""
    span = (b - a).days
    mid = a + (b - a) / 2
    if span <= 62:
        return mid.replace(day=1).isoformat(), "mes"
    if span <= 366:
        return f"{mid.year}-01-01", "anio"
    return None, ""


def glof(sheets: dict[str, list[dict]], territory, calendar, url: str, country: str = "Peru",
         skipped: Optional[Counter] = None) -> Iterator[dict]:
    """Candidatos de la base global de desbordes de lagunas glaciares (GLOF): uno por evento del Perú con fecha,
    ubicado por las coordenadas de la laguna. Se omiten los que causó un sismo (31 de mayo de 1970, 1725)."""
    from .fuentes import place

    skipped = skipped if skipped is not None else Counter()
    seen: set[str] = set()
    for sheet, rows in sheets.items():
        for d in rows:
            if country not in (d.get("Country") or ""):
                continue
            notes = " ".join(d.get(k) or "" for k in ("Further_comments", "Impact_and_destruction", "reported_impacts"))
            if re.search(r"earthquake|sismo|terremoto", notes, re.I):
                skipped["detonado por un sismo"] += 1
                continue
            day, precision = _glof_date(d)
            if not day:
                skipped["sin fecha (ventana de varios años o década)"] += 1
                continue
            lat, lon = (str(d.get(k) or "").replace(",", ".") for k in ("Latitude", "Longitude"))
            code, latlon, _ = place(territory, "", "", "", lat, lon)
            if not code:
                skipped["sin lugar"] += 1
                continue
            lake = (d.get("Lake") or "").strip()
            lake_ref = ""
            if len(lake) > 60 or re.search(r"\(\d{4}\)", lake):
                lake, lake_ref = "", lake  # en una fila de la base, la celda del lago trae la referencia
            lake = re.sub(r"^Unnamed \(Q\. (.+)\)$", r"sin nombre de la quebrada \1", lake)
            lake = re.sub(r"\s+Lake$", "", lake)
            glacier = re.sub(r"\s+glacier$", "", (d.get("Glacier") or "").strip(), flags=re.I)
            if glacier.startswith("RGI"):
                glacier = ""  # un código del inventario mundial de glaciares, no un nombre
            sid = re.sub(r"[^a-z0-9]+", "-", f"{day[:7] if precision != 'anio' else day[:4]}-{lake or glacier or lat}"
                         .lower()).strip("-")
            if sid in seen:
                sid += "-" + hashlib.sha1(f"{lat}{lon}{d.get('Date_Min')}".encode()).hexdigest()[:6]
            seen.add(sid)
            what = (f"una laguna {lake}" if lake.startswith("sin nombre") else f"la laguna {lake}" if lake
                    else "una laguna glaciar (la base no da su nombre)")
            mech = GLOF_MECHANISM.get((d.get("Mechanism") or "").strip().lower(), "")
            drain = (d.get("Further_comments") or "").lower()
            parts = [f"Desborde violento (aluvión) de {what}" + (f", al pie del glaciar {glacier}" if glacier else "")]
            if mech:
                parts.append(f"por {mech}")
            if "complete drainage" in drain:
                parts.append("la laguna se vació por completo")
            elif "partial drainage" in drain:
                parts.append("la laguna se vació en parte")
            trig = re.search(r"triggers?:\s*([^;]+)", d.get("Further_comments") or "")
            desc = ", ".join(parts) + "."
            if trig:
                es = next((t for pat, t in GLOF_TRIGGERS if re.search(pat, trig.group(1), re.I)), trig.group(1).strip())
                desc += f" Detonante según la base: {es}."
            imp_txt = (d.get("Impact_and_destruction") or "").strip()
            if imp_txt and imp_txt.lower() not in ("x", "yes"):
                desc += f" Daños según la base: «{imp_txt[:250]}»."
            if precision != "dia" and not (d.get("Date") or "").strip():
                desc += f" Fecha aproximada: entre {d.get('Date_Min')} y {d.get('Date_Max')} (imágenes de satélite)."
            dead = (d.get("reported_fatalities") or "").strip()
            if dead.lower() == "x":
                desc += " La base registra fallecidos, sin cifra."
            ref = d.get("Reference") or lake_ref or ""
            ref = re.sub(r"\s+", " ", ref if len(ref) > 4 else f"primera mención en {ref}" if ref else "").strip()
            yield make(territory, calendar, code=code, day=day, precision=precision, danger="Huayco/Alud",
                       origin="glof", source_id=sid, url=url, license=GLOF_LICENSE,
                       cite=f"Glacial Lake Outburst Flood Database (Lützow y Veh), hoja {sheet}"
                            + (f"; referencia: {ref[:300]}" if ref else ""),
                       description=desc, place=lake or (f"laguna del glaciar {glacier}" if glacier else "laguna glaciar"),
                       source_type="GLOF (desborde de laguna glaciar)",
                       latlon=latlon, impacts={"Fallecidos": int(dead) if dead.isdigit() else None}, icen=False,
                       confidence="media" if precision == "dia" else "baja")
