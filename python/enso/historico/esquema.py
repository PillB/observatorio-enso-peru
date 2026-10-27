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
    "PrecisionGeo",        # capital-distrito | capital-provincia | capital-departamento | coordenada-fuente
    "Region",              # macrorregión INEI (Norte, Centro, Sur, Oriente, Lima Metropolitana)
    "AltitudCapital",      # m s. n. m. de la capital del distrito
    "FaseENSO",            # El Niño costero | La Niña costera | Neutro (ICEN del mes)
    "EventoENSO",          # «El Niño costero 1997-98 (extraordinario)»
    "ICEN", "ONI",         # valor del mes (°C)
    "AtribucionENSO",      # fuente | curado | ventana-icen | ninguna
    "Fallecidos", "Desaparecidos", "Heridos", "Afectados", "Damnificados", "Evacuados", "Reubicados",
    "Desplazados",         # personas desplazadas según el IDMC (calculadas de las viviendas inhabitables del INDECI)
    "ViviendasDestruidas", "ViviendasAfectadas", "HectareasCultivo", "KmVias", "CentrosEducativos",
    "CentrosSalud", "PerdidasUSD",
    "ImpactoReportado",    # si | no
    "ImpactoEnTotales",    # no: resumen curado de un área y evento que otra fuente ya detalla (no se suma dos veces)
    "FuenteCita",          # la cita original (periódico y fecha, INDECI…) en texto legible
    "Licencia",
    "Confianza",           # alta | media | baja (resumen de la calidad de fecha, lugar y tipo)
    "FechaTipo",           # evento | informe (del primer reporte) | publicacion (de la nota) | texto (la que cita la nota)
    "Corroboracion",       # cuántos reportes o notas de otras fuentes cuentan el mismo evento (enlace.link)
    "OrigenesCorroboran",  # de qué fuentes son (coen, prensa…)
    "FuentesAdicionales",  # sus enlaces, separados por « | » (hasta 10)
]

COLUMNS = TEAM_COLUMNS + EXTRA_COLUMNS
IMPACT_COLUMNS = ["Fallecidos", "Desaparecidos", "Heridos", "Afectados", "Damnificados", "Evacuados", "Reubicados",
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
