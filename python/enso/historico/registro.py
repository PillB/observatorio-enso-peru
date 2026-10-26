"""Arma una fila completa del catálogo (``esquema.COLUMNS``) a partir de lo que da cada fuente.

Cada lector entrega lo propio de su fuente (fecha, tipo, lugar, descripción, impactos, cita); aquí se
completan los campos derivados igual para todas: nombres oficiales y coordenadas del UBIGEO,
macrorregión, altitud, año hidrológico, grupo de peligro, fase ENSO, ``TipoEvento`` y confianza.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from . import esquema as E

LEVEL = {2: "departamento", 4: "provincia", 6: "distrito"}


def make(territory, calendar, *, code: str, day: str, precision: str, danger: str, origin: str, source_id: str,
         url: str, cite: str, license: str, description: str = "", place: str = "", duration: Optional[int] = None,
         source_type: str = "", danger_method: str = "fuente", cause: str = "", latlon: Optional[tuple] = None,
         impacts: Optional[dict] = None, tipo: Optional[str] = None, confidence: Optional[str] = None) -> dict:
    """``day`` es «AAAA-MM-DD» (con «-01» si solo se sabe el mes, «-01-01» si solo el año)."""
    y, m = int(day[:4]), int(day[5:7])
    month_known = precision in ("dia", "mes")
    dep, prov, dist = territory.names(code)
    lat, lon, geo = territory.point(code)
    if latlon and latlon[0] is not None:
        lat, lon, geo = round(latlon[0], 5), round(latlon[1], 5), "coordenada-fuente"
    ph = calendar.phase(day[:7]) if month_known else None
    if tipo:
        attrib = "curado"
    else:
        tipo, attrib = calendar.tipo_evento(day, month_known, danger, code[:2], cause)
    end = ""
    if duration and precision == "dia":
        end = (date.fromisoformat(day) + timedelta(days=duration - 1)).isoformat()
    imp = {k: (impacts or {}).get(k) for k in E.IMPACT_COLUMNS}
    imp = {k: (v if v not in (0, 0.0, "") else None) for k, v in imp.items()}
    if confidence is None:
        typed = danger_method in ("fuente", "texto")
        confidence = ("alta" if len(code) == 6 and precision == "dia" and typed
                      else "media" if len(code) >= 4 and month_known else "baja")
    rec = {c: "" for c in E.COLUMNS}
    rec.update({
        "Date": day, "DangerType": danger, "Ubicacion": place, "Distrito": dist, "Provincia": prov,
        "Departamento": dep, "Descripción": description, "DuraciónEvento": duration, "Ubigeo": code,
        "TipoEvento": tipo, "Fuente": url, "Latitud": lat, "Longitud": lon,
        "Id": f"{origin}-{source_id}", "Origen": origin, "IdFuente": source_id, "FechaFin": end,
        "PrecisionFecha": precision, "Anio": y, "Mes": m if month_known else None,
        "AnioHidrologico": E.hydro_year(y, m) if month_known else "", "GrupoPeligro": E.danger_group(danger),
        "PeligroFuente": source_type or danger, "DangerTypeMetodo": danger_method, "CausaFuente": cause,
        "NivelUbigeo": LEVEL[len(code)], "PrecisionGeo": geo, "Region": territory.region(code),
        "AltitudCapital": territory.altitude(code), "FaseENSO": ph.phase if ph else "",
        "EventoENSO": ph.event if ph else "", "ICEN": ph.icen if ph else None, "ONI": ph.oni if ph else None,
        "AtribucionENSO": attrib, **imp, "ImpactoReportado": "si" if any(imp.values()) else "no",
        "FuenteCita": cite, "Licencia": license, "Confianza": confidence,
    })
    return rec
