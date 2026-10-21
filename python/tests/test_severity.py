"""Nivel y vigencia de los avisos (enso.severity), sobre titulares reales del 21 de octubre de 2026.

El nivel es siempre el de la institución; un aviso sin nivel en su fuente queda sin nivel.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from enso import severity as SV
from enso import sourcefeed

NOW = datetime(2026, 10, 21, 20, 40, tzinfo=timezone.utc)


@pytest.mark.parametrize("feed, title, summary, rank, label", [
    ("senamhi-quebradas", "SENAMHI · aviso de activación de quebradas por lluvias, nivel 4: 10 distritos de Piura y Cajamarca",
     "Distritos con probable activación de quebradas en las próximas 24 horas", 3, "Nivel 4"),
    ("senamhi-quebradas", "SENAMHI · aviso de activación de quebradas por lluvias, nivel 2: 1106 distritos", "", 1, "Nivel 2"),
    ("senamhi-hidrologicos", "SENAMHI · aviso hidrológico N° 1655 (nivel naranja): situación actual del nivel del río Nanay",
     "", 2, "Umbral naranja"),
    ("igp-cenvul-boletines", "Volcán Sabancaya: boletín IGP/CENVUL-SAB/BV 2026-0042, alerta naranja",
     "Nivel de alerta: naranja.", 2, "Alerta naranja"),
    ("usgs-sismos", "Sismo de magnitud 6.8 frente a la costa de Ica", "Magnitud 6.8 (mww). alerta PAGER yellow.", 1,
     "PAGER amarilla"),
    ("senamhi-telegram", "Aviso del SENAMHI: lluvias de moderada a fuerte intensidad", "Aviso naranja vigente.", 2, "Naranja"),
])
def test_level_comes_from_the_institution(feed, title, summary, rank, label):
    s = SV.severity(feed, title, summary)
    assert s and s["rank"] == rank and s["label"] == label and s["scaleLabel"]


@pytest.mark.parametrize("feed, title, summary", [
    # La magnitud de un sismo es una medida, no un nivel de alerta.
    ("usgs-sismos", "Sismo de magnitud 4.2 a 71 km al S de Camaná, Perú", "Magnitud 4.2 (mwr). profundidad 35 km."),
    # Los reportes de daños del COEN y los avisos de la DHN no traen nivel.
    ("indeci-coen", "Incendio forestal en el distrito de Ajoyani (Puno)", "Reporte complementario N° 14675 del COEN-INDECI"),
    ("dhn-avisos", "DHN · aviso especial de oleaje N° 42-26: oleaje fuerte en el litoral norte", ""),
    ("firms-focos", "NASA FIRMS · 77 focos de calor en el Perú", "Detecciones del satélite NOAA-20"),
    # «nivel del río» no es un nivel de aviso.
    ("senamhi-telegram", "Aviso del SENAMHI: del 22 al 24 de octubre, precipitaciones en la costa", "sube el nivel del río"),
])
def test_no_level_is_invented(feed, title, summary):
    assert SV.severity(feed, title, summary) is None


def test_validity_windows_from_the_text():
    v = SV.validity("senamhi-telegram", "Aviso del SENAMHI: del 22 al 24 de octubre, se presentará precipitaciones", "",
                    "2026-10-21T01:54:25Z")
    assert v["from"] == "2026-10-22T05:00:00Z" and v["until"] == "2026-10-25T04:59:00Z"  # días completos en Lima
    v = SV.validity("senamhi-telegram", "Aviso del SENAMHI: del 18 y 19 de octubre, se espera precipitaciones", "",
                    "2026-10-16T22:27:00Z")
    assert v["from"].startswith("2026-10-18") and v["until"].startswith("2026-10-20T04:59")
    v = SV.validity("senamhi-telegram", "Aviso del SENAMHI: del 31 de diciembre al 2 de enero, lluvias", "",
                    "2026-12-30T12:00:00Z")
    assert v["from"].startswith("2026-12-31") and v["until"].startswith("2027-01-03")  # cruza el año
    v = SV.validity("dhn-avisos", "DHN · aviso especial de oleaje N° 42-26: oleaje fuerte (válido del 20 al 25 de octubre del 2026)",
                    "", "2026-10-20T17:00:00Z")
    assert v["from"] == "2026-10-20T05:00:00Z" and v["until"] == "2026-10-26T04:59:00Z"
    v = SV.validity("indeci-coen", "BOLETÍN INFORMATIVO DE AVISO DE CORTO PLAZO ANTE LLUVIAS INTENSAS N° 293-2026-INDECI/COEN",
                    "VIGENCIA: 21-10-2026 (13:00 h) al 22-10-2026 (13:00 h)", "2026-10-21T18:37:00Z")
    assert v == {"from": "2026-10-21T18:00:00Z", "until": "2026-10-22T18:00:00Z", "basis": "vigencia del boletín del COEN"}
    v = SV.validity("senamhi-quebradas", "SENAMHI · aviso de activación de quebradas por lluvias, nivel 3: 313 distritos", "",
                    "2026-10-21T17:00:00Z")
    assert v["until"] == "2026-10-22T17:00:00Z"
    # Un rango imposible no se publica como vigencia.
    assert SV.validity("senamhi-telegram", "Aviso del SENAMHI: del 30 al 2 de octubre", "", "2026-10-01T00:00:00Z") is None


@pytest.mark.parametrize("valid, phase", [
    ({"from": "2026-10-22T05:00:00Z", "until": "2026-10-25T04:59:00Z"}, "proxima"),
    ({"from": "2026-10-20T05:00:00Z", "until": "2026-10-23T04:59:00Z"}, "vigente"),
    ({"from": "2026-10-17T05:00:00Z", "until": "2026-10-20T04:59:00Z"}, "vencida"),
])
def test_phase_of_a_forecast(valid, phase):
    assert SV.phase("pronostico", valid, "2026-10-20T00:00:00Z", NOW) == phase


def test_current_state_ages_out():
    assert SV.phase("en-curso", None, "2026-10-21T14:00:00Z", NOW, "senamhi-telegram") == "en-curso"
    assert SV.phase("en-curso", None, "2026-10-19T14:00:00Z", NOW, "senamhi-telegram") == "reciente"
    assert SV.phase("reporte", None, "2026-10-21T14:00:00Z", NOW, "indeci-coen") == "ocurrido"


def test_coen_report_keeps_when_it_happened():
    a = SV.assess("indeci-coen", "Incendio forestal en el distrito de Marcas (Huancavelica)",
                  "Reporte complementario N° 14672 del COEN-INDECI, 21/10/2026 14:19 h (actualización N° 3). HECHOS Fecha y "
                  "hora de la ocurrencia Descripción 18/10/2026 11:30 horas Se registró un incendio", "2026-10-21T20:07:00Z", NOW)
    assert a["kind"] == "reporte" and a["severity"] is None and a["occurred"] == "2026-10-18T16:30:00Z"


def test_alerts_in_feed_carry_severity_and_validity(monkeypatch):
    item = {"id": "abc", "feed": "senamhi-quebradas", "published": "2026-10-21T17:00:00Z", "first_seen": "2026-10-21T18:00:00Z",
            "title": "SENAMHI · aviso de activación de quebradas por lluvias, nivel 4: 10 distritos de Piura y Cajamarca",
            "summary": "Distritos con probable activación de quebradas en las próximas 24 horas, según el SENAMHI: Piura (8), Cajamarca (2).",
            "link": "https://geosinpad.indeci.gob.pe/x", "hazards": ["huaico"],
            "places": [{"code": "20", "level": "departamento", "name": "Piura"}]}
    out = sourcefeed.alerts([item], NOW)
    assert len(out) == 1
    a = out[0]
    assert a["severity"]["label"] == "Nivel 4" and a["severity"]["rank"] == 3
    assert a["kind"] == "pronostico" and a["phaseAtPublication"] == "vigente" and a["valid"]["until"] == "2026-10-22T17:00:00Z"
