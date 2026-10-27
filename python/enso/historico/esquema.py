"""Columnas del catálogo histórico y clasificación de peligros.

Las 13 primeras columnas son las que pidió el equipo de prevención de desastres para su tablero, con
sus nombres exactos; las demás son metadatos para análisis de recurrencia y riesgo, procedencia y
calidad. Todas las filas tienen todas las columnas (vacías si la fuente no da el dato: nunca se
inventa un valor; ``0`` significa «la fuente dice cero» solo en las columnas de impacto con
``ImpactoReportado = si``).
"""

from __future__ import annotations

import re
from typing import Optional

from ..geo import key

__all__ = ["key"]

#: Columnas del tablero del equipo de prevención (nombres exactos, en este orden).
TEAM_COLUMNS = [
    "Date", "DangerType", "Ubicacion", "Distrito", "Provincia", "Departamento", "Descripción",
    "DuraciónEvento", "Ubigeo", "TipoEvento", "Fuente", "Latitud", "Longitud",
]

#: Metadatos del observatorio.
EXTRA_COLUMNS = [
    "Id",                  # estable: <origen>-<id en la fuente>
    "Origen",              # desinventar | curado | …
    "IdFuente",            # identificador del registro en su fuente
    "FechaFin",            # Date + duración − 1, si se conoce la duración
    "PrecisionFecha",      # dia | mes | anio
    "Anio", "Mes",
    "AnioHidrologico",     # julio a junio: «1997-98»; agrupa la temporada de lluvias completa
    "GrupoPeligro",        # hidrometeorologico | climatologico | geologico-hidro | biologico
    "PeligroFuente",       # el tipo tal como lo nombra la fuente
    "DangerTypeMetodo",    # fuente | texto | causa | por-omision
    "CausaFuente",         # la causa tal como la nombra la fuente
    "NivelUbigeo",         # distrito | provincia | departamento
    "PrecisionGeo",        # coordenada-fuente | centro-poblado | capital-distrito | interior-distrito | capital-provincia | capital-departamento
    "Lugar",               # centro(s) poblado(s) oficiales (INEI, IGN) que nombra la fuente, dentro del distrito
    "LugarCodigo",         # código de centro poblado del INEI (10 dígitos) del primero
    "RadioKm",             # incertidumbre del punto de un centro poblado
    "Cuenca", "CuencaCodigo",  # unidad hidrográfica de la ANA (Pfafstetter) del punto, o del distrito si cae casi entero en una
    "Region",              # macrorregión INEI (Norte, Centro, Sur, Oriente, Lima Metropolitana)
    "AltitudCapital",      # m s. n. m. de la capital del distrito
    "FaseENSO",            # El Niño costero | La Niña costera | Neutro (ICEN del mes)
    "EventoENSO",          # «El Niño costero 1997-98 (extraordinario)»
    "ICEN", "ONI",         # valor del mes (°C)
    "AtribucionENSO",      # fuente | curado | ventana-icen | pendiente | ninguna
    "Fallecidos", "Desaparecidos", "Heridos", "Afectados", "Damnificados", "Evacuados", "Reubicados",
    "Desplazados",         # personas desplazadas según el IDMC (calculadas de las viviendas inhabitables del INDECI)
    "ViviendasDestruidas", "ViviendasAfectadas", "HectareasCultivo", "KmVias", "CentrosEducativos",
    "CentrosSalud", "PerdidasUSD",
    "ImpactoReportado",    # si | no
    "ImpactoEnTotales",    # si | no (resumen curado de un área y evento que otra fuente ya detalla: no se suma dos veces)
    "FuenteCita",          # la cita original (periódico y fecha, INDECI…) en texto legible
    "Licencia",
    "Confianza",           # alta | media | baja (resumen de la calidad de fecha, lugar y tipo)
    "FechaTipo",           # evento | informe (del primer reporte) | publicacion (de la nota) | texto (la que cita la nota)
    "Corroboracion",       # cuántos reportes o notas de otras fuentes cuentan el mismo evento (enlace.link)
    "OrigenesCorroboran",  # de qué fuentes son (coen, prensa…)
    "FuentesAdicionales",  # sus enlaces, separados por « | » (hasta 10)
]

COLUMNS = TEAM_COLUMNS + EXTRA_COLUMNS

#: Diccionario de datos (``diccionario.csv``, para cargar el catálogo en un tablero): columna → (tipo, qué dice,
#: valores o regla de llenado). El porcentaje de filas con dato, total y por fuente, lo calcula la construcción.
_IMPACT_DOC = ("entero", "{} según la fuente", "Vacío = la fuente no lo reporta (no es cero)")
COLUMN_DOCS = {
    "Date": ("fecha AAAA-MM-DD", "Fecha de inicio del evento (o de publicación, ver FechaTipo)",
             "Si la fuente solo da el mes, el día 01; si solo el año, el 01-01 (ver PrecisionFecha)"),
    "DangerType": ("texto", "Tipo de peligro, con el vocabulario del tablero del equipo",
                   "Uno de los valores de DANGER_TYPES; «Inundacion» = la fuente no dice si fue fluvial o pluvial"),
    "Ubicacion": ("texto", "El lugar más fino que da la fuente (sector, caserío, localidad, punto crítico)",
                  "Vacío si la fuente solo da el distrito (el SINPAD desde 2019 no da más)"),
    "Distrito": ("texto", "Nombre oficial del INEI", "Vacío si el registro es de provincia o departamento"),
    "Provincia": ("texto", "Nombre oficial del INEI", "Vacío si el registro es de todo un departamento"),
    "Departamento": ("texto", "Nombre oficial del INEI", "Siempre lleno"),
    "Descripción": ("texto", "Qué pasó, con la causa y los daños que describe la fuente",
                    "Las notas de prensa traen un extracto de hasta 200 caracteres y el enlace"),
    "DuraciónEvento": ("entero (días)", "Duración del evento", "Solo si la fuente la da; vacío si no (no se estima)"),
    "Ubigeo": ("texto (6, 4 o 2 dígitos)", "Código vigente del INEI del área del registro",
               "6 = distrito, 4 = provincia, 2 = departamento (ver NivelUbigeo). Léalo como texto: lleva ceros a la "
               "izquierda («010101»)"),
    "TipoEvento": ("texto", "Evento ENSO o temporada a la que pertenece",
                   "FEN 1997-98, Niño Costero 2017, Ciclón Yaku 2023…; fuera de ellos, Temporada de lluvias, Temporada "
                   "de heladas y friaje o Sin asociación ENSO; ICEN pendiente si el mes es posterior al último ICEN "
                   "publicado y la fuente no atribuye el evento a El Niño o La Niña (ver AtribucionENSO)"),
    "Fuente": ("URL", "Enlace al registro en su fuente o a la fuente",
               "Siempre lleno; enlaza a la fuente cuando no tiene una página por registro (DesInventar, capas de ArcGIS)"),
    "Latitud": ("decimal (grados)", "Punto de la fuente si cae en el distrito asignado y no es un punto por defecto; "
                "si no, el centro poblado que nombra la fuente; si no, la capital del área",
                "Ver PrecisionGeo. Las filas de provincia o departamento llevan la capital de la provincia o del "
                "departamento: en un mapa de puntos se agrupan en las capitales y no son el lugar exacto"),
    "Longitud": ("decimal (grados)", "Igual que Latitud", "Ver PrecisionGeo"),
    "Id": ("texto", "Identificador estable del registro", "<origen>-<id en la fuente>; no se repite"),
    "Origen": ("texto", "Fuente del registro",
               "desinventar, sinpad, coen, idmc, prensa, hemeroteca, glof, nasa-glc, curado. Las filas del IDMC que "
               "quedan son las que no tienen gemela en el SINPAD: casi todas por departamento y mes, resúmenes de "
               "desplazamiento más que eventos"),
    "IdFuente": ("texto", "Identificador del registro en su fuente", ""),
    "FechaFin": ("fecha AAAA-MM-DD", "Último día del evento", "Date + DuraciónEvento − 1, si se conoce la duración"),
    "PrecisionFecha": ("texto", "Qué tan precisa es Date", "dia, mes o anio"),
    "Anio": ("entero", "Año calendario de Date", ""),
    "Mes": ("entero", "Mes de Date", "Vacío si solo se sabe el año"),
    "AnioHidrologico": ("texto", "Temporada de julio a junio («1997-98»)", "Vacío si solo se sabe el año"),
    "GrupoPeligro": ("texto", "Grupo del peligro", "hidrometeorologico, climatologico, geologico-hidro, biologico"),
    "PeligroFuente": ("texto", "El tipo de peligro tal como lo nombra la fuente", ""),
    "DangerTypeMetodo": ("texto", "Cómo se eligió DangerType",
                         "fuente (la fuente lo dice), texto (por la descripción), causa, por-omision"),
    "CausaFuente": ("texto", "La causa tal como la nombra la fuente", ""),
    "NivelUbigeo": ("texto", "Nivel del área del registro", "distrito, provincia o departamento"),
    "PrecisionGeo": ("texto", "De dónde salen Latitud y Longitud",
                     "coordenada-fuente (el punto que da la fuente, dentro del distrito; no la capital ni un punto que la "
                     "fuente repite para todo el distrito), centro-poblado (el centro poblado que nombra la fuente: INEI "
                     "2017 o IGN, ver Lugar y RadioKm), capital-distrito, interior-distrito (un punto dentro del distrito, "
                     "lejos de sus bordes: el nomenclátor no trae su capital), capital-provincia o capital-departamento"),
    "Lugar": ("texto", "Centro(s) poblado(s) oficiales que nombra la fuente (Ubicacion o Descripción), dentro del distrito",
              "Nombre del INEI o del IGN; varios separados por « · ». Vacío si la fuente no nombra uno que exista en el "
              "distrito, o si el nombre se repite en el distrito (homónimos: no se adivina)"),
    "LugarCodigo": ("texto (10 dígitos)", "Código de centro poblado del INEI del primer Lugar",
                    "Léalo como texto. Vacío si el lugar viene solo del IGN, sin código"),
    "RadioKm": ("decimal (km)", "Incertidumbre del punto cuando PrecisionGeo es centro-poblado",
                "1 km (5 km si el INEI y el IGN ubican ese centro poblado a más de 5 km); con varios lugares, la distancia "
                "del punto medio al más lejano más 1 km"),
    "Cuenca": ("texto", "Unidad hidrográfica de la ANA (cuenca o intercuenca, Pfafstetter)",
               "La del punto si PrecisionGeo es coordenada-fuente o centro-poblado; si no, la del distrito cuando el 80 % "
               "o más de él está en una sola; vacío en las demás"),
    "CuencaCodigo": ("texto", "Código Pfafstetter de la ANA de la Cuenca", "Léalo como texto"),
    "Region": ("texto", "Macrorregión del INEI", "Norte, Centro, Sur, Oriente, Lima Metropolitana"),
    "AltitudCapital": ("entero (m s. n. m.)", "Altitud de la capital del distrito", ""),
    "FaseENSO": ("texto", "Fase costera del mes según el ICEN", "El Niño costero, La Niña costera, Neutro"),
    "EventoENSO": ("texto", "Evento del ICEN en curso ese mes", "«El Niño costero 1997-98 (extraordinario)»"),
    "ICEN": ("decimal (°C)", "Índice Costero El Niño del mes (ENFEN/IGP)", "Vacío si solo se sabe el año"),
    "ONI": ("decimal (°C)", "Índice Oceánico El Niño del mes (NOAA/CPC)", "Vacío si solo se sabe el año"),
    "AtribucionENSO": ("texto", "De dónde sale TipoEvento",
                       "fuente, curado, ventana-icen (la fecha cae en un evento del ICEN), pendiente (el ICEN del mes "
                       "aún no se publica) o ninguna; que un registro caiga en un Niño no prueba que el Niño lo causó"),
    **{c: (_IMPACT_DOC[0], _IMPACT_DOC[1].format(c), _IMPACT_DOC[2]) for c in (
        "Fallecidos", "Desaparecidos", "Heridos", "Afectados", "Damnificados", "Evacuados", "Reubicados",
        "ViviendasDestruidas", "ViviendasAfectadas", "CentrosEducativos", "CentrosSalud")},
    "Desplazados": ("entero", "Personas desplazadas según el IDMC (calculadas de las viviendas inhabitables del INDECI)",
                    "Vacío = la fuente no lo reporta"),
    "HectareasCultivo": ("decimal", "Hectáreas de cultivo o cobertura natural dañadas", "Vacío = la fuente no lo reporta"),
    "KmVias": ("decimal", "Kilómetros de vías dañadas", "Vacío = la fuente no lo reporta"),
    "PerdidasUSD": ("decimal", "Pérdidas en dólares según la fuente", "Vacío = la fuente no lo reporta"),
    "ImpactoReportado": ("texto", "Si la fuente reporta algún impacto", "si o no"),
    "ImpactoEnTotales": ("texto", "Si los impactos de la fila entran a las sumas",
                         "si; no = resumen curado de un área y evento que otra fuente ya detalla (no se suma dos veces)"),
    "FuenteCita": ("texto", "La cita original legible (institución, periódico y fecha…)", ""),
    "Licencia": ("texto", "Condiciones de uso de la fuente", "Ver docs/atribucion-licencias.md"),
    "Confianza": ("texto", "Resumen de la calidad de fecha, lugar y tipo",
                  "alta (distrito, día y tipo de la fuente o del texto), media (provincia o mejor y mes), baja (el "
                  "resto); nunca alta si la fecha es la de un reporte o una publicación (FechaTipo)"),
    "FechaTipo": ("texto", "De qué es la fecha Date",
                  "evento; informe (primer reporte del COEN); publicacion (de la nota); texto (la que cita la nota)"),
    "Corroboracion": ("entero", "Cuántos reportes o notas de otras fuentes cuentan el mismo evento", ""),
    "OrigenesCorroboran": ("texto", "De qué fuentes son esos reportes o notas", "Separados por coma"),
    "FuentesAdicionales": ("texto", "Sus enlaces", "Separados por « | », hasta 10"),
}
assert set(COLUMN_DOCS) == set(COLUMNS), set(COLUMNS) ^ set(COLUMN_DOCS)
IMPACT_COLUMNS =["Fallecidos", "Desaparecidos", "Heridos", "Afectados", "Damnificados", "Evacuados", "Reubicados",
                  "Desplazados", "ViviendasDestruidas", "ViviendasAfectadas", "HectareasCultivo", "KmVias", "CentrosEducativos",
                  "CentrosSalud", "PerdidasUSD"]

#: Nombre legible de cada columna de impacto (para descripciones).
IMPACT_LABELS = {
    "Fallecidos": "fallecidos", "Desaparecidos": "desaparecidos", "Heridos": "heridos", "Afectados": "personas afectadas",
    "Damnificados": "damnificados", "Evacuados": "evacuados", "Reubicados": "reubicados", "Desplazados": "desplazados",
    "ViviendasDestruidas": "viviendas destruidas o colapsadas", "ViviendasAfectadas": "viviendas afectadas o inhabitables",
    "HectareasCultivo": "hectáreas de cultivo o cobertura natural", "KmVias": "km de vías",
    "CentrosEducativos": "locales educativos", "CentrosSalud": "establecimientos de salud", "PerdidasUSD": "pérdidas (US$)",
}

# ---------------------------------------------------------------------------
# Peligros
# ---------------------------------------------------------------------------
#: Vocabulario de DangerType: los valores del equipo (sin tildes, como su tablero) y los adicionales
#: necesarios para no forzar un tipo que la fuente no dice. Valor → (grupo, código IRDR).
DANGER_TYPES = {
    "Inundacion fluvial": ("hidrometeorologico", "HY-FL-RIV"),
    "Inundacion pluvial": ("hidrometeorologico", "HY-FL-FLA"),
    "Inundacion": ("hidrometeorologico", "HY-FL"),
    "Desborde de rio": ("hidrometeorologico", "HY-FL-RIV"),
    "Huayco/Alud": ("geologico-hidro", "HY-MM-DEB"),
    "Deslizamiento": ("geologico-hidro", "HY-MM-LAN"),
    "Lluvias intensas": ("hidrometeorologico", "MET-CS-RAI"),
    "Oleaje anomalo": ("hidrometeorologico", "HY-WA-SWE"),
    "Erosion costera": ("hidrometeorologico", "HY-WA"),
    "Nevada": ("hidrometeorologico", "MET-ET-SEV"),
    "Granizada": ("hidrometeorologico", "MET-CS-HAI"),
    "Helada/Friaje": ("climatologico", "MET-ET-CW"),
    "Ola de calor": ("climatologico", "MET-ET-HW"),
    "Vientos fuertes": ("hidrometeorologico", "MET-CS-WIN"),
    "Tormenta electrica": ("hidrometeorologico", "MET-CS-LIG"),
    "Tormenta": ("hidrometeorologico", "MET-CS"),  # la fuente no dice si fue lluvia, viento o rayos
    "Sequias": ("climatologico", "CLI-DR"),
    "Incendio forestal": ("climatologico", "CLI-WF-FOR"),
    "Erosion": ("geologico-hidro", "HY-MM"),
    "Epidemia": ("biologico", "BIO-EP"),
    "Plaga": ("biologico", "BIO-IN"),
}

#: Nombre legible (con tildes) de cada DangerType, para descripciones.
DANGER_LABELS = {
    "Inundacion fluvial": "Inundación fluvial", "Inundacion pluvial": "Inundación pluvial",
    "Inundacion": "Inundación", "Desborde de rio": "Desborde de río", "Huayco/Alud": "Huayco o alud",
    "Oleaje anomalo": "Oleaje anómalo", "Erosion costera": "Erosión costera", "Helada/Friaje": "Helada o friaje",
    "Tormenta electrica": "Tormenta eléctrica", "Sequias": "Sequía", "Erosion": "Erosión",
}

#: Tipos de DesInventar que entran al catálogo (los demás son tecnológicos o sísmicos: no dependen
#: del clima). Epidemias y plagas solo si la fuente las atribuye a El Niño o a lluvias.
DESINVENTAR_TYPES = {
    "Inundación": "Inundacion", "Lluvias": "Lluvias intensas", "Aluvión (Huayco)": "Huayco/Alud",
    "Avenida torrencial": "Huayco/Alud", "Alud": "Huayco/Alud", "Deslizamiento": "Deslizamiento",
    "Marejada": "Oleaje anomalo", "Cambio línea de costa": "Erosion costera", "Nevada": "Nevada",
    "Granizada": "Granizada", "Helada": "Helada/Friaje", "Ola de frío": "Helada/Friaje",
    "Ola de calor": "Ola de calor", "Vendaval": "Vientos fuertes", "Tempestad": "Vientos fuertes",
    "Tormenta eléctrica": "Tormenta electrica", "Sequía": "Sequias", "Incendio forestal": "Incendio forestal",
    "Erosión": "Erosion", "Sedimentación": "Erosion", "Epidemia": "Epidemia", "Plaga": "Plaga",
}
CLIMATE_CAUSES = {"El Niño", "La Niña", "Lluvias", "Condiciones atmosféricas", "Desbordamiento", "Inundación",
                  "Sequía", "Vendaval", "Tempestad"}

_RIVER_OVERFLOW = re.compile(r"\bdesbord\w*(?: de| del)?(?: los| las| la| el| sus)?(?: aguas del?)?(?: rio| rios| quebrada| laguna| cauce| caudal)"
                             r"|\brio\b[^.;]{0,40}\bdesbord|\bcolapso de (?:la |las )?defensas?|\brompi\w* (?:de )?(?:la |las )?defensas?")
_RIVER = re.compile(r"\brio\b|\brios\b|\bcrecida|\bcaudal|\bquebrada|\bfluvial|\briberen|\bcrecient")
_RAIN_FLOOD = re.compile(r"\blluvi|\bprecipitac|\baniego|\bempoz|\bdrenaje|\bpluvial|\btormenta")
_HUAYCO = re.compile(r"\bhuayco|\bhuaico|\bhuaycos|\bhuaicos|\baluvi|\blloclla|\bflujo de (?:lodo|detritos)")


def classify_flood(texts: list[str], cause: str) -> tuple[str, str]:
    """Inundación de la fuente → fluvial, pluvial o desborde, por el texto o la causa.

    Devuelve (DangerType, método). Sin pistas queda «Inundacion»: no se adivina."""
    t = key(" ".join(x for x in texts if x))
    if _RIVER_OVERFLOW.search(t):
        return "Desborde de rio", "texto"
    if _RIVER.search(t):
        return "Inundacion fluvial", "texto"
    if _RAIN_FLOOD.search(t):
        return "Inundacion pluvial", "texto"
    if cause == "Desbordamiento":
        return "Desborde de rio", "causa"
    if cause in ("Lluvias", "Condiciones atmosféricas"):
        return "Inundacion pluvial", "causa"
    return "Inundacion", "por-omision"


def danger_group(dt: str) -> str:
    return DANGER_TYPES.get(dt, ("otro", ""))[0]


def irdr_code(dt: str) -> str:
    return DANGER_TYPES.get(dt, ("", ""))[1]


def hydro_year(year: int, month: Optional[int]) -> str:
    """Año hidrológico julio–junio: la temporada de lluvias de diciembre a abril queda en un solo año."""
    if not month:
        return ""
    y0 = year if month >= 7 else year - 1
    return f"{y0}-{str(y0 + 1)[2:]}"


def is_huayco_text(text: str) -> bool:
    return bool(_HUAYCO.search(key(text)))
