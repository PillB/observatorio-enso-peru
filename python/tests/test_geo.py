"""Ubicación de noticias y avisos: precisión sobre los conjuntos etiquetados a mano, coordenadas y correcciones."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from enso import geo_overrides as GO
from enso.geo import legacy_fields, locate_item
from enso.limites import locate
from tools import geo_eval

GOLD = Path(__file__).parent / "geo"


# --- Precisión (puerta de calidad) --------------------------------------------------------

@pytest.mark.parametrize("name", ["gold-noticias.jsonl", "holdout-noticias.jsonl", "review-tercera.jsonl"])
def test_precision_on_hand_labelled_news(name):
    """Notas reales etiquetadas a mano. Una nota mal ubicada es peor que una sin lugar: la puerta es la precisión.

    ``review-tercera`` revisa predicciones (su exhaustividad no es una medida independiente)."""
    m = geo_eval.evaluate(geo_eval.load([GOLD / name]), geo_eval.predict)
    assert m["items"] >= 100
    assert m["misplacedRate"] <= 0.02, m
    assert m["depPrecision"] >= 0.98, m
    assert m["finePrecision"] >= 0.97, m
    assert m["depRecall"] >= 0.9, m


# --- Texto ----------------------------------------------------------------------------------

@pytest.mark.parametrize("title,code,max_conf", [
    ("Sismo de magnitud 4.2 a 71 km al S de Camaná, Perú", "04", 0.55),
    ("Sismo de magnitud 5.2 a 18 km al SSE de Camaná, Perú", "04", 0.7),
    ("Sismo de 4.0 a 8 km al NE de Sullana", "2006", 0.7),
    ("Temblor frente a las costas de Pisco", "11", 0.7),
])
def test_distance_from_a_town_is_a_reference_not_the_place(title, code, max_conf):
    g = locate_item({"title": title})
    assert [p["code"] for p in g["places"]] == [code]
    assert g["places"][0]["confidence"] <= max_conf
    assert "referencia" in g["places"][0]["rule"]


@pytest.mark.parametrize("title,codes", [
    ("Sismo de magnitud 4.0. 20/10/2026 10:00 hora de Lima", []),
    ("Huaico en Kimbiri afecta viviendas", ["080907"]),
    ("Estación Lagarto (distrito de Raimondi, provincia de Atalaya, departamento de Ucayali)", ["250201"]),
    ("Perú busca esferas para almacenar GLP fuera de Lima", []),
    ("Extinguen incendios en los distritos de Uñón (Arequipa), Pallpata, Pampamarca y Ccatcca (Cusco). "
     "En los distritos de Pallpata, Pampamarca y Ccatcca, los comuneros", ["040412", "080805", "080506", "081205"]),
])
def test_reported_misplacements(title, codes):
    g = locate_item({"title": title}) or {}
    assert [p["code"] for p in g.get("places") or []] == codes


def test_item_carries_confidence_method_and_evidence():
    g = locate_item({"title": "Huaico afecta viviendas en el distrito de Chaclacayo"})
    p = g["places"][0]
    assert (p["code"], p["level"], p["method"]) == ("150107", "distrito", "texto")
    assert 0.5 <= p["confidence"] <= 1 and "Chaclacayo" in p["evidence"]
    assert g["country"] == "PE" and g["scope"] == "local"
    legacy = legacy_fields(g)
    assert legacy["departments"] == ["15"] and legacy["places"][0]["code"] == "150107"


# --- Coordenadas ------------------------------------------------------------------------------

@pytest.mark.parametrize("lat,lon,acc,code", [
    (-13.5167, -71.9787, 0, "080101"),   # Plaza de Armas del Cusco
    (-13.5298, -71.9546, 0, "080108"),   # Wanchaq
    (-13.5320, -71.9675, 0, "0801"),     # a metros del límite Cusco–Wanchaq: solo la provincia
    (-3.7491, -73.2538, 0, "160101"),    # Iquitos
    (-14.1, -75.7, 8, "1101"),           # epicentro con 8 km de error: provincia de Ica
])
def test_points_fall_in_the_right_unit(lat, lon, acc, code):
    hit = locate(lat, lon, acc)
    assert hit and hit["code"] == code, hit


def test_offshore_lake_and_neighbours():
    sea = locate(-13.9, -76.6)
    assert sea["code"] == "11" and sea["offshore"] and "mar" in sea["note"]
    assert locate(-15.8, -69.6)["code"] == "21"          # lago Titicaca, lado peruano
    assert locate(-18.48, -70.31) is None                 # Arica (Chile)
    assert locate(-16.17, -69.09) is None                 # Copacabana (Bolivia)
    assert locate(-0.18, -78.47) is None                  # Quito
    assert locate(-12, -82.5) is None                     # mar abierto, lejos de la costa
    assert locate(float("nan"), -77) is None


def test_newer_districts_lower_confidence():
    hit = locate(-12.0167, -76.9333)  # Huachipa (2023) cae en Lurigancho en los límites de la fuente
    assert hit["code"] == "150118" and hit["confidence"] < 0.8


def test_usgs_epicentre_coordinates_win_over_text():
    g = locate_item({"title": "Sismo de magnitud 4.4 a 34 km al SSO de Huacho, Perú", "coords": [[-11.406, -77.687, 10]]})
    assert g["places"][0]["code"] == "15" and g["places"][0]["method"] == "coordenadas"


# --- Correcciones de la consola --------------------------------------------------------------

def _items():
    return [
        {"id": "a" * 16, "title": "Lluvias en Sullana dejan damnificados", "summary": "", "feed": "", "region": "peru",
         "published": "2026-10-20T10:00:00+00:00", "first_seen": "2026-10-20T10:00:00+00:00"},
        {"id": "b" * 16, "title": "Gobierno declara emergencia", "summary": "", "feed": "", "region": "peru",
         "places": [{"code": "20", "level": "departamento", "name": "Piura"}], "departments": ["20"], "geoSource": "medio",
         "published": "2026-10-19T10:00:00+00:00", "first_seen": "2026-10-19T10:00:00+00:00"},
        {"id": "c" * 16, "title": "Reporte de emergencia", "summary": "", "feed": "", "region": "peru",
         "places": [{"code": "080101", "level": "distrito", "name": "Cusco"}], "departments": ["08"], "geoSource": "texto",
         "published": "2026-01-01T10:00:00+00:00", "first_seen": "2026-01-01T10:00:00+00:00"},
    ]


def test_relocate_keeps_old_text_places_but_not_the_outlet_guess():
    items = _items()
    GO.apply_all(items, [], {})
    a, b, c = items
    assert a["geo"]["places"][0]["code"].startswith("2006")
    assert not (b.get("geo") or {}).get("places"), "el departamento del medio no es evidencia"
    assert c["geo"]["places"][0]["code"] == "080101" and c["geo"]["method"] == "anterior"


def test_overrides_apply_latest_revision_and_validate():
    items = _items()
    ovs = GO.valid_overrides({"overrides": [
        {"id": "a" * 16, "action": "set", "places": ["150122"], "rev": 1, "at": "x"},
        {"id": "a" * 16, "action": "set", "places": ["200601", "20"], "rev": 2, "at": "y"},
        {"id": "b" * 16, "action": "foreign", "rev": 1},
        {"id": "c" * 16, "action": "set", "places": ["999999"], "rev": 1},
        {"id": "z" * 16, "action": "confirm", "rev": 1},
        {"id": "a" * 16, "action": "borrar", "rev": 9},
        "basura",
    ]})
    q = GO.apply_all(items, ovs, {})
    a, b, c = items
    assert [p["code"] for p in a["geo"]["places"]] == ["200601"]  # el departamento sobra junto al distrito
    assert a["geo"]["places"][0]["confidence"] == 1.0 and a["geo"]["review"]["rev"] == 2
    assert a["geoSource"] == "correccion" and a["departments"] == ["20"]
    assert b["geo"]["country"] is None and b["geo"]["scope"] == "internacional" and "places" not in b
    assert c["geo"]["method"] == "anterior", "un código inválido no borra la ubicación"
    assert q["overrides"] == {"applied": 2, "unknownItem": 1, "rejected": 1}


def test_confirm_and_none():
    items = _items()
    GO.apply_all(items, [{"id": "a" * 16, "action": "confirm", "rev": 1}, {"id": "c" * 16, "action": "none", "rev": 1}], {})
    assert all(p["confidence"] == 1.0 for p in items[0]["geo"]["places"])
    assert items[2]["geo"]["places"] == [] and items[2]["geo"]["scope"] == "nacional"


class _Log:
    def __init__(self):
        self.events = []

    def add(self, *a):
        self.events.append(a)


class _Prev:
    def get(self, name):
        return {"overrides": [{"id": "a" * 16, "action": "none", "rev": 3}]} if name == "geo/overrides.json" else None


class _Down:
    def get(self, *a, **k):
        raise OSError("sin red")


def test_overrides_fall_back_to_previous_publication_when_console_is_down():
    log = _Log()
    ovs, src = GO.fetch_overrides(_Down(), _Prev(), log, url="https://enso-peru.pages.dev/api/geo/overrides")
    assert src == "publicacion-anterior" and ovs[0]["rev"] == 3
    assert log.events and log.events[0][3] == "overrides-down"


def test_console_items_window():
    items = _items()
    GO.apply_all(items, [], {})
    out = GO.console_items(items, datetime(2026, 10, 21, tzinfo=timezone.utc))
    assert [i["id"][0] for i in out] == ["a", "b"]  # la de enero queda fuera de la ventana
    assert set(out[0]) >= {"id", "title", "link", "outlet", "published", "geo"}
