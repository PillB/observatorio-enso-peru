"""Por qué un aviso del mapa queda sin nivel, y que un nivel que no se lee avise (noviembre de 2026).

Revisión de los 60 avisos publicados el 23 de noviembre y de los 1178 de las fuentes de peligros de los 60 días
anteriores (docs/niveles-de-aviso.md): 824 decían «Sin nivel» con la misma etiqueta gris («La fuente no asigna
nivel»). La mayoría era cierto (589 reportes del COEN, 64 detecciones de FIRMS), pero no todos:

* los 9 avisos de peligro extremo de incendios forestales del SENAMHI: la capa FWI da BAJO … EXTREMO y se buscaba
  «Nivel N» o un color;
* los 17 avisos hidrológicos que difunde el COEN: su PDF dice «ubicándose en el umbral amarillo» y no se leía;
* boletines de tsunami de la DHN escritos de otra forma («se emite BOLETIN DE INFORMACIÓN - SE INTENSIFICA
  VIGILANCIA»), y la cancelación de una alerta de tsunami se mostraba como alerta vigente (naranja);
* los avisos verdes (PAGER verde, «no genera tsunami») se filtraban y contaban como «sin nivel».

Cada prueba usa una respuesta real archivada y una verdad independiente del código: el texto del PDF leído a mano,
la capa del SENAMHI del mismo aviso, o la escala que la capa misma declara en su ``drawingInfo``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from enso import documentos as D
from enso import hazardparse as H
from enso import severity as SV
from enso import sourcefeed
from enso.observatory import EventLog

FIX = Path(__file__).parent / "fixtures"
SRC = FIX / "sources"
DOCS = FIX / "documentos"
NOW = datetime(2026, 11, 23, 16, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Peligro de incendios forestales (capa FWI)
# ---------------------------------------------------------------------------
def test_fwi_level_is_read_from_the_real_layer():
    """La copia real de la capa trae INTENSIDAD «EXTREMO» y RANGO «> 97»: antes quedaba sin nivel."""
    raw = json.loads((SRC / "news-senamhi-incendios.json").read_text(encoding="utf-8"))
    assert {f["properties"]["INTENSIDAD"] for f in raw["features"]} == {"EXTREMO"}  # la verdad, en la respuesta
    p = H.parse_arcgis((SRC / "news-senamhi-incendios.json").read_bytes(),
                       "https://geosinpad.indeci.gob.pe/indeci/rest/services/Ent_Tecnico_Cientificas/SENAMHI/MapServer/3/query")
    assert p.items
    for it in p.items:
        sev = SV.severity("senamhi-incendios", it["title"], it["summary"])
        assert sev is not None, it["title"]
        assert (sev["label"], sev["rank"], sev["color"]) == ("Peligro extremo", 3, "morado")


def test_fwi_scale_covers_and_orders_what_the_layer_declares():
    """La escala es la del ``drawingInfo`` de la capa: cada valor que la capa pinta tiene nivel, y el orden sigue sus
    colores (BAJO transparente < MODERADO amarillo < ALTO naranja < MUY ALTO rojo ≤ EXTREMO morado)."""
    ren = json.loads((SRC / "geosinpad-senamhi-renderers-20261123.json").read_text(encoding="utf-8"))["3"]["renderer"]
    assert ren["field1"] == "INTENSIDAD"
    declared = {u["value"].lower(): u["color"] for u in ren["uniqueValueInfos"]}
    levels = SV.SCALES["senamhi-fwi"]["levels"]
    assert set(declared) == set(levels)
    assert declared["bajo"][3] == 0  # transparente: no es un aviso → rango 0
    order = ["bajo", "moderado", "alto", "muy alto", "extremo"]
    ranks = [levels[k][0] for k in order]
    assert ranks == sorted(ranks) and ranks[0] == 0 and ranks[1] == 1


def test_quebradas_and_lluvias_scale_covers_what_the_layers_declare():
    """Cada «Nivel N» que las capas 2 y 5 declaran se lee (el nivel 1, transparente, es rango 0)."""
    ren = json.loads((SRC / "geosinpad-senamhi-renderers-20261123.json").read_text(encoding="utf-8"))
    for layer in ("2", "5"):
        for u in ren[layer]["renderer"]["uniqueValueInfos"]:
            sev = SV.severity("senamhi-lluvias", f"SENAMHI · aviso de precipitaciones para 24 horas, {u['value'].lower()}", "")
            assert sev is not None, u["value"]
            assert (sev["rank"] == 0) == (u["color"][3] == 0)


@pytest.mark.parametrize("intensidad, rank", [("BAJO", 0), ("MODERADO", 1), ("ALTO", 2), ("MUY ALTO", 3), ("EXTREMO", 3)])
def test_fwi_each_level_word(intensidad, rank):
    # «ALTO» no debe tomarse de «MUY ALTO» ni al revés (mutación probada: quitar «muy\s+alto» de _FWI_RE).
    sev = SV.severity("senamhi-incendios", f"SENAMHI · peligro {intensidad.lower()} de incendios forestales (índice FWI x)", "")
    assert sev["rank"] == rank and sev["label"].lower() == f"peligro {intensidad.lower()}"


def test_fwi_unknown_word_is_loud_not_silent():
    title = "SENAMHI · peligro extrema de incendios forestales (índice FWI > 97): Loreto"
    sev = SV.severity("senamhi-incendios", title, "")
    st = SV.level_status("senamhi-incendios", "pronostico", title, "", sev)
    assert sev is None and st["code"] == "no-leido" and st["loud"]


# ---------------------------------------------------------------------------
# Avisos hidrológicos que difunde el COEN
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture, umbral", [
    # Leídos a mano en cada PDF real («…ubicándose en el umbral …»).
    ("aviso-hidrologico-1647-lagarto.txt", "amarillo"),
    ("aviso-hidrologico-1652-puerto-alegria.txt", "naranja"),
    ("aviso-hidrologico-1656-borja.txt", "naranja"),
    ("aviso-hidrologico-1667.txt", "rojo"),
    ("aviso-hidrologico-1704.txt", "naranja"),
])
def test_station_threshold_from_real_coen_pdfs(fixture, umbral):
    text = (DOCS / fixture).read_text(encoding="utf-8")
    assert D.station_threshold(text) == umbral
    doc = D.read(text, "Aviso hidrológico N° 1 del SENAMHI")
    sev = SV.severity("indeci-coen-boletines", "Aviso hidrológico N° 1 del SENAMHI: situación actual del río",
                      D.summary(doc, "hidrológico"))
    assert sev["scale"] == "senamhi-umbral" and sev["color"] == umbral


#: Una frase de descripción real de un reporte del COEN (docs/documentos-backtest.md, Challhuahuacho).
DESCRIBED = " Se registró un deslizamiento en el distrito Challhuahuacho, provincia de Cotabambas."


@pytest.mark.parametrize("fixture, title, basis", [
    ("corto-plazo-lluvias-297.txt", "Aviso de corto plazo ante lluvias intensas", "provincias expuestas"),
    ("oleaje-043.txt", "Aviso especial de oleaje N° 043", "tramos del litoral"),
    ("aviso-432.txt", "Aviso meteorológico N° 432 del SENAMHI", "departamentos expuestos"),
    ("aviso-hidrologico-1704.txt", "Aviso hidrológico N° 1704 del SENAMHI", "estación del boletín"),
])
def test_reading_the_threshold_does_not_change_where_places_come_from(fixture, title, basis):
    """Guardia de la revisión adversarial: un primer intento insertó la lectura del umbral en medio de la cadena
    ``if/elif`` de ``documentos.read``, y la ubicación por la descripción de un reporte (la última rama) pasaba a
    correr también en los avisos que ya tenían lugares: un aviso que menciona un distrito en su texto perdía sus
    provincias expuestas. Mutación probada: ese mismo intento hace fallar las tres primeras (la cuarta, el aviso
    hidrológico, es la rama que el intento tomaba)."""
    doc = D.read((DOCS / fixture).read_text(encoding="utf-8") + DESCRIBED, title)
    assert basis in doc.get("basis", ""), doc.get("basis")
    assert ("umbral" in doc) == ("hidrol" in title.lower())


def test_pdf_and_layer_agree_on_aviso_1654():
    """Dos fuentes independientes del mismo aviso: el PDF del COEN (boletín 1647, aviso N° 1654 del SENAMHI) y el
    titular real de la capa hidrológica del SENAMHI del 17 de octubre."""
    text = (DOCS / "aviso-hidrologico-1647-lagarto.txt").read_text(encoding="utf-8")
    assert re.search(r"AVISO N°\s*1654", text)
    layer_title = ("SENAMHI · aviso hidrológico N° 1654 (nivel amarillo): situación actual del nivel del río Ucayali, "
                   "estación Lagarto Ird")
    assert SV.severity("senamhi-hidrologicos", layer_title, "")["color"] == D.station_threshold(text)


def test_threshold_ignores_the_table_header_and_the_legend():
    # La cabecera «Umbral Rojo (m s. n. m.)» y la leyenda AMARILLO/NARANJA/ROJO están en todos los boletines.
    assert D.station_threshold("NIVELES DE PELIGRO AMARILLO … ROJO Río Estación Distrito Umbral Rojo (m s. n. m.)") is None
    # Dos umbrales distintos en la descripción: ambiguo, no se elige ninguno.
    assert D.station_threshold("se encuentra en el umbral amarillo y luego superó el umbral rojo") is None


def _coen_hidro(summary: str) -> dict:
    return {"source": "news-indeci-coen-boletines", "title": "Aviso hidrológico N° 1654 del SENAMHI: situación actual",
            "url": "https://portal.indeci.gob.pe/x", "date": "2026-10-17T12:00:00Z", "text": summary,
            **SV.assess("indeci-coen-boletines", "Aviso hidrológico N° 1654 del SENAMHI: situación actual", summary,
                        "2026-10-17T12:00:00Z", NOW)}


LAYER_1654 = {"feed": "senamhi-hidrologicos", "title": "SENAMHI · aviso hidrológico N° 1654 (nivel amarillo): situación"}


def test_layer_fills_the_level_when_the_pdf_was_not_read():
    a = _coen_hidro("Aviso hidrológico N° 1654: situación actual del nivel del río.")
    assert a["severity"] is None and a["levelStatus"]["code"] == "pendiente"
    sourcefeed.cross_level(a, sourcefeed.hidro_levels([LAYER_1654]))
    assert a["severity"]["color"] == "amarillo" and "capa del SENAMHI" in a["severity"]["basis"]
    assert "levelStatus" not in a


def test_pdf_and_layer_disagree_is_loud():
    a = _coen_hidro("Umbral de la estación según el PDF del COEN: naranja.")
    sourcefeed.cross_level(a, sourcefeed.hidro_levels([LAYER_1654]))
    assert a["severity"]["color"] == "naranja" and a["levelConflict"]["label"] == "Umbral amarillo"
    log = EventLog()
    sourcefeed.audit_levels([a], log, NOW)
    assert [e.code for e in log.events] == ["alert-level-conflict"]


def test_pdf_read_without_threshold_is_unread_not_pending():
    a = _coen_hidro("Aviso hidrológico N° 1654: situación. Según el PDF del COEN (estación del boletín): Raimondi.")
    assert a["levelStatus"]["code"] == "no-leido" and a["levelStatus"]["loud"]


def test_cached_reads_from_before_the_threshold_are_read_again_once():
    hidro = {"title": "Aviso hidrológico N° 1704 del SENAMHI: descenso del nivel"}
    assert D._needs_read(hidro, {"status": "ok", "tries": 1})  # leído con la versión 1: sin umbral
    assert not D._needs_read(hidro, {"status": "ok", "tries": 2, "v": D.READ_VERSION})  # ya releído
    assert not D._needs_read(hidro, {"status": "ok", "tries": 1, "umbral": "rojo"})
    assert not D._needs_read({"title": "Aviso de corto plazo ante lluvias intensas"}, {"status": "ok", "tries": 1})
    assert D._needs_read(hidro, {"status": "error", "tries": D.MAX_TRIES - 1})
    assert not D._needs_read(hidro, {"status": "error", "tries": D.MAX_TRIES})


# ---------------------------------------------------------------------------
# Boletines de sismo y tsunami de la DHN
# ---------------------------------------------------------------------------
def _dhn_blocks() -> list[tuple[str, str]]:
    from enso.feedparse import clean_text, text_of

    text = text_of((SRC / "news-dhn-tsunamis.html").read_bytes())
    return [(m.group("num"), clean_text(m.group("body"), 3000)) for m in H._DHN_BLOCK_RE.finditer(text)]


#: La frase de estado de un boletín y el nivel que corresponde (el primero que aparece en la frase).
DHN_SAID = (("cancelaci", "Cancelación de la alerta de tsunami"), ("no genera", "No genera tsunami"),
            ("alerta de tsunami", "Alerta de tsunami"), ("vigilancia", None))
_SAID_RE = re.compile(r"(?:comunica,? que(?: este evento)?|se emite)\s+(.+?)\.(?:\s|$)", re.I)


def _said(body: str):
    """El nivel que dice la primera frase tras «comunica que» o «se emite» del texto crudo, o «sin frase»."""
    m = _SAID_RE.search(body)
    if not m:
        return "sin frase"
    return next((lab for key, lab in DHN_SAID if key in m.group(1).lower()), "?")


def _check_bulletin(num: str, it: dict, label) -> None:
    sev = SV.severity("dhn-tsunamis", it["title"], it["summary"])
    st = SV.level_status("dhn-tsunamis", "reporte", it["title"], it["summary"], sev)
    assert (sev["label"] if sev else None) == label, (num, it["title"])
    assert label is not None or st["code"] == "en-evaluacion", num


def test_every_real_dhn_bulletin_gets_a_level_or_a_reason():
    """Los boletines de la copia real: ninguno queda «no leído», y cada uno tiene el nivel que dice su frase de estado.
    La verdad sale del texto crudo de cada bloque (``_said``), no del titular que arma el lector."""
    items = {i["link"].split("#")[1]: i for i in H.parse_dhn((SRC / "news-dhn-tsunamis.html").read_bytes()).items}
    seen: dict = {}
    for num, body in _dhn_blocks():
        label, it = _said(body), items.get(num)
        if it is None or label == "sin frase":
            continue  # simulacros y bloques vacíos
        _check_bulletin(num, it, label)
        seen[label] = seen.get(label, 0) + 1
    # Antes del arreglo: 2 cancelaciones como «Alerta de tsunami» y 2 boletines en evaluación sin estado.
    assert seen.get("Cancelación de la alerta de tsunami") == 2 and seen.get(None, 0) >= 18 and "?" not in seen


def test_an_active_alert_that_mentions_its_future_cancellation_stays_an_alert():
    """Boletín 31-2025-5 (Kamchatka, 8,8 Mw): «…se continúa en ALERTA DE TSUNAMI… EVACUAR … hasta la cancelación de
    ALERTA de tsunamis». Con el texto completo, una regla ingenua de «cancelación» lo volvía verde."""
    [body] = [b for n, b in _dhn_blocks() if n == "31-2025-5"]
    assert "hasta la cancelación de ALERTA de tsunamis" in body
    sev = SV.severity("dhn-tsunamis", "BOLETÍN DE SISMO TSUNAMI N° 31-2025-5", body)
    assert sev["label"] == "Alerta de tsunami" and sev["rank"] == 2


def test_dhn_second_wording_gets_its_status():
    """«…se emite BOLETIN DE INFORMACIÓN - SE INTENSIFICA VIGILANCIA.» (sismo de Panamá, 9 de octubre de 2026)."""
    items = H.parse_dhn((SRC / "news-dhn-tsunamis.html").read_bytes()).items
    panama = [i for i in items if "LAS TABLAS" in i["title"] and "en tierra" in i["title"]]
    assert panama and panama[0]["title"].lower().endswith("se intensifica vigilancia")


# ---------------------------------------------------------------------------
# Las razones, con titulares reales del 23 de noviembre de 2026
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("feed, kind, title, summary, code", [
    ("indeci-coen", "reporte", "Vientos fuertes en el distrito de Colcabamba (Apurímac)", "Reporte complementario N° 16322",
     "no-aplica"),
    ("indeci-coen-boletines", "pronostico", "Aviso de corto plazo ante lluvias intensas (boletín N° 325 del COEN)",
     "VIGENCIA: 22-11-2026 (13:00 h) al 23-11-2026 (13:00 h). Aviso N° 326", "multinivel"),
    ("indeci-coen", "pronostico", "Aviso especial de oleaje N° 050: oleaje de ligera a moderada intensidad", "", "sin-escala"),
    ("dhn-avisos", "pronostico", "DHN · aviso especial de oleaje N° 50-26: oleaje moderado en el litoral norte", "", "sin-escala"),
    ("usgs-sismos", "reporte", "Sismo de magnitud 5 a 15 km al NNE de Carhuamayo, Perú",
     "Magnitud 5 (mww). profundidad 108 km.", "no-calculado"),
    ("firms-focos", "deteccion", "NASA FIRMS · 201 focos de calor en el Perú", "", "no-aplica"),
    ("senamhi-telegram", "en-curso", "SENAMHI, en este momento: se presenta lluvia en la costa de Tumbes", "", "sin-escala"),
    ("indeci-coen-boletines", "pronostico", "Aviso meteorológico N° 482 del SENAMHI: llovizna en la costa", "", "pendiente"),
])
def test_each_no_level_alert_says_why(feed, kind, title, summary, code):
    assert SV.severity(feed, title, summary) is None
    st = SV.level_status(feed, kind, title, summary, None)
    assert st["code"] == code and not st["loud"] and st["label"] and st["why"]


def test_a_new_hazard_feed_without_a_rule_is_loud():
    st = SV.level_status("ingemmet-nuevo", "pronostico", "Alerta geológica", "", None)
    assert st["code"] == "sin-regla" and st["loud"]


def test_a_level_is_not_overridden_by_a_reason():
    assert SV.level_status("usgs-sismos", "reporte", "x", "alerta PAGER green.", {"rank": 0}) is None


# ---------------------------------------------------------------------------
# La incidencia
# ---------------------------------------------------------------------------
def _alert(source: str, title: str, status: dict, hours: float) -> dict:
    return {"source": source, "title": title, "url": "https://x", "severity": None, "levelStatus": dict(status),
            "date": (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")}


def test_audit_opens_one_issue_per_source_and_reason():
    unread = SV.level_status("senamhi-incendios", "pronostico", "peligro raro", "", None)
    alerts = [_alert("news-senamhi-incendios", f"SENAMHI · peligro raro {n}", unread, 1) for n in range(6)]
    alerts.append(_alert("news-indeci-coen", "Vientos fuertes", SV.level_status("indeci-coen", "reporte", "Vientos", "", None), 1))
    log = EventLog()
    counts = sourcefeed.audit_levels(alerts, log, NOW)
    assert [(e.source, e.code, e.severity) for e in log.events] == [("senamhi-incendios", "alert-level-unread", "warning")]
    msg = log.events[0].message
    assert msg.startswith("6 aviso(s)") and "y 2 más" in msg and "docs/niveles-de-aviso.md" in msg
    assert counts == {"no-leido": 6, "no-aplica": 1}


@pytest.mark.parametrize("hours, loud", [(47.9, False), (48.1, True)])
def test_a_pending_level_that_cites_its_number_escalates_after_48_hours(hours, loud):
    pending = SV.level_status("indeci-coen-boletines", "pronostico", "Aviso meteorológico N° 482 del SENAMHI: x", "", None)
    a = _alert("news-indeci-coen-boletines", "Aviso meteorológico N° 482 del SENAMHI: x", pending, hours)
    log = EventLog()
    sourcefeed.audit_levels([a], log, NOW)
    assert (a["levelStatus"]["code"] == "no-leido") is loud
    assert bool(log.events) is loud


def test_pending_without_a_number_does_not_escalate():
    pending = SV.level_status("senamhi-telegram", "pronostico", "Aviso del SENAMHI: reducen condiciones", "", None,
                              cites_aviso=True)
    assert pending["code"] == "pendiente"
    a = _alert("news-senamhi-telegram", "Aviso del SENAMHI: reducen condiciones", pending, 500)
    log = EventLog()
    sourcefeed.audit_levels([a], log, NOW)
    assert not log.events and a["levelStatus"]["code"] == "pendiente"


# ---------------------------------------------------------------------------
# Deriva simulada: un vocabulario nuevo en el campo del nivel avisa
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("feed, mutation", [
    ("senamhi-incendios", "level-vocab"), ("senamhi-lluvias", "level-vocab"), ("senamhi-quebradas", "level-vocab"),
    ("senamhi-hidrologicos", "level-vocab"), ("dhn-tsunamis", "status-wording")])
def test_level_vocabulary_drift_is_loud(feed, mutation):
    from tools import drift_sim as DS

    targets = DS.build_targets(all_feeds=True, only={feed})
    [r] = DS.simulate(targets, [mutation])
    assert r.verdict == DS.LOUD and "warning:alert-level-unread" in r.signals, (r.verdict, r.detail)


def test_an_unknown_coen_bulletin_type_asks_for_a_rule():
    """Un boletín del COEN de un tipo nuevo (ni corto plazo, ni oleaje, ni hidrológico, ni meteorológico) no se da por
    «sin nivel»: pide una regla (``alert-level-norule``). Un reporte sigue siendo un reporte."""
    st = SV.level_status("indeci-coen-boletines", "pronostico", "Boletín informativo de aviso de heladas N° 12", "", None)
    assert st["code"] == "sin-regla" and st["loud"]
    st = SV.level_status("firms-focos", "deteccion", "NASA FIRMS · 3 focos", "", None)
    assert st["code"] == "no-aplica" and st["label"] == "Detección, sin nivel"
