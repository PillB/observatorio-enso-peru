"""Del aviso al documento: lo que dice el PDF que el COEN del INDECI enlaza en cada publicación.

El RSS del COEN trae el rótulo de cada publicación y, a veces, unas líneas; la página de la publicación es
una portada con un botón de descarga, y el detalle está en el PDF: los **departamentos expuestos** de un
aviso meteorológico («B. PARA LAS AUTORIDADES Y POBLACIÓN DE LOS DEPARTAMENTOS EXPUESTOS: AMAZONAS, ÁNCASH…»),
las **provincias expuestas** de un aviso de corto plazo (tabla «DEPARTAMENTOS · PROVINCIAS EXPUESTAS»), los
tramos del litoral de un aviso de oleaje y la **ubicación** (departamento, provincia y distrito) de un reporte
de emergencia. Sin el PDF, un aviso que nombra regiones («costa norte y sierra») queda sin departamento y el
mapa de alertas no lo pinta.

``follow`` baja la página y el PDF de las publicaciones de los últimos días que aún no se leyeron (con un tope
de pedidos y de tiempo por corrida, y tres intentos por publicación), y ``apply`` pasa lo leído a cada nota:

* ``geoHint.geo``: los lugares del documento en la forma «provincia de X, departamento de Y», que
  ``geo.locate_item`` convierte en códigos con confianza de campo (0,95). Reemplaza la ubicación por el texto
  del titular, que es más gruesa (el titular dice «distrito de Huaraz (Áncash)»; el PDF, la fila exacta).
* ``document``: el PDF, para que el aviso enlace al informe y no a la portada.
* el resumen (y, si el RSS no traía el tema, el titular) con el texto del aviso y su vigencia.

Lo leído se publica en ``news/documentos.json`` y la corrida siguiente parte de ahí: cada documento se pide
una sola vez, y una nota que se guardó en el histórico antes de que su PDF se leyera lo recibe igual (el
histórico es de solo anexar; ``apply`` actúa sobre la copia en memoria, como las correcciones de la consola).
"""

from __future__ import annotations

import html
import re
import time
import unicodedata
from datetime import datetime, timedelta
from typing import Callable, Optional
from urllib.parse import quote, urlsplit, urlunsplit

#: Feeds cuyas publicaciones enlazan un PDF que se lee (adaptador ``indeci-coen``).
FOLLOW_ADAPTERS = ("indeci-coen",)
#: Publicaciones de hasta estos días (las del mapa de alertas: ``sourcefeed.ALERTS_DAYS``).
DAYS = 7
#: Tope de publicaciones que se leen por corrida (cada una son dos pedidos: la página y el PDF) y de tiempo.
MAX_PER_RUN = 40
MAX_SECONDS = 180.0
#: Intentos por publicación (en corridas distintas) antes de darla por imposible.
MAX_TRIES = 3
#: Lo leído se guarda este tiempo (más que ``DAYS``: una nota vieja que vuelve no se pide de nuevo).
KEEP_DAYS = 21
MAX_PDF_BYTES = 15 * 2**20
#: Más lugares que estos se publican por departamento (el resumen sigue nombrando las provincias).
MAX_PLACES = 25

_PDF_RE = re.compile(r'href="(https?://portal\.indeci\.gob\.pe/wp-content/uploads/[^"]+?\.pdf)"', re.I)
_PAGE_RE = re.compile(r"^https?://portal\.indeci\.gob\.pe/emergencias/[^?#]+", re.I)


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def pdf_link(page: str, title: str = "") -> Optional[str]:
    """El PDF de la publicación en su página. La página enlaza también documentos fijos del sitio (una nota
    de prensa de 2018 en el pie): se prefiere el subido a ``wp-content/uploads`` cuyo nombre comparte más
    palabras con el titular."""
    links = list(dict.fromkeys(html.unescape(u) for u in _PDF_RE.findall(page)))
    if not links:
        return None
    words = {w for w in re.findall(r"[a-z0-9]{3,}", _fold(title))}

    def score(u: str) -> int:
        name = _fold(u.rsplit("/", 1)[-1])
        return sum(1 for w in words if w in name)

    return max(links, key=score)


def safe_url(url: str) -> str:
    """La URL con su ruta codificada (los nombres de archivo del COEN llevan tildes y «°»)."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, quote(p.path, safe="/%"), p.query, p.fragment))


def pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


# ---------------------------------------------------------------------------
# Lugares del documento
# ---------------------------------------------------------------------------
def _gz():
    from .geo import gazetteer

    return gazetteer()


def _dep_code(name: str) -> Optional[str]:
    """Código de un departamento por su nombre exacto («ÁNCASH», «Lima Metropolitana», «Callao»)."""
    from .geo import key

    k = key(re.sub(r"\b(?:metropolitana|provincias|region|regi[oó]n|prov\.?\s*const\.?\s*del?|provincia constitucional del?)\b",
                   " ", name, flags=re.I))
    for c, d in _gz().deps.items():
        if key(d["name"]) == k:
            return c
    return None


_DEPS_LIST_RE = re.compile(r"DEPARTAMENTOS?[^:\n]{0,60}:\s*(?P<list>[^:]+?)(?:\.\s|\.$|\n\s*(?:Por\s|POR\s|[a-z]\)))", re.S)


def listed_departments(text: str) -> list[str]:
    """«… DE LOS DEPARTAMENTOS EXPUESTOS: AMAZONAS, ÁNCASH, … Y TUMBES.» → códigos, en el orden del texto.
    Un trozo corto que no es un departamento se salta («PROV. CONST. DEL CALLAO» mal escrito no corta la lista);
    uno largo la termina (lo que sigue es otra cosa)."""
    out: list[str] = []
    # «… TUMBES Y LA PROVINCIA CONSTITUCIONAL DEL CALLAO», «PROV. CONST. DEL CALLAO», «PROVINCIACONSTITUCIONALDEL»:
    # antes de buscar la lista, porque el punto de «PROV.» la cortaría.
    text = re.sub(r"\b(?:LA\s*)?PROV(?:INCIA)?\.?\s*CONST(?:ITUCIONAL)?\.?\s*DE\s*L?\s*(?=CALLAO)", "", text, flags=re.I)
    for m in _DEPS_LIST_RE.finditer(text):
        names = _flat(m.group("list"))
        parts = re.split(r"\s*,\s*|\s+Y\s+|\s+y\s+", names)
        found = []
        for p in parts:
            c = _dep_code(p.strip(" ."))
            if c:
                found.append(c)
            elif len(p.split()) > 5:  # ya no es un nombre: lo que sigue es otra cosa
                break
        if found:
            out += [c for c in found if c not in out]
    return out


def _unique(codes: list[str]) -> Optional[str]:
    return codes[0] if len(codes) == 1 else None


def province_table(text: str) -> list[str]:
    """Tabla «DEPARTAMENTOS · PROVINCIAS EXPUESTAS» de un aviso de corto plazo → códigos de provincia (o del
    departamento, si una provincia no se reconoce).

    pypdf corta la celda de cada departamento en líneas, a veces en medio de un nombre («Carlos / Fermin
    Fitzcarrald», «San / Pablo», «Santiago de / Chuco»): se une todo lo que sigue a un departamento hasta el
    siguiente y recién ahí se separa por comas. «*Callao» en la fila de Lima es la Provincia Constitucional."""
    m = re.search(r"DEPARTAMENTOS\s+PROVINCIAS\s+EXPUESTAS(?P<t>.+?)(?:\n\s*(?:INDECI|INTERPRETACI|NIVELES|Fuente|PERSPECTIVAS)|\Z)",
                  text, re.S)
    if not m:
        return []
    gz = _gz()
    blocks: list[tuple[str, str]] = []
    for chunk in re.split(r"\n", m.group("t")):
        chunk = chunk.strip()
        if not chunk:
            continue
        head = re.match(r"^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]+?)(?=\s+\*?[A-ZÁÉÍÓÚÑ][a-záéíóúñ]|\s*$)", chunk)
        if head and _dep_code(head.group(1)):
            blocks.append((_dep_code(head.group(1)), chunk[head.end():]))
        elif blocks:
            blocks[-1] = (blocks[-1][0], blocks[-1][1] + " " + chunk)
    out: list[str] = []
    for dep, body in blocks:
        if dep not in out:
            out.append(dep)
        # Lo que sigue al punto final de la celda es otra cosa (la nota «* Provincia Constitucional del Callao»).
        body = re.split(r"\.\s", body + " ", maxsplit=1)[0]
        for name in re.split(r"\s*,\s*|\s+y\s+", _flat(body).strip(" .")):
            name = name.strip(" .")
            if not name:
                continue
            if name.startswith("*") and _dep_code(name.strip("* ")) == "07":
                c = "0701"
            else:
                c = _unique(gz.find(name, "provincia", dep))
            if c and c not in out:
                out.append(c)
    # Sin el departamento si ya está una de sus provincias.
    return [c for c in out if not (len(c) == 2 and any(o != c and o.startswith(c) for o in out))]


def _spellings() -> dict[str, set[str]]:
    """Código → sus nombres (sin tildes, en mayúsculas): el oficial del INEI y los alias de un solo lugar que usa
    el COEN («KIMBIRI» por Quimbiri, «MARISCAL GAMARRA» por Gamarra)."""
    global _SPELLINGS
    if _SPELLINGS is None:
        from .geo import ALIASES

        gz = _gz()
        out: dict[str, set[str]] = {}
        for level in (gz.deps, gz.provs, gz.dists):
            for c, x in level.items():
                out[c] = {_fold(x["name"]).upper()}
        for k, v in ALIASES.items():
            if len(v) == 1 and (c := next(iter(v))) in out:
                out[c].add(_fold(k).upper())
        _SPELLINGS = out
    return _SPELLINGS


_SPELLINGS: Optional[dict[str, set[str]]] = None


def _compact(s: str) -> str:
    return re.sub(r"[^A-Z]", "", s)


class _Section:
    """El texto de la tabla, con y sin espacios, y los nombres del gazetteer que aparecen pegados en él."""

    def __init__(self, text: str):
        self.text = text
        self.compact = _compact(text)
        names = {_compact(n) for ns in _spellings().values() for n in ns}
        self.present = [n for n in names if len(n) >= 4 and n in self.compact]
        self._memo: dict[str, int] = {}

    def glued(self, c: str) -> int:
        """Apariciones de ``c`` sin espacios que no son parte de otro nombre más largo que también está («TOMAS»
        no cuenta como Omas, «CHONGOS» no cuenta como Hongos, «ALTO PICHIGUA» no cuenta como Pichigua)."""
        if c not in self._memo:
            taken = [False] * len(self.compact)
            for big in self.present:
                if len(big) > len(c) and c in big:
                    for m in re.finditer(f"(?={re.escape(big)})", self.compact):
                        for i in range(m.start(), m.start() + len(big)):
                            taken[i] = True
            hits, i = 0, self.compact.find(c)
            while i >= 0:
                if not all(taken[i:i + len(c)]):
                    hits += 1
                    i = self.compact.find(c, i + len(c))
                else:
                    i = self.compact.find(c, i + 1)
            self._memo[c] = hits
        return self._memo[c]

    def count(self, names: set[str], loose: bool = True) -> int:
        """Veces que aparece un lugar. pypdf pega y parte las celdas de la tabla («LOCUMBAJORGE BASADRETACNA»,
        «PAMPASAN LUISCARLOS», «PASCO OX APAMPA»): un nombre de 4 letras o más se cuenta en el texto sin espacios;
        uno más corto, solo como palabra. ``loose=False`` exige 6 letras para contarlo pegado."""
        best = 0
        for n in names:
            c = _compact(n)
            if len(c) >= (4 if loose else 6):
                hits = self.glued(c)
            else:
                hits = len(re.findall(rf"(?<![A-Z]){re.escape(n)}(?![A-Z])", self.text))
            best = max(best, hits)
        return best


def _same_name(code: str, others: list[str]) -> int:
    """Cuántos de ``others`` (ya hallados) se llaman igual que ``code``: cada uno ya usó una aparición
    («PIURA PIURA PIURA»: el departamento, la provincia y el distrito)."""
    sp = _spellings()
    mine = {_compact(n) for n in sp[code]}
    return sum(1 for o in others if o != code and mine & {_compact(n) for n in sp[o]})


def _location_table(text: str) -> Optional[_Section]:
    """La tabla «UBICACIÓN» de un reporte de emergencia, sin sus rótulos."""
    m = re.search(r"UBICACI[ÓO]N\s*:?(?P<t>.+?)(?:\n\s*\d\.\s+[A-ZÁÉÍÓÚ]|EVALUACI[ÓO]N DE DA|Distribuci[óo]n\s*:|"
                  r"CENTRO DE OPERACIONES|\Z)", text, re.S)
    if not m:
        return None
    sec = re.sub(r"\b(?:DEPARTAMENTO|PROVINCIA|DISTRITO|BARRIO|LOCALIDAD|CENTRO POBLADO|SECTOR|ANEXO|CASER[ÍI]O|"
                 r"COMUNIDAD|ZONA|UBICACI[ÓO]N|DPTO|PROV|DIST|DIRECCI[ÓO]N|SINPAD)\.?\b", " ", m.group("t"))
    return _Section(_flat(_fold(sec).upper()))


def location_rows(text: str) -> list[str]:
    """Sección «UBICACIÓN» de un reporte de emergencia (tabla departamento · provincia · distrito · localidad) →
    los códigos más finos que nombra.

    El texto que saca pypdf de esa tabla no respeta filas ni columnas («TALAVERAANDAHUAYLASAPURÍMAC SACHAPUNA»):
    se buscan los departamentos que aparecen, luego sus provincias y luego los distritos de esas provincias. Un
    nombre igual al de su departamento o su provincia («LIMA LIMA LIMA») cuenta solo si aparece una vez más por
    cada uno; uno que es parte de otro nombre del texto, no cuenta ahí. Si la provincia no se lee («LIMA CALLAO
    VENTANILLA»), se buscan los distritos de todo el departamento; un departamento sin provincia ni distrito
    cuando otro sí los tiene es un centro poblado de ese nombre («JUNÍN CONCEPCIÓN ANDAMARCA HUÁNUCO»)."""
    table = _location_table(text)
    if table is None:
        return []
    gz, sp = _gz(), _spellings()

    def pick(codes: list[str], above: list[str], loose: bool = True) -> list[str]:
        return [c for c in codes if table.count(sp[c], loose) >= 1 + _same_name(c, above)]

    out: list[str] = []
    for dc in pick(list(gz.deps), []):
        provs = pick([pc for pc in gz.provs if pc.startswith(dc)], [dc])
        rows: list[str] = []
        for pc in provs:
            rows += pick([xc for xc in gz.dists if xc.startswith(pc)], [dc, pc]) or [pc]
        if not provs:
            rows = pick([xc for xc in gz.dists if xc.startswith(dc)], [dc], loose=False)
        out.append(rows or [dc])
    deep = [r for r in out if len(r[0]) > 2]
    return sorted(c for r in (deep or out) for c in r)


#: Letras que debe tener un nombre de lugar para buscarlo pegado en la tabla de ubicación (uno más corto aparece por
#: azar dentro de otros nombres).
TABLE_PLACE_LETTERS = 5


def table_localities(text: str, codes: list[str]) -> list[dict]:
    """La columna de localidad de la tabla «UBICACIÓN» (sector, comunidad, barrio, centro poblado): los centros
    poblados de esos distritos (``enso.lugares``) que aparecen en ella, aunque pypdf pegue las celdas
    («CONDEBAMBA PANAMÁCAJAMARCA CAJABAMBA»). No cuentan los nombres del departamento, la provincia, el distrito
    ni su capital, uno que es parte de otro nombre hallado, ni uno con homónimos en el distrito."""
    from .lugares import GENERIC, inside_district, lugares, name_key

    table = _location_table(text)
    if table is None:
        return []
    gz, L = _gz(), lugares()
    out: list[dict] = []
    for code in [c for c in codes if len(c) == 6][:3]:
        lab = gz.label(code)
        skip = {_compact(name_key(n).upper()) for n in (lab["name"], lab.get("province", ""), lab.get("department", ""),
                                                        (gz.dists.get(code) or {}).get("capital", "")) if n}
        found: dict[str, list] = {}
        for k, rows in L.index(code).items():
            c = _compact(k.upper())
            if len(c) < TABLE_PLACE_LETTERS or k in GENERIC or c in skip or c not in table.compact:
                continue
            if table.glued(c):
                found[c] = rows
        for c, rows in found.items():
            if any(c != o and c in o for o in found):
                continue  # «CHULLUNI» dentro de «UROSCHULLUNI»
            p = L._place(rows, code, f"tabla de ubicación del reporte: {title_case(rows[0][0])}")
            if p and inside_district(code, p.lat, p.lon):
                out.append({**p.as_dict(), "kind": "centro-poblado", "district": code})
    return out


def title_case(s: str) -> str:
    from .lugares import title

    return title(s)


#: Tramos del litoral en los boletines de oleaje del COEN (los mismos de la DHN).
def litoral_departments(text: str) -> list[str]:
    from .hazardparse import DHN_LITORAL

    tramos = [t.lower() for t in re.findall(r"LITORAL\s+(NORTE|CENTRO|SUR)\b", text, re.I)]
    names = list(dict.fromkeys(d for t in ("norte", "centro", "sur") if t in tramos for d in DHN_LITORAL[t]))
    return [c for c in (_dep_code(n) for n in names) if c]


# ---------------------------------------------------------------------------
# Texto del aviso
# ---------------------------------------------------------------------------
_AVISO_RE = re.compile(r"AVISO\s+(?:ESPECIAL\s+DE\s+OLEAJE\s+)?N\s*[°º]?\s*(?P<num>\d+)\s*:\s*(?P<what>.+?)\s*\n?\s*"
                       r"VIGENCIA\s*:\s*(?P<when>[^\n]+)(?P<body>.*)", re.S)
_VIG_RE = re.compile(r"VIGENCIA\s*:\s*(?P<when>\d{1,2}-\d{1,2}-\d{4}\s*\(\d{1,2}:\d{2}\s*h\)\s*al\s*\d{1,2}-\d{1,2}-\d{4}\s*"
                     r"\(\d{1,2}:\d{2}\s*h\))", re.I)
_FUENTE_RE = re.compile(r"Fuente\s*:\s*(?P<src>Aviso\s+N\s*[°º]?\s*\d+[^\n]*(?:\n[^\n]{0,60})?)", re.I)


def _body(s: str) -> str:
    """El párrafo del aviso, sin lo que el PDF pone después (rótulos, «Fuente:», la leyenda del mapa)."""
    s = _flat(re.split(r"\n\s*(?:BOLET[ÍI]N|INDECI|Fuente|SOLO|M[OÓ]DULO|Chorrillos|IMPACTO|En aplicaci)", s)[0])
    if len(s) > 420:  # hasta la última oración completa
        cut = s[:420].rfind(". ")
        s = s[:cut + 1] if cut > 120 else s[:419].rstrip() + "…"
    return s


_PROSE_RE = re.compile(
    r"distrito\s+(?:y\s+provincia\s+)?(?:de\s+)?(?P<dist>[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñü' -]+?)\s*"
    r"(?:,\s*(?:en\s+la\s+)?provincia\s+(?:de\s+)?(?P<prov>[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñü' -]+?))?\s*[.,;()\n]")


def described_place(text: str) -> list[str]:
    """Cuando la tabla de ubicación es una imagen, el lugar de la descripción del reporte, antes de la tabla
    («…en el sector Los Pinos de la comunidad Tambillo, distrito Challhuahuacho, provincia de Cotabambas.»)."""
    head = _flat(re.split(r"UBICACI[ÓO]N", text, maxsplit=1)[0])
    gz = _gz()
    for m in _PROSE_RE.finditer(head):
        both = re.search(r"distrito\s+y\s+provincia", m.group(0), re.I)
        dist = m.group("dist").strip()
        c = gz.from_admin(dist, dist if both else (m.group("prov") or "").strip())
        if c and len(c) == 6:
            return [c]
    return []


_RIVER_RE = re.compile(r"comportamiento\s+hidrol[óo]gico\s+del\s+r[íi]o\s.{0,60}?\s+en\s+el\s+departamento\s+de\s+"
                       r"(?P<dep>[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ ]+?)\s*\(\s*Prov\.?\s*(?P<prov>[^)]+?)\s*\)", re.I | re.S)
_STATION_RE = re.compile(r"^(?P<row>.*?[A-Za-zÁÉÍÓÚÑáéíóúñ].*?)\s+\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s*$", re.M)


def river_place(text: str) -> list[str]:
    """Aviso hidrológico: el distrito de la estación («Río Estación Distrito … / Amazonas Puerto Alegría Yavari
    59.54 58.78») en el departamento que nombra («…en el departamento de LORETO (Prov. Mariscal Ramón
    Castilla)»); si no se lee, la provincia o el departamento."""
    m = _RIVER_RE.search(text)
    dep = _dep_code(m.group("dep")) if m else None
    if not dep:
        return []
    gz, sp = _gz(), _spellings()
    prov = next(iter(gz.find(_flat(m.group("prov")), "provincia", dep)), None)
    rows = " · ".join(r.group("row") for r in _STATION_RE.finditer(text))
    table = _Section(_flat(_fold(rows).upper()))
    found = [c for c in gz.dists if c.startswith(dep) and table.count(sp[c])]
    # La provincia del texto primero: la estación Lagunas está en el distrito de Lagunas (Alto Amazonas).
    inside = [c for c in found if prov and c.startswith(prov)]
    return inside or found[:3] or [prov or dep]


#: Lima y Callao se confunden en los reportes («LIMA CALLAO VENTANILLA», «Ventanilla (Lima)»).
_SAME = {"07": "15"}


def title_departments(title: str) -> list[str]:
    """Departamentos entre paréntesis al final del titular de un reporte («… de Ccapi (Cusco)»)."""
    m = re.search(r"\(([^()]+)\)\s*$", title or "")
    if not m:
        return []
    names = re.split(r"\s*,\s*|\s+y\s+", m.group(1).strip())
    return [c for c in (_dep_code(n) for n in names) if c]


def read(text: str, title: str = "") -> dict:
    """Lo que el observatorio usa de un PDF del COEN: lugares (``codes``), de dónde salen (``basis``), el
    número, tema y vigencia del aviso y su texto."""
    out: dict = {}
    up = title.upper()
    oleaje = "OLEAJE" in up or "AVISO ESPECIAL DE OLEAJE" in text.upper()
    corto = "CORTO PLAZO" in up
    if corto and (codes := province_table(text)):
        out.update(codes=codes, basis="provincias expuestas del boletín del COEN")
    elif oleaje and (codes := litoral_departments(text)):
        out.update(codes=codes, basis="tramos del litoral del boletín de oleajes del COEN")
    elif (codes := listed_departments(text)):
        out.update(codes=codes, basis="departamentos expuestos del boletín del COEN")
    elif (codes := river_place(text)):
        out.update(codes=codes, basis="estación del boletín de aviso hidrológico del COEN")
    elif (codes := location_rows(text)):
        out.update(codes=codes, basis="ubicación del reporte del COEN")
    elif (codes := described_place(text)):
        out.update(codes=codes, basis="descripción del reporte del COEN")
    if out.get("basis", "").endswith("reporte del COEN"):
        # La página enlaza el PDF de otra publicación: «…Ccapi (Cusco)» con el reporte de Huancabamba (Piura),
        # el boletín de corto plazo N° 193 con el reporte de Mariscal Gamarra.
        gz = _gz()
        said = title_departments(title)
        where = ", ".join(gz.label(c)["name"] for c in codes[:3])
        if re.match(r"\s*(?:aviso|bolet[íi]n)\b", title, re.I):
            return {"mismatch": f"el PDF es un reporte de emergencia ({where}); la publicación, un aviso"}
        if said and not {_SAME.get(c[:2], c[:2]) for c in codes} & {_SAME.get(d, d) for d in said}:
            return {"mismatch": f"el PDF ubica en {where}; el titular, en {', '.join(gz.label(d)['name'] for d in said)}"}
    if out.get("basis", "").endswith("reporte del COEN"):
        # El centro poblado del hecho: el que nombra la descripción («en el sector de Panamá») y, si no, el de la
        # columna de localidad de la tabla de ubicación.
        from .lugares import localities

        dists = [c for c in out["codes"] if len(c) == 6]
        head = _flat(re.split(r"UBICACI[ÓO]N", text, maxsplit=1)[0])
        pts = localities(dists, head) or table_localities(text, dists)
        if pts:
            out["localidades"] = pts
    a = _AVISO_RE.search(text)
    if a:
        out.update(num=int(a.group("num")), what=_flat(a.group("what")).rstrip(" ."),
                   when=_flat(a.group("when")).rstrip(" ."), body=_body(a.group("body")))
    else:
        v = _VIG_RE.search(text)
        if v:
            out["when"] = _flat(v.group("when"))
        f = _FUENTE_RE.search(text)
        if f:
            out["source"] = _flat(f.group("src"))
    return out


def summary(doc: dict, kind: str = "meteorológico") -> str:
    """Resumen del aviso con lo que dice su PDF (la vigencia en la forma que lee ``severity.validity``)."""
    gz = _gz()
    parts = []
    if doc.get("what"):
        lead = f"Aviso {kind} N° {doc['num']}" if doc.get("num") else "Aviso"
        parts.append(f"{lead}: {doc['what'][:1].upper()}{doc['what'][1:].lower()}.")
    if doc.get("when"):
        when = doc["when"]
        parts.append(f"VIGENCIA: {when}." if re.match(r"\d", when) else f"Vigencia: {when.lower()}.")
    if doc.get("body"):
        parts.append(doc["body"])
    if doc.get("source") and not doc.get("what"):
        parts.append(f"{doc['source']}.")
    codes = doc.get("codes") or []
    if codes:
        names = [gz.label(c)["name"] for c in codes if gz.valid(c)]
        shown = ", ".join(names[:12]) + (f" y {len(names) - 12} más" if len(names) > 12 else "")
        parts.append(f"Según el PDF del COEN ({doc.get('basis') or 'lugares'}): {shown}.")
    return _flat(" ".join(parts))


def geo_texts(codes: list[str]) -> list[str]:
    """Los lugares en la forma que ``geo.locate_item`` lee como campos de la fuente."""
    gz = _gz()
    out = []
    for c in codes:
        if not gz.valid(c):
            continue
        p = gz.label(c)
        if len(c) == 6:
            out.append(f"distrito de {p['name']}, provincia de {p['province']}, departamento de {p['department']}")
        elif len(c) == 4:
            out.append(f"provincia de {p['name']}, departamento de {p['department']}")
        else:
            out.append(f"departamento de {p['name']}")
    return out


# ---------------------------------------------------------------------------
# Seguimiento y aplicación
# ---------------------------------------------------------------------------
def _when(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


_BULLETIN_RE = re.compile(r"^(?:Aviso (?:meteorol|hidrol)\w+ N° \d+ del SENAMHI|Aviso especial de oleaje|Aviso de corto plazo)", re.I)


def is_bulletin(item: dict) -> bool:
    return bool(_BULLETIN_RE.match(item.get("title") or ""))


def wanted(item: dict, feeds: dict, now: datetime) -> bool:
    """Una publicación del COEN de los últimos días: su PDF dice más que su titular. También los reportes con
    un distrito en el titular: la prueba hacia atrás halló que la ubicación por el texto suma lugares que el
    reporte no tiene («La Cruz (Tumbes)» con una provincia de La Libertad) y le faltan los otros distritos de
    la tabla."""
    f = feeds.get(item.get("feed") or "")
    if not f or getattr(f, "adapter", "") not in FOLLOW_ADAPTERS or not _PAGE_RE.match(item.get("link") or ""):
        return False
    when = _when(item.get("published") or item.get("first_seen"))
    if when is None or now - when > timedelta(days=DAYS):
        return False
    return True


def _placed(item: dict) -> bool:
    return any(len(p.get("code") or "") == 6 for p in (item.get("geo") or {}).get("places") or [])


def load_cache(obj) -> dict:
    """``news/documentos.json`` de la publicación anterior → {enlace: lo leído}."""
    docs = obj.get("documents") if isinstance(obj, dict) else None
    return {k: v for k, v in (docs or {}).items() if isinstance(k, str) and isinstance(v, dict)}


def dump_cache(cache: dict, now: datetime) -> dict:
    since = now - timedelta(days=KEEP_DAYS)
    keep = {k: v for k, v in cache.items() if (_when(v.get("at")) or now) >= since}
    return {"generatedAt": now.isoformat(timespec="seconds"), "keepDays": KEEP_DAYS, "documents": keep}


def follow(items: list[dict], fetch: Callable[[str], tuple], cache: dict, feeds: dict, now: datetime,
           max_items: int = MAX_PER_RUN, max_seconds: float = MAX_SECONDS) -> dict:
    """Lee la página y el PDF de las publicaciones que lo necesitan y aún no se leyeron (los avisos primero, lo
    más nuevo primero). ``fetch(url)`` → (estado, cuerpo, tipo, error). Devuelve cuántas se leyeron, cuántas
    fallaron y cuántas quedaron para la corrida siguiente."""
    todo = [i for i in items if wanted(i, feeds, now)]
    todo = [i for i in todo if (cache.get(i["link"]) or {}).get("status") not in ("ok", "sin-pdf", "sin-datos")
            and int((cache.get(i["link"]) or {}).get("tries") or 0) < MAX_TRIES]
    # Los avisos primero, luego los reportes sin distrito; lo más nuevo primero.
    todo.sort(key=lambda i: (not is_bulletin(i), _placed(i), _neg(i.get("published") or i.get("first_seen") or "")))
    seen: set[str] = set()
    stats = {"read": 0, "failed": 0, "pending": 0}
    started = time.monotonic()
    for it in todo:
        link = it["link"]
        if link in seen:
            continue
        seen.add(link)
        if stats["read"] + stats["failed"] >= max_items or time.monotonic() - started > max_seconds:
            stats["pending"] += 1
            continue
        prev = cache.get(link) or {}
        entry = {"at": now.isoformat(timespec="seconds"), "tries": int(prev.get("tries") or 0) + 1}
        try:
            entry.update(_read_one(link, it.get("title") or "", fetch))
        except Exception as exc:  # noqa: BLE001 — un PDF raro no detiene a los demás
            entry.update(status="error", error=f"{type(exc).__name__}: {exc}"[:200])
        cache[link] = entry
        stats["read" if entry["status"] in ("ok", "sin-datos") else "failed"] += 1
    return stats


def _neg(s: str) -> str:
    """Orden descendente de fechas ISO dentro de una clave ascendente."""
    return "".join(chr(0x10FFFF - ord(c)) for c in s)


def _read_one(link: str, title: str, fetch) -> dict:
    code, body, *_rest = fetch(link)
    if code != 200 or not body:
        err = _rest[1] if len(_rest) > 1 and _rest[1] else f"HTTP {code}"
        return {"status": "error", "error": f"página: {err}"[:200]}
    page = body.decode("utf-8", errors="replace")
    pdf = pdf_link(page, title)
    if not pdf:
        return {"status": "sin-pdf"}
    pdf = safe_url(pdf)
    code, data, *_rest = fetch(pdf)
    if code != 200 or not data:
        err = _rest[1] if len(_rest) > 1 and _rest[1] else f"HTTP {code}"
        return {"status": "error", "error": f"PDF: {err}"[:200], "pdf": pdf}
    if not data.startswith(b"%PDF") or len(data) > MAX_PDF_BYTES:
        return {"status": "error", "error": "la descarga no es un PDF legible", "pdf": pdf}
    doc = read(pdf_text(data), title)
    out = {"status": "no-coincide" if doc.get("mismatch") else "ok" if doc else "sin-datos", "pdf": pdf}
    out.update({k: v for k, v in doc.items() if v})
    return out


_KIND_RE = re.compile(r"^Aviso (meteorol[óo]gico|hidrol[óo]gico) N° (\d+) del SENAMHI", re.I)


def apply(items: list[dict], cache: dict) -> int:
    """Pasa lo leído de cada PDF a sus notas (en memoria). Devuelve cuántas notas cambiaron."""
    from .feedparse import clean_text
    from .news import hazards

    n = 0
    for it in items:
        doc = cache.get(it.get("link") or "")
        if not doc or doc.get("status") != "ok":
            continue
        it["document"] = doc["pdf"]
        if isinstance(doc.get("localidades"), list):
            it["localities"] = [p for p in doc["localidades"] if isinstance(p, dict)][:12]
        codes = [c for c in doc.get("codes") or [] if isinstance(c, str)]
        if len(codes) > MAX_PLACES:  # un aviso de corto plazo nombra cien provincias: basta su departamento
            codes = list(dict.fromkeys(c[:2] for c in codes))
        if codes:
            hint = dict(it.get("geoHint") or {})
            hint.pop("ubigeo", None)
            hint["geo"] = geo_texts(codes)
            it["geoHint"] = hint
        title = it.get("title") or ""
        k = _KIND_RE.match(title)
        oleaje = title.lower().startswith("aviso especial de oleaje")
        kind = k.group(1).lower() if k else ("especial de oleaje" if oleaje else "")
        text = summary(doc, kind or "meteorológico")
        before = it.get("summary") or ""
        if text and not any(doc.get(k) for k in ("what", "num", "when", "body", "source")):
            # Un reporte de emergencia: lo que dice el RSS (el hecho, «Ocurrió el …», que ``severity.occurred``
            # lee) se queda; los lugares del PDF van después.
            if "Según el PDF del COEN" not in before:
                it["summary"] = clean_text(f"{before} {text}".strip(), 900)
        elif text:
            tail = re.search(r"Difundido por el COEN del INDECI[^.]*\.", before)
            it["summary"] = clean_text(text + (f" {tail.group(0)}" if tail else ""), 600)
        if (k or oleaje) and doc.get("what"):
            # El titular con el tema y la vigencia del PDF (el RSS a veces no los trae, o pega palabras).
            head = k.group(0) if k else f"Aviso especial de oleaje N° {doc.get('num') or ''}".rstrip()
            when = f" (vigencia: {doc['when'].lower()})" if doc.get("when") else ""
            it["title"] = clean_text(f"{head}: {doc['what'].lower()}{when}", 300)
        # Los peligros, con el tema que trae el PDF (el RSS del aviso 440 no lo dice: quedaba solo «emergencia»).
        it["hazards"] = list(dict.fromkeys(hazards(it.get("title") or "", it.get("summary") or "")
                                           + [h for h in it.get("hazards") or [] if h != "emergencia"])) or \
            it.get("hazards") or []
        n += 1
    return n
