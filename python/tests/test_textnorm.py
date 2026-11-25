"""Lectura de niveles tolerante a la forma del texto (``enso/textnorm.py``).

Cada prueba fija lo que una institución escribe de verdad o podría escribir mañana, y qué nivel corresponde. Las que
dicen «no se lee» son tan importantes como las que leen: tolerar no es adivinar (docs/niveles-de-aviso.md).
Prueba de mutación: sobre el código anterior a este cambio fallan las que leen variantes (romanos, género, plural,
errata, palabra partida del PDF, nombres de la DHN con «tsunamis»).
"""
from __future__ import annotations

import json

import pytest

from enso import documentos as D
from enso import severity as SV
from enso import sourcefeed
from enso import textnorm as T
from enso.observatory import EventLog


# ---------------------------------------------------------------------------
# fold
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw, want", [
    ("Cancelación de ALERTA", "cancelacion de alerta"),
    ("umbral amarillo", "umbral amarillo"),  # espacio duro
    ("ama­rillo", "amarillo"),  # guion blando
    ("na​ranja", "naranja"),  # espacio de ancho cero
    ("ubicándose en el umbral ama-\nrillo", "ubicandose en el umbral amarillo"),  # corte de línea del PDF
    ("Nivel–4", "nivel-4"),  # raya a guion, sin unir (no hay salto de línea)
    ("ＮＩＶＥＬ ４", "nivel 4"),  # ancho completo (NFKC)
    ("Nivel Nº 4", "nivel no 4"),
    ("  muy\t\n alto ", "muy alto"),
])
def test_fold(raw, want):
    assert T.fold(raw) == want


def test_fold_does_not_join_a_real_hyphen():
    assert T.fold("PDF-COEN") == "pdf-coen" and T.fold("Nivel-4") == "nivel-4"


# ---------------------------------------------------------------------------
# stem: solo flexión, y cada escala sigue distinguiendo sus palabras
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("a, b", [("amarillo", "amarillas"), ("rojo", "rojas"), ("alto", "alta"), ("bajo", "bajas"),
                                  ("moderado", "moderadas"), ("extremo", "extrema"), ("naranja", "naranjas"),
                                  ("verde", "verdes"), ("alerta", "alertas"), ("voraz", "voraces")])
def test_stem_joins_gender_and_number(a, b):
    assert T.stem(a) == T.stem(b)


@pytest.mark.parametrize("a, b", [("moderado", "moderadamente"), ("alerta", "alertar"), ("alto", "altura")])
def test_stem_keeps_derivation_apart(a, b):
    """Un *light stemmer*, no el Snowball: «moderadamente» no es «moderado»."""
    assert T.stem(a) != T.stem(b)


def test_every_scale_stays_distinguishable_after_stemming():
    """Si dos niveles de una escala tuvieran la misma raíz, ``lookup`` no podría separarlos: la prueba lee las claves
    reales de ``SCALES``, no una lista copiada."""
    for name, scale in SV.SCALES.items():
        stems = [T.stem_phrase(k) for k in scale["levels"]]
        assert len(set(stems)) == len(stems), (name, stems)


def test_fuzzy_candidates_are_far_apart():
    """La lectura aproximada (distancia 1) es segura solo si ningún par de palabras de una escala está a distancia 2
    o menos: una errata no puede quedar a 1 de las dos."""
    for vocab in (SV._COLORS, SV._FWI_WORDS):
        stems = [T.stem_phrase(k) for k in vocab]
        for i, a in enumerate(stems):
            for b in stems[i + 1:]:
                if len(a) >= T.FUZZY_MIN_LEN and len(b) >= T.FUZZY_MIN_LEN:
                    assert T.distance(a, b) > 2 * T.FUZZY_MAX, (a, b)


@pytest.mark.parametrize("a, b, d", [("amarillo", "amarrillo", 1), ("naranja", "naraja", 1), ("rojo", "rjoo", 1),
                                     ("amarillo", "naranja", 6), ("", "abc", 3)])
def test_distance(a, b, d):
    assert T.distance(a, b) == d


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw, key, how", [
    ("ROJO", "rojo", "exacto"), ("Roja", "rojo", "flexion"), ("NARANJAS", "naranja", "flexion"),
    ("amarrillo", "amarillo", "aproximado"), ("Amarila", "amarillo", "aproximado"),
])
def test_lookup_colors(raw, key, how):
    hit = T.lookup(raw, SV._COLORS)
    assert (hit.key, hit.how, hit.raw) == (key, how, raw)


@pytest.mark.parametrize("raw", ["ORANGE", "rajo", "rosado", "verdadero", "", "amarillento", "muy extremo"])
def test_lookup_does_not_guess(raw):
    """Otro idioma, una palabra corta a una letra (rajo/rojo: demasiado cerca para fiarse), otra palabra."""
    assert T.lookup(raw, {**SV._COLORS, **SV._FWI_WORDS}) is None


def test_lookup_without_fuzzy():
    assert T.lookup("amarrillo", SV._COLORS, fuzzy=False) is None


def test_fuzzy_refuses_a_tie():
    assert T.lookup("casas", ("casar", "cosas")) is None  # a 1 de las dos: ambiguo


# ---------------------------------------------------------------------------
# Números de nivel
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw, n", [
    ("Nivel 4", 4), ("NIVEL 4", 4), ("Nivel IV", 4), ("nivel iii", 3), ("Nivel II", 2), ("Nivel I", 1),
    ("nivel: 3", 3), ("Nivel N° 2", 2), ("Nivel Nº 2", 2), ("nivel-4", 4), ("nivel4", 4), ("Nivel cuatro", 4),
    ("aviso de precipitaciones, nivel 3: Cusco", 3), ("NIVEL 2", 2),
])
def test_level_number_reads_every_form(raw, n):
    assert T.level_number(raw) == n


@pytest.mark.parametrize("raw", ["Nivel 5", "nivel 10", "nivel 4.5", "nivel 4,5", "nivel inferior", "niveles 2 a 4",
                                 "Grado 4", "nivel del río 4", ""])
def test_level_number_refuses_what_is_not_a_level(raw):
    assert T.level_number(raw) is None


# ---------------------------------------------------------------------------
# Lectores de severidad con las variantes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("feed, title, summary, label", [
    ("senamhi-lluvias", "SENAMHI · aviso de precipitaciones para 24 horas, nivel iv: Puno", "", "Nivel 4"),
    ("senamhi-quebradas", "SENAMHI · aviso de activación de quebradas por lluvias, NIVEL 3: 4 quebradas", "", "Nivel 3"),
    ("senamhi-incendios", "SENAMHI · peligro EXTREMA de incendios forestales (índice FWI > 97)", "", "Peligro extremo"),
    ("senamhi-incendios", "SENAMHI · peligro Muy  Alta de incendios forestales", "", "Peligro muy alto"),
    ("senamhi-hidrologicos", "SENAMHI · aviso hidrológico N° 1654 (nivel Amarilla): río", "", "Umbral amarillo"),
    ("igp-cenvul-alertas", "Volcán Ubinas", "El IGP mantiene la ALERTA AMARILLA", "Alerta amarilla"),
    ("igp-cenvul-alertas", "Volcanes del sur", "con alertas naranjas por actividad", "Alerta naranja"),
    ("igp-cenvul-boletines", "Volcán Ubinas", "Alerta volcánica: Naranja", "Alerta naranja"),
    ("senamhi-telegram", "Aviso de color Rojo por lluvias", "", "Rojo"),
    ("senamhi-telegram", "Avisos naranjas en la sierra", "", "Naranja"),
    ("dhn-tsunamis", "Boletín", "CANCELACION DE ALERTA DE TSUNAMI en el litoral", "Cancelación de la alerta de tsunami"),
    ("dhn-tsunamis", "Boletín", "Se emite ALERTAS DE TSUNAMIS para la costa", "Alerta de tsunami"),
])
def test_severity_reads_the_variants(feed, title, summary, label):
    sev = SV.severity(feed, title, summary)
    assert sev and sev["label"] == label and "approx" not in sev, sev


def test_the_dhn_institution_name_is_not_an_alert():
    """«…organismo responsable del Sistema Nacional de Alerta de Tsunamis…» va en todos los boletines; con el plural
    aceptado, sin quitar el nombre, cada boletín informativo pasaba a «Alerta de tsunami» (encontrado en la copia
    real: boletín 28-2026-1, Panamá)."""
    body = ("La Dirección de Hidrografía y Navegación, organismo responsable del Sistema Nacional de Alerta de Tsunamis, "
            "informa… luego de un análisis a través del Centro Nacional de Alerta de Tsunamis, se comunica que este "
            "evento no genera tsunami en el litoral peruano.")
    assert SV.severity("dhn-tsunamis", "Sismo de magnitud 6.1", body)["label"] == "No genera tsunami"


def test_a_typo_is_read_marked_and_audited():
    sev = SV.severity("igp-cenvul-alertas", "Volcán Sabancaya", "alerta amarrilla")
    assert sev["label"] == "Alerta amarilla" and sev["approx"] == "amarrilla" and "aproximada" in sev["basis"]
    log = EventLog()
    a = {"source": "news-igp-cenvul-alertas", "title": "Volcán Sabancaya", "url": "u", "severity": sev}
    sourcefeed.audit_levels([a], log, SV.datetime.now(SV.timezone.utc))
    [e] = log.events
    assert e.code == "alert-level-approx" and "«amarrilla» leído como Alerta amarilla" in e.message


def test_an_exact_level_is_not_audited():
    sev = SV.severity("igp-cenvul-alertas", "Volcán Sabancaya", "alerta amarilla")
    log = EventLog()
    sourcefeed.audit_levels([{"source": "news-igp-cenvul-alertas", "title": "x", "url": "u", "severity": sev}], log,
                            SV.datetime.now(SV.timezone.utc))
    assert not log.events


def test_coen_rules_match_without_accents():
    """Un titular del COEN sin tildes («Boletin informativo…») recibe la misma regla que con tildes."""
    a = SV.level_status("indeci-coen-boletines", "pronostico", "BOLETIN INFORMATIVO DE AVISO DE CORTO PLAZO N° 3", "", None)
    b = SV.level_status("indeci-coen-boletines", "pronostico", "Boletín informativo de aviso de corto plazo N° 3", "", None)
    assert a["code"] == b["code"] == "multinivel"


# ---------------------------------------------------------------------------
# Umbral en el PDF del COEN
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text, want", [
    ("…registró 200.37 m s. n. m., ubicándose en el umbral amarillo.", "amarillo"),
    ("…registró 200.37 m s. n. m., UBICANDOSE EN EL UMBRAL NARANJA.", "naranja"),
    ("…el nivel se encuentra en el umbral de color rojo.", "rojo"),
    ("…ubicándose en el umbral ama-\nrillo.", "amarillo"),
    ("…superó el umbral Naranja durante la noche.", "naranja"),
])
def test_station_threshold_variants(text, want):
    assert D.station_threshold(text) == want


@pytest.mark.parametrize("text", ["Umbral Rojo (m s. n. m.) 210.5", "ubicándose en el umbral amarrillo",
                                  "ubicándose en el umbral amarillo y luego ubicándose en el umbral rojo"])
def test_station_threshold_does_not_guess(text):
    """La cabecera de la tabla, una errata (en un PDF queda «pendiente» y escala: no se adivina) y dos umbrales."""
    assert D.station_threshold(text) is None


# ---------------------------------------------------------------------------
# Deriva simulada: el nivel escrito de otra forma conserva cada nivel
# ---------------------------------------------------------------------------
def _without_link(obs: str) -> dict:
    o = json.loads(obs)
    drop = ("link", "id")
    for key in ("entries", "found"):  # ordenadas de nuevo: el orden de la copia sale del enlace
        o[key] = sorted(json.dumps({k: v for k, v in json.loads(e).items() if k not in drop}, sort_keys=True)
                        for e in o[key])
    return o


@pytest.mark.parametrize("feed", ["senamhi-incendios", "senamhi-lluvias", "senamhi-quebradas", "senamhi-hidrologicos"])
def test_level_forms_keep_every_level(feed):
    """Mutación ``level-forms`` (Nivel IV, EXTREMA, Amarilla…): sin incidencia, y todo lo publicado igual salvo el
    enlace y el id (el filtro de la capa cita el valor de la fuente). Es lo que justifica su entrada en ALLOWLIST."""
    from tools import drift_sim as DS

    [t] = DS.build_targets(all_feeds=True, only={feed})
    base = t.run(t.body)
    body = DS.MUTATIONS["level-forms"].apply(t.body, t.ctx)
    assert body and body != t.body
    got = t.run(body)
    assert not got.signals, got.signals
    assert _without_link(got.obs) == _without_link(base.obs)
    [r] = DS.simulate([t], ["level-forms"])
    assert r.verdict == DS.BENIGN or (r.verdict == DS.SILENT and DS.allowed(r)), (r.verdict, r.detail)
