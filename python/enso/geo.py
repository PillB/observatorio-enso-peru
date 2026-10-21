"""Ubica cada noticia y cada aviso en el Perú: departamento, provincia y distrito (UBIGEO del INEI).

Cada lugar asignado lleva su **confianza** (0 a 1), el **método** con que se
obtuvo y la **evidencia** (el fragmento de texto, el campo o la coordenada).
Solo se publican los lugares con confianza de al menos ``PUBLISH_MIN``; los
demás quedan como sugerencias para la consola de revisión. Las correcciones de
la consola (``enso.geo_overrides``) se aplican después y tienen la última palabra.

Métodos, de más a menos fiable:

``campo``
    La fuente trae el lugar en campos propios: códigos UBIGEO o el nombre del
    distrito, la provincia y el departamento (capas ArcGIS del SENAMHI, avisos
    de la DHN). Se resuelve por jerarquía exacta, no por búsqueda en el texto.
``coordenadas``
    La fuente trae latitud y longitud (sismos, focos de calor): punto en
    polígono sobre los límites distritales del INEI (``enso.limites``).
``texto``
    El titular y el resumen nombran el lugar (reglas abajo).
``medio``
    El texto no nombra ningún lugar y el medio es regional: la nota queda en el
    departamento del medio, con confianza baja (más baja aún si el «medio» es
    una búsqueda de Google Noticias, que encuentra notas nacionales que solo
    mencionan la región en el cuerpo). No se aplica si el texto habla del país,
    de varias regiones o de otro país.

Reglas del texto. Busca los nombres de los 25 departamentos, 196 provincias y
1893 distritos, las capitales de distrito («Pucallpa» → Callería), alias de
uso común («Chosica», «Puerto Eten») y algunos lugares geográficos que ubican
sin ambigüedad («lago Titicaca» → Puno). Muchos nombres se repiten, son
palabras comunes («Santa Rosa», «Independencia», «Mala») o nombran otra cosa
(el río Rímac, el jirón Ica, la Comisión de Constitución, el club Alianza
Lima), así que:

* El nombre debe aparecer con mayúscula inicial (es un nombre propio). En los
  titulares en MAYÚSCULAS o en Formato Título eso no dice nada, y se exige un
  respaldo más fuerte.
* No cuenta si va después de una palabra que lo convierte en otra cosa (río,
  quebrada, jirón, avenida, club, comisión, sector, anexo…), aunque haya una
  enumeración de por medio («quebradas Llaca-Casca, Llullán y Mancos»). Sí
  cuenta, con algo menos de confianza, si es la sede de algo que está en ese
  lugar («Hospital de Chosica», «Universidad de Piura», «bahía de Samanco»).
* No cuenta si es la data de un comunicado («Lima, 20 de octubre de 2026»),
  parte de un nombre de persona o de institución («Santiago Ojeda», «María
  Auxiliadora»), ni si lo sigue el nombre de otro país o de un estado
  extranjero («Loreto, Hidalgo», «Santa Cruz, California»).
* Una palabra de nivel («distrito de», «provincia de», «región», «Municipalidad
  Provincial de», «Gobierno Regional de») indica qué nivel se nombra; en
  plural y con un número («21 distritos de Arequipa») nombra al que los
  contiene. El nivel se hereda en una enumeración («distritos de Piura,
  Sullana y Castilla»), salvo para el departamento que la cierra
  («provincia de Requena-Loreto», «Pampas y Caja (Huancavelica)»), que
  además respalda a los nombres de la enumeración.
* Un nombre repetido en varios lugares solo se asigna si el texto menciona
  también su provincia o departamento (o es el del medio regional).
* Un nombre de la lista ``WEAK`` (palabras comunes, apellidos, santos,
  ciudades de otros países) solo se acepta con una palabra de nivel o con su
  departamento entre paréntesis.
* Un distrito sin ese respaldo solo se acepta si su nombre es único en el
  país, va precedido de una preposición («en», «de», «desde», …), encabeza el
  titular («Sullana: …») o sigue en una enumeración a otro lugar aceptado, y
  el texto no nombra otro departamento.
* En medios internacionales se exige además que el texto hable del Perú; si
  el texto nombra otro país o una ciudad extranjera y no al Perú, solo cuentan
  los departamentos, y si lo nombra un medio extranjero conocido, nada.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

DATA = Path(__file__).resolve().parent / "data" / "ubigeo.json"

#: Versión de las reglas: se guarda en cada nota para saber con qué se ubicó.
GEO_VERSION = 2
#: Confianza mínima para publicar un lugar (los demás quedan como sugerencia en la consola).
PUBLISH_MIN = 0.5

#: Nombres que también son palabras comunes, apellidos, santos o lugares de otros
#: países: se aceptan solo con una palabra de nivel («distrito de Independencia»).
WEAK = {w.strip() for w in """
arma, caja, chalaco, el descanso, independencia, la banda, la matanza, la punta, la victoria, lagunas, llama,
los organos, mala, marca, marcas, marco, punos, quinua, recta, santa, santa rosa, santa maria, santa ana,
santa cruz, santiago, san juan, san pedro, san pablo, san luis, san miguel, san jose, san antonio,
san francisco, san marcos, san isidro, san lorenzo, san rafael, san ramon, san martin, la libertad, amazonas,
grau, bolivar, sucre, castilla, bolognesi, sanchez carrion, leoncio prado, daniel alcides carrion,
ramon castilla, mariscal castilla, jose galvez, ricardo palma, tupac amaru, florida, la florida, belen, victoria,
esperanza, la esperanza, progreso, el progreso, union, la union, paz, la paz, pueblo nuevo, carmen, el carmen,
colonia, morales, castillo, chavez, vega, huerta, salas, pinto, rio grande, mexico, chile, colombia, paris,
tambo, el tambo, pampas, santo domingo, santo tomas, concepcion, asuncion, trinidad, calvario, putumayo,
requena, nueva arica, general san martin, jorge basadre, dos de mayo, manu, sama, pira, inclan, ite,
magdalena, yura, moro, supe, canta,
cocha, huanca, quilca, palca, cochas, pucara, nueva, alianza, libertad, providencia, porvenir,
el porvenir, sorochuco, lucre, luya, ocros, acos, tinta, frias, vilca, ilave, ayo, yanque, pampa, montero,
maria, constitucion, choco, balsas, granada, manta, el alto, montevideo, las lomas, lomas, huaca, puerto,
tres unidos, la merced, los baños del inca, banos, la cruz, cruz, rioja, mariscal caceres, padre abad,
asia, gamarra, jorge chavez, mosca, habana, rosario,
el dorado, casca, cuenca, san cristobal, san agustin, quebrada honda, paraiso, el paraiso, chavin, moche
""".replace("\n", " ").split(",") if w.strip()}
#: Departamentos de ``WEAK`` que se aceptan también tras una preposición («lluvias en La Libertad»).
WEAK_DEPARTMENTS = {"la libertad", "amazonas", "san martin"}
#: Nombres de ``WEAK`` que también se aceptan tras una preposición cuando el texto nombra su departamento.
WEAK_WITH_DEPARTMENT = {"requena", "padre abad", "putumayo", "rioja", "luya", "ocros", "canta", "supe", "yura", "manu",
                        "ilave", "tinta", "pampas", "caja", "pucara", "el dorado", "cuenca"}

SMALL = {"de", "del", "la", "las", "los", "el", "y", "en"}
#: Preposición antes del nombre: indica un lugar.
CUE_RE = re.compile(
    r"\b(?:en|de|del|a|al|desde|hacia|hasta|para|por|entre|sobre|v[ií]a|carretera|tramo|ruta|in|near|at|from|across)"
    r"\s+(?:la\s+|el\s+|los\s+|las\s+)?$",
    re.I)
#: Palabra de nivel antes del nombre; el grupo indica el nivel.
LEVEL_RE = re.compile(
    r"\b(?:(?P<dep>regi[oó]n(?:es)?|departamentos?|gobierno regional|gore|diresa|geresa|coer)|"
    r"(?P<prov>provincias?|municipalidad provincial|mpp?)|"
    r"(?P<dist>distritos?|municipalidad distrital|municipalidades distritales)|"
    r"(?P<city>ciudad(?:es)?|localidad(?:es)?|municipalidad|alcald[ií]a))"
    r"\s+(?:(?:de|del|de la|de los|de las)\s+)?$", re.I)
#: «21 distritos de», «cinco provincias del», «sus distritos de»: el nombre siguiente es el que los contiene.
CONTAINER_RE = re.compile(
    r"\b(?:\d+|un|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|veinte|"
    r"varios|varias|diversos|diversas|algunos|algunas|todos los|todas las|sus|otros|otras|m[aá]s de \d+)\s+"
    r"(?:distritos|provincias|regiones|departamentos|comunidades|localidades|centros poblados)\s+(?:de|del)\s+(?:la\s+)?$",
    re.I)
#: Palabras que convierten el nombre siguiente en otra cosa (un río, una calle, una institución…).
_ANTI_WORDS = (
    r"r[ií]os?|quebradas?|lagunas?|lagos?|nevados?|cerros?|volc[aá]n|cordillera|cuencas?|subcuencas?|"
    r"jir[oó]n|jr|av|avenida|calle|pasaje|psje|ovalo|club|alianza|sport|"
    r"sporting|deportivo|atl[eé]tico|proyecto especial|comisi[oó]n|junta de usuarios|comit[eé]|"
    r"placas?|tect[oó]nicas?|vientos?|combate|batalla|h[eé]roe|monumento|se[ñn]or|virgen|santuario|"
    r"sectore?s?|barrio|urbanizaci[oó]n|urb|asentamiento humano|aa\.?\s?hh|anexos?|caser[ií]os?|"
    r"centros? poblados?|diario|radio|canal|revista|banco|caja|cultura|culturas|"
    r"ala|aaa|administraci[oó]n local de agua|autoridad administrativa del agua|"
    r"emporio|galer[ií]as?|instituci[oó]n educativa|i\.?e\.?|consorcio|empresa|eps|emapa|sedapal|"
    r"facultad|escuela profesional|parque nacional|reserva nacional|santuario nacional|"
    r"plaza|parque|malec[oó]n|estadio|coliseo|mercados?|hospital|colegio|aeropuerto|terminal|universidad|"
    r"valles?|bah[ií]a|comunidad(?:es)?(?: campesinas?| nativas?)?")
ANTI_RE = re.compile(
    r"\b(?P<w>" + _ANTI_WORDS + r")"
    r"\)?\.?\s+(?:(?:de|del|la|el|los|las|a|usuarios de|campesina de|nativa de|nacional de|regional de|"
    r"de apoyo de|docente de|de salud de|de armas de)\s+){0,2}$", re.I)
#: Sedes que están en el lugar que nombran: «Hospital de Chosica», «Universidad de Piura», «valle de Ica».
LOCATED_RE = re.compile(
    r"^(?:plaza|parque|malec[oó]n|estadio|coliseo|mercados?|hospital|colegio|aeropuerto|terminal|universidad|"
    r"valles?|bah[ií]a|sectore?s?|comunidad(?:es)?(?: campesinas?| nativas?)?)$", re.I)
#: Palabras que, después del nombre, lo vuelven otra cosa: «pisco sour» es un cóctel.
NOT_PLACE_AFTER_RE = re.compile(r"^\s+(?:sour|acholado|quebranta|mosto verde)\b", re.I)
DATELINE_RE = re.compile(r"^\s*,\s*\d{1,2}\s+de\s+[a-z]+", re.I)
SEP_RE = re.compile(r"^\s*(?:,|y|e|,\s*y|,\s*e|-|–|/|and|,\s*and)\s*$")
HEAD_PREFIX_RE = re.compile(r"^(?:[A-ZÁÉÍÓÚÑ ]{2,20}\s*\|\s*|[\"“«'‘]\s*)?")
HEAD_END_RE = re.compile(r"^\s*(?:[:,|”\"»]|\.\s?-|\s-\s|\s?[–—]\s)")
#: Palabras que pueden ir después del nombre sin que sea el de una persona o institución.
QUALIFIERS = {"norte", "sur", "este", "oeste", "centro", "metropolitana", "provincias", "alto", "bajo", "medio",
              "region", "regional", "provincia", "ciudad", "cercado"}
#: Palabras con mayúscula que pueden preceder al nombre (no forman con él un nombre propio).
PRE_OK = {"regional", "provincial", "distrital", "region", "provincia", "distrito", "departamento", "ciudad",
          "municipalidad", "gore", "diresa", "geresa", "ugel", "coer", "essalud", "hoy", "ayer", "manana",
          "sedapal", "senamhi", "indeci", "cenepred", "ingemmet", "igp", "ana", "midagri", "minam", "imarpe",
          "enfen", "dhn", "coen", "mtc", "minsa", "vivienda", "agro", "rural", "provias", "lluvias", "huaico",
          "huaicos", "alerta", "emergencia", "sismo", "temblor", "friaje", "heladas", "sequia", "dengue"}
PERU_RE = re.compile(r"\b(per[uú]|peruan[oa]s?|peruvian|peru's)\b", re.I)
_FOREIGN = """España, Andalucía, Cataluña, Madrid, Barcelona, Galicia, Murcia, Sevilla, Málaga, Europa, Italia, Francia,
Alemania, Portugal, Grecia, Reino Unido, Inglaterra, Estados Unidos, EE.UU., EEUU, Texas, California, Nueva York,
Miami, Chicago, Los Ángeles, México, Ciudad de México, CDMX, Jalisco, Veracruz, Oaxaca, Chiapas, Sonora, Sinaloa,
Chihuahua, Tamaulipas, Nuevo León, Yucatán, Quintana Roo, Tabasco, Michoacán, Monterrey, Guadalajara, Cancún,
Acapulco, Guatemala, Honduras, El Salvador, Nicaragua, Costa Rica, Panamá, Cuba, Haití, República Dominicana,
Puerto Rico, Venezuela, Colombia, Ecuador, Bolivia, Chile, Argentina, Brasil, Uruguay, Paraguay, Canadá, China,
India, Japón, Filipinas, Indonesia, Pakistán, Vietnam, Tailandia, Australia, África, Kenia, Etiopía, Somalia,
Sudáfrica, Gaza, Israel, Ucrania, Rusia, Irán, Guayaquil, Esmeraldas, Manabí, Bogotá, Medellín, Barranquilla, Quito,
Buenos Aires, Caracas, Santiago de Chile, Valparaíso, Antofagasta, Santa Cruz de la Sierra, Puntarenas, Spain,
Brazil, United States, Mexico"""
#: Estados, provincias y ciudades extranjeras que también son apellidos o nombres de lugares del Perú: solo
#: cuentan inmediatamente después de otro nombre («Loreto, Hidalgo», «San Francisco (California)»).
_FOREIGN_AFTER = """Hidalgo, Puebla, Morelos, Guerrero, Durango, Coahuila, Querétaro, Guanajuato, Tlaxcala, Campeche, Nayarit,
Colima, Aguascalientes, Baja California, Zacatecas, Florida, Arizona, Nevada, Oregón, Ohio, Illinois, Kentucky,
Michigan, Wyoming, Washington, Valencia, Granada, Córdoba, Almería, Huelva, Cádiz, Asturias, Navarra, Aragón,
Extremadura, Mendoza, Cochabamba, Tarija, Oruro, Potosí, Pando, Beni, Chaco, Biobío, Maule, Manabí, Loja,
El Oro, Zamora Chinchipe, Morona Santiago, Nariño, Antioquia, Cauca, Acre"""
_FOREIGN_NAMES = [n.strip() for n in _FOREIGN.replace("\n", " ").split(",") if n.strip()]


def _variants(n: str) -> set[str]:
    a = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
    return {re.escape(v) for v in (n, n.upper(), a, a.upper())}


#: Otro país o una ciudad extranjera, con mayúscula inicial o en mayúsculas.
FOREIGN_RE = re.compile(r"(?<![\w-])(" + "|".join(sorted({v for n in _FOREIGN_NAMES for v in _variants(n)},
                                                           key=len, reverse=True)) + r")(?![\w-])")
#: «Loreto, Hidalgo», «Santa Cruz (California)»: el nombre anterior es de otro país.
FOREIGN_AFTER_RE = re.compile(r"^\s*(?:,|\(|-)\s*(?<![\w-])(" + "|".join(sorted(
    {v for n in _FOREIGN_NAMES + [n.strip() for n in _FOREIGN_AFTER.replace("\n", " ").split(",") if n.strip()]
     for v in _variants(n)}, key=len, reverse=True)) + r")(?![\w-])")
#: Medios extranjeros que las búsquedas de Google Noticias traen con nombres de lugares del Perú
#: («Jaén» de España, «Loreto» de México): sus notas no se ubican en el Perú si no lo nombran.
FOREIGN_OUTLETS_RE = re.compile(
    r"^(?:el confidencial|hora jaén|hora jaen|lacontradejaén|lacontradejaen|la contra de jaén|diario jaén|"
    r"diario jaen|jaén hoy|ideal|el sol de méxico|el sol de mexico|el universal|milenio|excélsior|excelsior|"
    r"la jornada|el financiero|infobae méxico|2001 online|el tiempo \(colombia\)|el comercio \(ecuador\)|"
    r"el universo|expreso \(ecuador\)|primicias|la tercera|biobiochile|emol|clarín|clarin|la nación \(argentina\))$",
    re.I)
FOREIGN_DOMAIN_RE = re.compile(r"\.(?:es|mx|cl|ec|co|ar|bo|sv|gt|hn|ni|cr|pa|cu|do|ve|uy|py|br)(?:/|$)|chile$", re.I)
#: Gentilicios: «distritos limeños», «agricultores piuranos». Solo ubican si el texto no nombra un lugar.
DEMONYMS = {"limen": "1501", "chalac": "07", "piuran": "20", "tumbesin": "24", "lambayecan": "14", "chiclayan": "1401",
            "liberten": "13", "trujillan": "1301", "cajamarquin": "06", "ancashin": "02", "huaracin": "0201",
            "chimbotan": "021801", "huanuquen": "10", "pasquen": "19", "huancain": "1201", "huancavelican": "09",
            "iquen": "11", "ayacuchan": "05", "apurimen": "03", "cusquen": "08", "cuzquen": "08", "arequipen": "04",
            "moqueguan": "18", "tacnen": "23", "punen": "21", "loretan": "16", "iquiten": "160101", "ucayalin": "25",
            "tarapotin": "220901", "juliaquen": "211101", "pucallpin": "250101"}
DEMONYM_RE = re.compile(r"\b(" + "|".join(sorted(DEMONYMS, key=len, reverse=True)) + r")(?:[oa]s?)\b"
                        r"|\b(juninense|sanmartinense|madrediosense)s?\b", re.I)
_DEMONYM_ES = {"juninense": "12", "sanmartinense": "22", "madrediosense": "17"}
#: El texto habla del país o de varias regiones: el departamento del medio no es el de la nota.
NATIONAL_RE = re.compile(
    r"\b(?:a nivel nacional|de nivel nacional|todo el pa[ií]s|del pa[ií]s|en el pa[ií]s|al pa[ií]s|nuestro pa[ií]s|"
    r"(?:el|del|al|todo el|en)\s+per[uú]\b|peruan[oa]s|regiones|departamentos|varias zonas|diversas zonas|"
    r"(?:el\s+)?(?:norte|sur|centro|oriente)\s+del\s+pa[ií]s|(?:costa|sierra|selva)\s+(?:norte|sur|centro|central)|"
    r"(?:la\s+)?(?:costa|sierra|selva)\s+(?:del\s+per[uú]|peruana)|(?:simulacro|plan|campa[ñn]a|estrategia)\s+nacional|"
    r"congreso|senado|diputados|poder ejecutivo|el ejecutivo|consejo de ministros|premier|"
    r"president[ae] de la rep[uú]blica|latinoam[eé]rica|am[eé]rica latina|sudam[eé]rica|mundo|mundial|global|"
    r"internacional|nationwide|country)\b", re.I)
#: Instituciones cuyo nombre lleva «del Perú» sin que la nota trate del país.
PERU_INSTITUTION_RE = re.compile(
    r"(?:ej[eé]rcito|polic[ií]a nacional|marina de guerra|fuerza a[eé]rea|instituto [\w ]{0,40}|universidad [\w ]{0,40}|"
    r"banco [\w ]{0,30}|servicio nacional [\w ]{0,60}|colegio [\w ]{0,40}|bomberos voluntarios|c[aá]mara [\w ]{0,30})"
    r"\s+del\s+$", re.I)
#: Capitales de distrito muy conocidas que no son capital de provincia.
NOTABLE_CAPITALS = {"chosica", "huaycan", "tingo maria", "quillabamba", "la oroya", "cerro de pasco",
                    "puerto maldonado", "tarapoto", "juliaca", "chimbote", "mollendo", "pichanaki"}
#: Nombres de uso común que el INEI escribe de otra forma, o que la prensa usa para otro distrito.
ALIASES = {"surco": {"150140"}, "tambogrande": {"200114"}, "pichanaki": {"120303"},
           "carmen de la legua": {"070103"}, "nasca": {"1103", "110301"}, "nazca": {"1103", "110301"},
           "banos del inca": {"060108"}, "cuzco": {"08"}, "ciudad imperial": {"0801"}, "lima metropolitana": {"1501"},
           "lima provincias": {"15"}, "lima region": {"15"}, "region lima": {"15"},
           "puerto eten": {"140104"}, "eten puerto": {"140104"}, "puerto supe": {"150205"},
           "mariscal gamarra": {"030703"}, "ancohuallo": {"030602"}, "anco huallo": {"030602"},
           "rupa rupa": {"100601"}, "huaycan": {"150103"}, "vitarte": {"150103"}, "ate vitarte": {"150103"},
           "sjl": {"150132"}, "smp": {"150135"}, "vmt": {"150143"}, "ves": {"150142"},
           "cercado de lima": {"150101"}, "lima cercado": {"150101"}, "cusco ciudad": {"080101"},
           # «Lima» y «Callao»: la provincia (Lima Metropolitana, Callao) y no el departamento ni el distrito.
           "lima": {"1501"}, "callao": {"0701"}}
#: Lugares geográficos que caen enteros en un departamento o provincia: ubican la nota aunque no
#: nombren una división administrativa («lago Titicaca», «río Piura»). Los ríos que cruzan varios
#: departamentos (Mantaro, Marañón, Apurímac, Amazonas…) no están.
LANDMARKS = {
    "lago titicaca": "21", "titicaca": "21", "cordillera blanca": "02", "callejon de huaylas": "02",
    "cordillera negra": "02", "huascaran": "02", "parque nacional huascaran": "02", "valle sagrado": "08",
    "valle sagrado de los incas": "08", "machu picchu": "080108", "canon del colca": "0405", "valle del colca": "0405",
    "reserva nacional de paracas": "110505", "valle del mantaro": "12", "nevado huaytapallana": "1201",
    "huaytapallana": "1201", "lomas de lachay": "1508", "rio piura": "20", "rio chira": "20", "rio tumbes": "24",
    "rio zarumilla": "24", "rio rimac": "15", "rio chillon": "15", "rio lurin": "15", "rio santa": "02",
    "rio la leche": "14", "rio chancay-lambayeque": "14", "rio ica": "11", "rio pisco": "11", "rio moche": "13",
    "rio chicama": "13", "rio jequetepeque": "13", "rio viru": "13", "rio chili": "04",
    "rio camana": "04", "rio majes": "04", "rio caplina": "23", "rio tambo": None, "quebrada del diablo": "2301",
    "volcan misti": "04", "el misti": "04", "volcan ubinas": "1802", "volcan sabancaya": "0405",
    "volcan huaynaputina": "18", "quebrada huaycoloro": "150118", "quebrada de huaycoloro": "150118",
    "carretera central": None, "vraem": None, "islas lobos de afuera": "14",
}


def fold(s: str) -> str:
    """Quita tildes conservando la longitud del texto (para ubicar las coincidencias)."""
    out = []
    for ch in s:
        if ch == "ı":
            out.append("i")
            continue
        d = unicodedata.normalize("NFKD", ch)
        out.append(d[0] if d and not unicodedata.combining(d[0]) else ch)
    return "".join(out)


def key(s: str) -> str:
    return re.sub(r"\s+", " ", fold(s).lower()).strip()


@dataclass
class Match:
    name: str
    codes: set[str]
    cue: Optional[str]  # "level" | "prep" | "located" | "head" | "start" | None
    hint: Optional[str]  # "dep" | "prov" | "dist" | "city" | None
    informative: bool
    pos: int = 0  # orden de aparición (texto y posición)
    evidence: str = ""
    group: int = 0  # enumeración a la que pertenece («Pampas y Caja (Huancavelica)»)
    paren_dep: Optional[str] = None  # departamento que cierra la enumeración
    qualifier: bool = False  # el departamento de «Requena-Loreto» o «Atico, Arequipa»
    container: bool = False  # «21 distritos de Arequipa»
    landmark: bool = False
    chained: bool = False  # sigue a otro nombre en una enumeración
    chain_hint: Optional[str] = None  # el nivel que heredaría de la enumeración
    plural: bool = False  # «distritos de», «provincias de»


@dataclass
class Place:
    code: str
    confidence: float
    method: str
    evidence: str = ""
    extra: dict = field(default_factory=dict)


class Gazetteer:
    def __init__(self, data: dict):
        self.deps = {d["ubigeo"]: d for d in data["departments"]}
        self.provs = {p["ubigeo"]: p for p in data["provinces"]}
        self.dists = {d["ubigeo"]: d for d in data["districts"]}
        names: dict[str, set[str]] = {}

        def add(name: str, code: str) -> None:
            name = re.sub(r"\s*\(.*?\)", "", name).strip()
            if len(name) >= 3:
                names.setdefault(key(name), set()).add(code)
                if "-" in name:  # «Rupa-rupa», «Huanca-Huanca»
                    names.setdefault(key(name.replace("-", " ")), set()).add(code)

        for c, d in self.deps.items():
            add(d["name"], c)
        for c, p in self.provs.items():
            add(p["name"], c)
        for c, d in self.dists.items():
            add(d["name"], c)
        official = set(names)
        prov_capitals = {key(p["capital"]) for p in self.provs.values()}
        for c, d in self.dists.items():
            if d.get("capital"):
                add(d["capital"], c)
        for k, v in ALIASES.items():
            names[k] = set(v)
        #: Capitales de distrito que no son nombre oficial ni capital de provincia (Leticia, Mosca, Angamos…):
        #: solo cuentan con el respaldo de su departamento o del medio regional.
        self.minor_alias = {k for k in names if k not in official and k not in prov_capitals
                            and k not in NOTABLE_CAPITALS and k not in ALIASES}
        self.names = names
        self.dep_by_key = {key(d["name"]): c for c, d in self.deps.items()}
        alts = sorted(names, key=len, reverse=True)
        self.regex = re.compile(r"(?<!\w)(" + "|".join(re.escape(a) for a in alts) + r")(?!\w)", re.I)
        self.landmark_re = re.compile(r"(?<!\w)(" + "|".join(re.escape(a) for a in sorted(LANDMARKS, key=len, reverse=True))
                                      + r")(?!\w)", re.I)
        self.paren_re = re.compile(r"^\s*(?:\(\s*(?:regi[oó]n\s+|departamento\s+de\s+)?|-)(" + "|".join(
            re.escape(fold(d["name"])) for d in sorted(self.deps.values(), key=lambda d: -len(d["name"]))) + r")\s*\)?",
            re.I)

    def _case_informative(self, text: str) -> bool:
        """False en textos en MAYÚSCULAS o en Formato Título, donde la mayúscula no distingue nombres propios.

        Se miran las palabras que no son nombres de lugar (una enumeración de distritos no es Formato Título)."""
        letters = [c for c in text if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
            return False
        words = [w for w in re.findall(r"[^\W\d_]{4,}", text)[1:] if key(w) not in self.names]
        if len(words) < 4:
            return True
        return sum(w[0].isupper() for w in words) / len(words) <= 0.7

    # -- utilidades ---------------------------------------------------------
    def label(self, code: str) -> dict:
        level = {2: "departamento", 4: "provincia", 6: "distrito"}[len(code)]
        src = {2: self.deps, 4: self.provs, 6: self.dists}[len(code)][code]
        out = {"code": code, "level": level, "name": src["name"], "department": self.deps[code[:2]]["name"]}
        if len(code) == 6:
            out["province"] = self.provs[code[:4]]["name"]
        return out

    def valid(self, code: str) -> bool:
        return code in self.deps or code in self.provs or code in self.dists

    # -- etiquetado ---------------------------------------------------------
    @staticmethod
    def _list_gap(gap: str) -> bool:
        """El texto entre dos nombres es una enumeración: «, », « y », o nombres propios que no están en el
        nomenclátor («, Llullán, »)."""
        if SEP_RE.match(gap):
            return True
        parts = [p.strip() for p in re.split(r"\s*(?:,|\by\b|\be\b|-|–)\s*", gap)]
        if len(parts) < 2 or parts[0] or parts[-1]:
            return False  # tiene que empezar y terminar en separador
        inner = [p for p in parts[1:-1]]
        return 0 < len(inner) <= 4 and all(re.fullmatch(r"[A-Z][\w'’]*(?:\s+(?:de|del|la|las|los|el)?\s*[A-Z][\w'’]*){0,3}", p)
                                           for p in inner)

    def _matches(self, text: str) -> list[Match]:
        text = unicodedata.normalize("NFC", text)
        folded = fold(text)
        informative = self._case_informative(text)
        head_at = HEAD_PREFIX_RE.match(folded).end()
        #: comienzos de oración: «Fenómeno El Niño: Chosica no tiene…», «… en Lima. Chosica…»
        starts = {head_at} | {m.end() for m in re.finditer(r"(?:[:.!?]|\s[-–—|])\s+(?:[\"“«'‘]\s*)?", folded)}
        out: list[Match] = []
        prev: Optional[Match] = None
        prev_end, prev_state = -1, None  # fin del anterior y si era «anti»
        group = 0
        pos = 0
        while True:
            m = self.regex.search(folded, pos)
            if not m:
                break
            start, end = m.start(), m.end()
            raw = text[start:end]
            words = raw.split()
            pos = end
            if words[0].lower() in SMALL and words[0][:1].islower():
                # «el Alto Amazonas»: el artículo en minúscula no es parte del nombre; se busca otra vez después.
                pos = start + len(words[0]) + 1
                continue
            if not all(w[:1].isupper() for w in words if w.lower() not in SMALL):
                continue  # «mala», «santa rosa» en minúsculas: no es un nombre propio
            name = key(raw)
            codes = self.names.get(name)
            if not codes:
                continue
            gap = folded[prev_end:start] if prev_end >= 0 else None
            chained = gap is not None and self._list_gap(gap)
            # «Llaca-Casca»: parte de un nombre compuesto que no está en el nomenclátor.
            comp = re.search(r"([A-Za-z][\w'’]*)-$", folded[max(0, start - 30):start])
            comp_start = start - len(comp.group(0)) if comp else start
            if comp and key(comp.group(1)) not in self.names:
                if ANTI_RE.search(folded[max(0, comp_start - 60):comp_start]):
                    prev_end, prev_state = end, "anti"
                continue
            before = folded[max(0, comp_start - 60):comp_start]
            after = folded[end:end + 60]
            anti = ANTI_RE.search(before)
            located = bool(anti and LOCATED_RE.match(anti.group("w")) and re.search(r"\b(?:de|del)\s+$", before, re.I))
            if (anti and not located) or (chained and prev_state == "anti"):
                prev_end, prev_state = end, "anti"  # «ríos Chira y Piura»: la enumeración sigue siendo de ríos
                continue
            if DATELINE_RE.match(after):
                continue  # «Lima, 20 de octubre de 2026»: lugar de emisión del comunicado
            if NOT_PLACE_AFTER_RE.match(after) or FOREIGN_AFTER_RE.match(after):
                continue  # «pisco sour»; «Loreto, Hidalgo»
            if FOREIGN_RE.match(folded, start) and len(FOREIGN_RE.match(folded, start).group(0)) > end - start:
                continue  # «Santiago de Chile», «Santa Cruz de la Sierra»
            if informative and self._part_of_longer_name(folded, start, end, codes):
                continue
            cue, hint, container = None, None, False
            lv = LEVEL_RE.search(before)
            if lv and CONTAINER_RE.search(before):
                cue, container = "prep", True
            elif lv:
                cue, hint = "level", lv.lastgroup
            elif located:
                cue = "located"
            elif CUE_RE.search(before):
                cue = "prep"
            elif start == head_at and HEAD_END_RE.match(after):
                cue = "head"  # «Sullana: …», «Chosica – …»
            elif start in starts:
                cue = "start"  # el nombre abre la oración: «Chosica en peligro por…»
            qualifier, chain_hint = False, None
            if chained and prev is not None:
                if prev.qualifier:
                    # «Laberinto, Madre de Dios y Huepetuhe»: la enumeración sigue; el departamento era un distrito más.
                    prev.qualifier, prev.hint = False, prev.chain_hint
                    for x in out:
                        if x.group == prev.group and x.paren_dep == prev.paren_dep and x is not prev:
                            x.paren_dep = None
                    prev.paren_dep = None
                chain_hint = prev.hint if prev.cue else None
                dep_code = next((c for c in codes if len(c) == 2), None)
                if dep_code and prev.codes and all(c[:2] == dep_code for c in prev.codes if len(c) > 2) \
                        and any(len(c) > 2 for c in prev.codes) and re.match(r"^\s*(?:,|-)\s*$", gap):
                    # «Requena-Loreto», «Atico, Arequipa»: el departamento de lo anterior, no otra provincia.
                    qualifier = True
                    cue, hint = cue or "prep", "dep"
                    if prev.paren_dep is None:
                        for x in out:
                            if x.group == prev.group:
                                x.paren_dep = dep_code
                elif not cue and prev.cue:
                    cue, hint = prev.cue, prev.hint  # «en Chosica, Chaclacayo y Cieneguilla»
                    container = prev.container
                elif cue == "prep" and prev.hint and not lv:
                    hint = prev.hint  # «los distritos de Piura, de Sullana…»
            if not chained:
                group += 1
            ev_start = max(0, start - 25)
            ev = text[ev_start:end].split(" ", 1)[-1] if ev_start else text[:end]
            mm = Match(name, set(codes), cue, hint, informative, start, ev.strip(), group, None, qualifier, container,
                       chained=chained, chain_hint=chain_hint,
                       plural=bool(lv and re.search(r"(?:distritos|provincias)\s+(?:de|del)?\s*$", lv.group(0), re.I)))
            if chained and prev is not None and not mm.plural:
                mm.plural = prev.plural
            out.append(mm)
            prev, prev_end, prev_state = mm, end, None
            # «Pampas y Caja (Huancavelica)»: el departamento entre paréntesis respalda a toda la enumeración.
            pm = self.paren_re.match(folded[end:end + 40])
            if pm and folded[end:end + 40].lstrip().startswith("("):
                dep = self.dep_by_key.get(key(pm.group(1)))
                if dep:
                    for x in out:
                        if x.group == group:
                            x.paren_dep = dep
        # «en distritos de Ayacucho, Huancavelica y Cusco»: si todos los nombres de la enumeración son
        # departamentos, los nombran como contenedores, no como sus distritos capitales.
        for g in {m.group for m in out if m.plural}:
            members = [m for m in out if m.group == g]
            if all(any(len(c) == 2 for c in m.codes) for m in members):
                for m in members:
                    m.hint, m.container, m.cue = None, True, m.cue or "prep"
        for lm in self.landmark_re.finditer(folded):
            code = LANDMARKS.get(key(lm.group(0)))
            if code is None:
                continue
            out.append(Match(key(lm.group(0)), {code}, "prep", None, informative, lm.start(),
                             text[lm.start():lm.end()], -1, None, False, False, True))
        return out

    @staticmethod
    def _part_of_longer_name(folded: str, start: int, end: int, codes: set[str]) -> bool:
        """«Santiago Ojeda», «María Auxiliadora», «Lomas de Lachay», «Evo Morales»: no es el lugar."""
        nxt = re.match(r"\s+([A-Z][a-z]+)", folded[end:end + 30])
        if nxt and nxt.group(1).lower() not in QUALIFIERS and nxt.group(1).lower() not in SMALL:
            return True
        if not any(len(c) == 2 for c in codes) and re.match(r"\s+(?:de|del|de la|de los|de las)\s+[A-Z]", folded[end:end + 20]):
            return True
        pre = re.search(r"([A-Z][a-z]+)\s+$", folded[max(0, start - 30):start])
        if pre and pre.group(1).lower() not in PRE_OK:
            i = start - len(pre.group(0))
            sentence_start = i == 0 or folded[:i].rstrip()[-1:] in (".", ":", "!", "?", "¿", "¡", '"', "“", "«", "|")
            word = pre.group(1).lower()
            if not sentence_start and not CUE_RE.search(word + " ") and not LEVEL_RE.search(word + " "):
                return True
        return False

    @staticmethod
    def _resolve(codes: set[str], hint: Optional[str]) -> set[str]:
        """El nivel nombrado («provincia de Santa») o, sin palabra de nivel, el más amplio que corresponda:
        «Piura» = departamento, provincia y distrito → departamento; «Sullana» = provincia y su capital → provincia."""
        if hint == "dep" and any(len(c) == 2 for c in codes):
            return {c for c in codes if len(c) == 2}
        if hint == "prov" and any(len(c) == 4 for c in codes):
            return {c for c in codes if len(c) == 4}
        if hint == "dist" and any(len(c) == 6 for c in codes):
            return {c for c in codes if len(c) == 6}
        if hint == "city":
            provs = {c for c in codes if len(c) == 4}
            if provs:
                return provs
            if any(len(c) == 6 for c in codes):
                return {c for c in codes if len(c) == 6}
        deps = {c for c in codes if len(c) == 2}
        if deps:
            return deps
        p4 = {c[:4] for c in codes}
        if len(p4) == 1 and next(iter(p4)) in codes:
            return p4
        return codes

    @staticmethod
    def national(text: str) -> bool:
        """El texto habla del país o de varias regiones (no de un lugar concreto)."""
        for m in NATIONAL_RE.finditer(text):
            if re.match(r"(?:el|del|al|todo el|en)\s+per", m.group(0), re.I) and \
                    PERU_INSTITUTION_RE.search(text[max(0, m.start() - 60):m.start() + len(m.group(0)) - 4]):
                continue  # «Ejército del Perú», «Instituto Geofísico del Perú»
            return True
        return False

    def tag(self, texts: Iterable[str], peru_context: bool, default_dep: Optional[str] = None,
            prior: float = 0.5, outlet: str = "") -> Optional[dict]:
        """Lugares del texto. ``default_dep`` es el departamento del medio regional, que se usa (con confianza
        ``prior``) cuando el texto no nombra ninguno. Devuelve ``None`` si no hay lugar o el texto no es del Perú."""
        texts = [t for t in texts if t]
        joined = " ".join(texts)
        found = [m for t in texts for m in self._matches(t)]
        for i, m in enumerate(found):
            m.pos = i
        named_peru = bool(PERU_RE.search(joined))
        if not (peru_context or named_peru):
            return None
        if outlet and not named_peru and (FOREIGN_OUTLETS_RE.match(outlet.strip()) or FOREIGN_RE.search(outlet)
                                          or FOREIGN_DOMAIN_RE.search(outlet.strip())):
            return None  # «Jaén» de El Confidencial es Jaén de España; «Junín» de El Diario Ecuador, el de Manabí
        foreign = not named_peru and bool(FOREIGN_RE.search(unicodedata.normalize("NFC", joined)))
        picked: dict[str, Place] = {}

        def pick(code: str, conf: float, m: Match, why: str = "") -> None:
            if code not in picked or picked[code].confidence < conf:
                picked[code] = Place(code, round(conf, 2), "texto", m.evidence, {"rule": why} if why else {})

        # 1) departamentos y provincias inequívocos
        deps: list[str] = []
        provs: list[str] = []
        named: set[tuple[str, str]] = set()  # (nombre, código): «Chota» ya es la provincia
        for m in found:
            codes = self._resolve(m.codes, m.hint)
            if len(codes) != 1:
                continue
            c = next(iter(codes))
            if len(c) == 6:
                continue
            if m.landmark:
                if not foreign:
                    pick(c, 0.65, m, "lugar geográfico")
                    (deps if len(c) == 2 else provs).append(c)
                continue
            if foreign and (len(c) != 2 or m.name in WEAK):
                continue  # nombra otro país y no al Perú: solo cuentan los departamentos
            conf = 0.9 if len(c) == 2 else 0.85
            if m.name in WEAK:
                if m.paren_dep and len(c) == 4 and c[:2] == m.paren_dep:
                    ok, conf = True, 0.85
                elif len(c) == 2:
                    ok = m.cue in ("level", "head") or (m.cue == "prep" and m.informative and m.name in WEAK_DEPARTMENTS) \
                        or (c == default_dep and m.cue in ("start", "prep") and m.name in WEAK_DEPARTMENTS)
                    conf = 0.85
                else:  # «Grau», «Jorge Basadre»: provincia de nombre común, con palabra de nivel o su departamento
                    ok = m.cue == "level" or (m.cue == "prep" and any(d == c[:2] for d in deps))
                    conf = 0.85
                if not ok:
                    continue
            if m.cue == "level":
                conf = 0.95
            elif m.cue == "located":
                conf -= 0.1
            elif not m.cue and len(c) == 4:
                conf -= 0.1
            (deps if len(c) == 2 else provs).append(c)
            named.add((m.name, c))
            pick(c, conf, m)
        # «Lima» junto a otros departamentos («Áncash, Junín y Lima») es el departamento.
        if "1501" in provs and len({d for d in deps if d != "15"} | {p[:2] for p in provs if p[:2] != "15"}) >= 2:
            provs = [p for p in provs if p != "1501"]
            deps.append("15")
            pl = picked.pop("1501")
            picked.setdefault("15", Place("15", pl.confidence, "texto", pl.evidence))
        mentioned = set(deps) | {p[:2] for p in provs}
        # Un departamento que solo cierra una enumeración («Atico, Arequipa») respalda a sus distritos.
        mentioned |= {m.paren_dep for m in found if m.paren_dep}
        named_names = {n for n, _ in named}
        first_dep = {}
        for m in found:
            for c in self._resolve(m.codes, m.hint):
                if len(c) == 2 and c in mentioned:
                    first_dep.setdefault(c, m.pos)

        def collapse(cs: list[str]) -> list[str]:
            """Una provincia y su distrito capital («Lampa» provincia y distrito) cuentan como la provincia."""
            p4 = {c[:4] for c in cs}
            if len(p4) == 1 and next(iter(p4)) in cs:
                return [next(iter(p4))]
            return cs

        # 2) distritos y nombres repetidos, con el respaldo del resto del texto
        for m in found:
            if foreign or m.landmark or m.qualifier:
                continue
            cands = sorted(self._resolve(m.codes, m.hint))
            if len(cands) == 1 and len(cands[0]) <= 4:
                continue  # ya considerado arriba
            weak = m.name in WEAK
            if m.paren_dep:
                local = [c for c in m.codes if c[:2] == m.paren_dep and len(c) > 2]
                local = [c for c in local if len(c) == 6] or local
                if len(local) == 1:
                    pick(local[0], 0.9, m, "departamento entre paréntesis")
                    continue
                if local and len({c[:4] for c in local}) == 1:
                    pick(local[0][:4], 0.8, m, "departamento entre paréntesis")
                    continue
            if weak and m.cue != "level" and not (m.name in WEAK_WITH_DEPARTMENT and m.cue in ("prep", "head")
                                                   and any(c[:2] in mentioned for c in cands)) \
                    and not (m.chained and m.cue and any(c[:2] in mentioned for c in cands)):
                continue  # «Huánuco, Ambo y Leoncio Prado»: un nombre común en una enumeración de su departamento sí
            if m.name in named_names and any(c in provs or c in deps for c in m.codes):
                # «Chota» ya es la provincia: no el homónimo de otro departamento; pero «distritos de …, Madre
                # de Dios y Huepetuhe» sí es el distrito aunque el titular nombre el departamento.
                if m.hint != "dist":
                    continue
            if m.name in self.minor_alias and not m.informative and m.cue != "level":
                continue  # en un titular en mayúsculas «DE MOSCA» no es el pueblo de Mosca
            by_prov = [c for c in cands if c[:4] in provs and c not in provs]
            by_dep = [c for c in cands if c[:2] in mentioned and c not in provs]
            backed = collapse(by_prov or by_dep)
            if len({c[:2] for c in backed}) > 1 and not by_prov:
                # «Huancavelica: huaico en Anco … vía Huancayo–Ayacucho»: el departamento nombrado primero.
                ranked = sorted(backed, key=lambda c: first_dep.get(c[:2], 99))
                if first_dep.get(ranked[0][:2], 99) < first_dep.get(ranked[1][:2], 99):
                    backed = [c for c in backed if c[:2] == ranked[0][:2]]
            if backed:
                conf = 0.9 if by_prov else 0.85
                if m.cue == "level":
                    conf += 0.05
                if not m.cue:
                    conf -= 0.1
                if len(backed) == 1:
                    pick(backed[0], conf, m, "respaldado por su provincia" if by_prov else "respaldado por su departamento")
                elif len({c[:4] for c in backed}) == 1:
                    pick(backed[0][:4], conf - 0.05, m, "respaldado por su departamento")
                continue
            local = collapse([c for c in cands if default_dep and c[:2] == default_dep])
            if m.name in self.minor_alias and m.cue != "level":
                if len(local) == 1 and m.cue:
                    pick(local[0], 0.7, m, "homónimo del departamento del medio")
                continue
            if len(local) == 1 and m.cue:
                pick(local[0], 0.75, m, "homónimo del departamento del medio")  # medio regional
                continue
            if len(cands) != 1 or not m.cue:
                continue
            c = cands[0]
            if mentioned and c[:2] not in mentioned:
                continue  # el texto nombra otro departamento: es un homónimo (un anexo, un estadio…)
            if m.cue != "level":
                if default_dep and c[:2] != default_dep:
                    continue
                if not m.informative and m.cue in ("prep", "start"):
                    continue  # «DAMNIFICADOS CRUZAN EL RÍO EN BALSAS»
            conf = 0.85 if m.cue == "level" else 0.75 if m.cue in ("prep", "head") else 0.7
            if m.cue == "located":
                conf = 0.7
            if len(c) == 6 and len(self.names.get(m.name, ())) == 1 and m.name not in self.minor_alias:
                conf += 0.05  # nombre único en el país
            pick(c, conf, m, "nombre único")
        if not picked and not foreign:
            for dm in DEMONYM_RE.finditer(fold(joined)):
                code = DEMONYMS.get((dm.group(1) or "").lower()) or _DEMONYM_ES.get((dm.group(2) or "").lower())
                if code and self.valid(code):
                    picked[code] = Place(code, 0.55, "texto", joined[max(0, dm.start() - 20):dm.end()].strip(),
                                         {"rule": "gentilicio"})
        if not picked:
            if default_dep and not foreign and not self.national(joined):
                pl = self.label(default_dep)
                pl.update(confidence=round(prior, 2), method="medio", evidence="departamento del medio")
                pub = prior >= PUBLISH_MIN
                return {"places": [pl] if pub else [], "departments": [default_dep] if pub else [],
                        "suggested": [] if pub else [pl], "source": "medio", "confidence": pl["confidence"]}
            return None
        order = {}
        for m in found:
            for c in self._resolve(m.codes, m.hint) | m.codes:
                order.setdefault(c, m.pos)
        codes = sorted(picked, key=lambda c: order.get(c, order.get(c[:4], order.get(c[:2], 99))))
        codes = [c for c in codes if self.valid(c)]
        # «provincia de Calca» y «distrito de Calca»: con la provincia basta.
        codes = [c for c in codes if not (len(c) == 6 and c[:4] in codes and key(self.dists[c]["name"]) == key(self.provs[c[:4]]["name"]))]
        if not codes:
            return None
        # El departamento implícito en algo más específico sobra (Piura si ya está Sullana); las provincias
        # nombradas se conservan («Paracas y Pisco»).
        specific = [c for c in codes if not (len(c) == 2 and any(o != c and o.startswith(c) for o in codes))
                    and not (len(c) == 4 and c not in provs and any(o != c and o.startswith(c) for o in codes))]
        places = []
        for c in specific:
            pl = self.label(c)
            p = picked[c]
            pl.update(confidence=p.confidence, method=p.method, evidence=p.evidence, **p.extra)
            places.append(pl)
        pub = [p for p in places if p["confidence"] >= PUBLISH_MIN]
        low = [p for p in places if p["confidence"] < PUBLISH_MIN]
        return {"places": pub, "departments": list(dict.fromkeys(c[:2] for c in codes if picked[c].confidence >= PUBLISH_MIN)),
                "suggested": low, "source": "texto", "confidence": min((p["confidence"] for p in pub), default=None)}

    # -- campos estructurados -------------------------------------------------
    def find(self, name: str, level: str, within: Optional[str] = None) -> list[str]:
        """Códigos cuyo nombre (o capital, o alias) es ``name`` en el nivel dado, dentro de ``within``."""
        k = key(re.sub(r"^(?:dist|prov|depa?)\.?\s*", "", name or "", flags=re.I))
        n = {"departamento": 2, "provincia": 4, "distrito": 6}[level]
        src = {2: self.deps, 4: self.provs, 6: self.dists}[n]
        hits = [c for c, x in src.items() if key(x["name"]) == k and (not within or c.startswith(within))]
        if not hits:
            hits = [c for c in self.names.get(k, ()) if len(c) == n and (not within or c.startswith(within))]
        return hits

    def from_admin(self, dist: str = "", prov: str = "", dep: str = "") -> Optional[str]:
        """El código más fino que se puede afirmar a partir de nombres de distrito, provincia y departamento."""
        d = self.find(dep, "departamento") if dep else []
        d = d[0] if len(d) == 1 else None
        p = self.find(prov, "provincia", d) if prov else []
        p = p[0] if len(p) == 1 else None
        x = self.find(dist, "distrito", p or d) if dist else []
        if len(x) == 1:
            return x[0]
        return p or d

    _ADMIN_RE = re.compile(
        r"(?:distrito\s+de\s+(?P<dist>[^,;()]+?)\s*,\s*)?(?:provincia\s+de\s+(?P<prov>[^,;()]+?)\s*,\s*)?"
        r"departamento\s+de\s+(?P<dep>[^,;()]+?)\s*(?=[,;()]|$)", re.I)

    def admin_codes(self, texts: Iterable[str]) -> list[tuple[str, str]]:
        """«distrito de X, provincia de Y, departamento de Z» (campos de las capas del SENAMHI) → códigos."""
        out = []
        for t in texts:
            for m in self._ADMIN_RE.finditer(t or ""):
                c = self.from_admin(m.group("dist") or "", m.group("prov") or "", m.group("dep") or "")
                if c:
                    out.append((c, m.group(0).strip()))
        return out


@lru_cache(maxsize=1)
def gazetteer() -> Gazetteer:
    return Gazetteer(json.loads(DATA.read_text(encoding="utf-8")))


def department_names() -> dict[str, str]:
    return {c: d["name"] for c, d in gazetteer().deps.items()}


# --- Ubicación de una nota o un aviso -------------------------------------------------

#: Confianza del departamento del medio cuando el texto no nombra ninguno.
PRIOR = {"gobierno": 0.6, "agregador": 0.35}
PRIOR_DEFAULT = 0.5


def _place(gz: Gazetteer, code: str, conf: float, method: str, evidence: str) -> dict:
    p = gz.label(code)
    p.update(confidence=round(conf, 2), method=method, evidence=evidence[:120])
    return p


def _finish(gz: Gazetteer, places: list[dict], suggested: list[dict], country: Optional[str], scope: Optional[str]) -> dict:
    # Sin repetir y sin el ancestro de algo más específico.
    seen: dict[str, dict] = {}
    for p in places:
        if p["code"] not in seen or seen[p["code"]]["confidence"] < p["confidence"]:
            seen[p["code"]] = p
    codes = list(seen)
    places = [seen[c] for c in codes if not any(o != c and o.startswith(c) for o in codes)]
    deps = list(dict.fromkeys(c[:2] for c in codes))
    if scope is None:
        scope = None if not places else "local" if any(p["level"] != "departamento" for p in places) else \
            "regional" if len(deps) <= 3 else "nacional"
    methods = list(dict.fromkeys(p["method"] for p in places))
    return {
        "country": country, "scope": scope, "places": places, "departments": deps,
        "suggested": [s for s in suggested if s["code"] not in seen],
        "confidence": min((p["confidence"] for p in places), default=None),
        "method": "+".join(methods) if methods else None, "v": GEO_VERSION,
    }


def locate_item(entry: dict, feed=None, region: str = "peru") -> Optional[dict]:
    """Ubica una entrada de feed o una nota ya guardada. Devuelve el objeto ``geo`` (ver arquitectura) o ``None``.

    Usa, en este orden: códigos UBIGEO de la fuente (``ubigeo``), coordenadas (``coords``: [[lat, lon], …]),
    lugares en campos propios (``geo``: textos «distrito de X, provincia de Y, departamento de Z»), y el texto
    (titular, resumen y, en medios nacionales, las categorías)."""
    gz = gazetteer()
    dep = getattr(feed, "department", None)
    kind = getattr(feed, "kind", None)
    places: list[dict] = []
    for c in entry.get("ubigeo") or []:
        c = str(c).strip()
        if gz.valid(c):
            places.append(_place(gz, c, 0.97, "campo", f"UBIGEO {c}"))
    for pt in entry.get("coords") or []:
        try:
            lat, lon = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError):
            continue
        from .limites import locate as locate_point

        hit = locate_point(lat, lon)
        if hit:
            places.append(_place(gz, hit["code"], hit["confidence"], "coordenadas",
                                 f"{lat:.3f}, {lon:.3f}" + (f" ({hit['note']})" if hit.get("note") else "")))
    texts = [entry.get("title") or "", entry.get("summary") or ""]
    outlet = (entry.get("outlet") or "").strip()
    if len(outlet) >= 4:  # Google Noticias pega el nombre del medio al resumen («… Tumbes de Miércoles»)
        texts = [t.replace(outlet, " ").strip() for t in texts]
    if entry.get("categories") and not dep:
        texts.append(" · ".join(entry["categories"]))
    if places:
        return _finish(gz, places, [], "PE", None)
    if entry.get("geo"):
        admin = gz.admin_codes(entry["geo"])
        if admin:
            return _finish(gz, [_place(gz, c, 0.95, "campo", ev) for c, ev in admin], [], "PE", None)
        texts = list(entry["geo"])
    tag = gz.tag(texts, peru_context=region == "peru", default_dep=dep,
                 prior=PRIOR.get(kind or "", PRIOR_DEFAULT), outlet=entry.get("outlet") or "")
    if not tag:
        joined = " ".join(t for t in texts if t)
        if region != "peru" and not PERU_RE.search(joined):
            return {"country": None, "scope": "internacional", "places": [], "departments": [], "suggested": [],
                    "confidence": None, "method": None, "v": GEO_VERSION}
        scope = "nacional" if gz.national(joined) else None
        return {"country": "PE" if region == "peru" or PERU_RE.search(joined) else None, "scope": scope,
                "places": [], "departments": [], "suggested": [], "confidence": None, "method": None, "v": GEO_VERSION}
    return _finish(gz, tag["places"], tag.get("suggested") or [], "PE", None)


def legacy_fields(g: Optional[dict]) -> dict:
    """Los campos que el sitio ya usa (``departments``, ``places``, ``geoSource``), a partir del objeto ``geo``."""
    if not g or not g.get("places"):
        return {}
    m = g.get("method") or ""
    return {"departments": g["departments"],
            "places": [{k: p[k] for k in ("code", "level", "name")} for p in g["places"]],
            "geoSource": "correccion" if "correccion" in m else "medio" if m == "medio" else "texto"}
