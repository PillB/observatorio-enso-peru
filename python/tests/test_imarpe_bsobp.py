"""Boletín semanal del IMARPE (BS-OBP): anomalía subsuperficial frente a Paita y Chicama, con su cita."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from enso.feeds import imarpe_bsobp as bs

CORPUS = json.loads(gzip.open(Path(__file__).parent / "fixtures" / "reports"
                              / "imarpe-bsobp-2025-51-a-2026-42.pages.json.gz", "rt", encoding="utf-8").read())

# Leído a mano en cada boletín (resumen de la primera página): lugar → (anomalía °C, profundidad m, plataforma).
EXPECTED = {
    "2025-51": {"Paita": (-2.0, 150, "seccion"), "Chicama": (-2.0, 100, "seccion")},
    "2026-05": {"Paita": (-3.0, 100, "seccion"), "Chicama": (-3.0, 100, "seccion")},
    "2026-06": {"Paita": (3.0, 50, "seccion"), "Chicama": (-3.0, 100, "seccion")},
    "2026-07": {"Chicama": (2.0, 40, None)},
    "2026-09": {"Paita": (-1.0, 250, "seccion")},
    "2026-14": {"Paita": (4.0, 60, "seccion"), "Chicama": (4.0, 60, "seccion")},
    "2026-16": {"Paita": (1.0, 150, "argo")},
    "2026-22": {"Paita": (8.0, 100, None), "Chicama": (4.0, 100, None)},
    "2026-26": {"Paita": (8.0, 100, "seccion"), "Chicama": (8.0, 100, "seccion")},
    "2026-30": {"Paita": (2.0, 150, "seccion"), "Chicama": (2.0, 150, "seccion")},
    "2026-35": {"Paita": (8.0, 350, "seccion"), "Chicama": (8.0, 150, "seccion")},
    "2026-42": {"Paita": (8.0, 100, "estacion_fija"), "Chicama": (7.0, 100, "estacion_fija")},
}


@pytest.mark.parametrize("name", sorted(CORPUS))
def test_backtest_on_44_real_bulletins(name):
    d = bs.parse(CORPUS[name])
    year, num = map(int, name.split("-"))
    assert d["number"] == num and d["period"][:4] in (str(year), str(year + 1))
    got = {s: (v["anomaly"], v["depth"], v["platform"]) for s, v in d["sites"].items()}
    # Las semanas sin frase sobre la columna de agua frente a Paita o Chicama no dan valor (y no es error):
    # en particular, los valores de Punta La Negra, Chimbote o de un tramo «desde Chicama a Huarmey» no cuentan.
    assert got == EXPECTED.get(name, {})
    for v in d["sites"].values():
        assert v["quote"] and v["page"] == 1


def test_fixed_station_quote_and_week():
    d = bs.parse(CORPUS["2026-42"])
    assert (d["number"], d["week"], d["period"], d["volume"]) == (42, 42, "2026-10-18", 11)
    assert d["sites"]["Paita"]["quote"].startswith("Sin embargo, persistieron anomalías superiores a +8 °C (Paita)")
    assert d["sites"]["Paita"]["layer"] == "por encima de los 100 m"


def test_week_across_years():
    assert bs.parse(CORPUS["2026-01"])["period"] == "2026-01-04"


def test_isotherm_15_only_when_said_of_paita_or_chicama():
    iso = bs.parse(CORPUS["2026-07"])["isotherm15"]
    assert (iso["site"], iso["from"], iso["depth"]) == ("Chicama", 40, 90)
    # «… frente a Chimbote donde la isoterma de 15 °C alcanzó los 250 m» es de Chimbote.
    assert bs.parse(CORPUS["2026-20"])["isotherm15"] is None


def test_unrecognized_header_and_implausible_value_raise():
    with pytest.raises(ValueError):
        bs.parse(["Otro documento"])
    page = CORPUS["2026-42"][0].replace("+8 °C (Paita)", "+38 °C (Paita)")
    with pytest.raises(ValueError):
        bs.parse([page])


def test_overdue():
    assert not bs.overdue("2026-10-18", date(2026, 10, 21))
    assert bs.overdue("2026-10-04", date(2026, 10, 21))
    assert bs.overdue(None, date(2026, 10, 21))


# --- Lectura diaria y avisos al administrador ------------------------------------------------------------------
from test_imarpe_repo import _Fetcher, _bundles, _item, _search  # noqa: E402

from enso import manual  # noqa: E402
from enso.feeds import imarpe_repo  # noqa: E402

U43 = "b5000000-0000-0000-0000-000000000043"
PDF43 = f"{imarpe_repo.API}/core/bitstreams/b43/content"
T43 = "Boletín Semanal Oceanográfico y Biológico - Pesquero vol. 11, N°43, 2026"


class _Log:
    def __init__(self):
        self.events = []

    def add(self, severity, source, stage, code, message):
        self.events.append((severity, code, message))

    def codes(self):
        return {c for _, c, _ in self.events}


def _routes(issued="2026-10-25", pdf=b"%PDF-1.7 b43"):
    return {
        "/server/api/discover/search/objects?Boletín Semanal Oceanográfico y Biológico": _search(
            _item(U43, T43, issued, "20.500.12958/6043"),
            _item("old", "Boletín Semanal Oceanográfico y Biológico - Pesquero vol. 11, N°42, 2026", "2026-10-18", "x")),
        f"/server/api/core/items/{U43}/bundles": _bundles(("BS-OBP N43 2026.pdf", PDF43)),
        PDF43: pdf,
    }


def _page43():
    return [CORPUS["2026-42"][0].replace("N° 42", "N° 43").replace("Semana 42: 12 - 18 de octubre",
                                                                   "Semana 43: 19 - 25 de octubre")]


def test_new_bulletin_is_read_with_its_provenance(monkeypatch):
    monkeypatch.setattr("enso.reports.pdf_pages", lambda b: _page43())
    log, needs = _Log(), manual.ManualNeeds()
    out = bs.acquire(_Fetcher(_routes()), None, log, date(2026, 10, 26), needs)
    top = out["bulletins"][0]
    assert (top["number"], top["period"], top["sites"]["Paita"]["anomaly"]) == (43, "2026-10-25", 8.0)
    assert top["page"].endswith("/handle/20.500.12958/6043") and top["url"] == PDF43
    assert len(out["bulletins"]) == 45 and not out["pending"] and not log.events and not needs.items
    # La corrida siguiente no lo vuelve a bajar.
    f = _Fetcher(_routes())
    bs.acquire(f, out, _Log(), date(2026, 10, 27), needs)
    assert PDF43 not in f.asked


def test_unreadable_bulletin_alerts_the_admin_and_asks_for_the_pdf(monkeypatch):
    log, needs = _Log(), manual.ManualNeeds()
    out = bs.acquire(_Fetcher(_routes(pdf=b"<html>error</html>")), None, log, date(2026, 10, 26), needs)
    assert "bsobp-unreadable" in log.codes() and out["pending"][0]["number"] == 43
    item = needs.items["imarpe-bsobp-2026-43"]
    assert item["urls"] == [PDF43] and item["open"] == ["https://repositorio.imarpe.gob.pe/handle/20.500.12958/6043"]
    assert out["bulletins"][0]["number"] == 42  # se conserva lo ya leído


def test_bulletin_of_another_number_is_not_published(monkeypatch):
    monkeypatch.setattr("enso.reports.pdf_pages", lambda b: CORPUS["2026-42"])  # el PDF es el N° 42
    log = _Log()
    out = bs.acquire(_Fetcher(_routes()), None, log, date(2026, 10, 26), manual.ManualNeeds())
    assert "bsobp-unreadable" in log.codes() and "N° 42" in out["pending"][0]["problem"]


def test_overdue_and_unreachable_repository_alert(monkeypatch):
    monkeypatch.setattr("enso.reports.pdf_pages", lambda b: _page43())
    log = _Log()
    bs.acquire(_Fetcher(_routes(issued="2026-10-25")), None, log, date(2026, 11, 10))
    assert "bsobp-overdue" in log.codes()
    log = _Log()
    prev = {"bulletins": [{"year": 2026, "number": 42, "period": "2026-10-18"}]}
    out = bs.acquire(_Fetcher({}), prev, log, date(2026, 10, 26))
    assert log.codes() == {"bsobp-unreachable"} and out["bulletins"] == prev["bulletins"]


def test_week_without_paita_or_chicama_is_not_an_alert(monkeypatch):
    page = CORPUS["2026-41"][0].replace("N° 41", "N° 43").replace("Semana 41: 05 - 11", "Semana 43: 19 - 25")
    monkeypatch.setattr("enso.reports.pdf_pages", lambda b: [page])
    log = _Log()
    out = bs.acquire(_Fetcher(_routes()), None, log, date(2026, 10, 26))
    assert not log.events and out["bulletins"][0]["number"] == 43 and out["bulletins"][0]["sites"] == {}


def test_item_without_a_pdf_link_is_queued_under_a_manual_key_and_read_once_uploaded(monkeypatch):
    routes = _routes()
    routes[f"/server/api/core/items/{U43}/bundles"] = _bundles()  # el ítem no trae el PDF
    log, needs = _Log(), manual.ManualNeeds()
    out = bs.acquire(_Fetcher(routes), None, log, date(2026, 10, 26), needs)
    key = manual.key("imarpe-bsobp", "2026-43")
    assert "bsobp-unreadable" in log.codes() and out["pending"][0]["number"] == 43
    assert needs.items["imarpe-bsobp-2026-43"]["urls"] == [key]

    from enso.fetch import Response

    class _Uploaded(_Fetcher):
        def copy(self, url, accept=()):
            return Response(url, b"%PDF-1.7 b43", "relay-manual", 200, archived_at="2026-10-26T12:00:00Z") \
                if url == key else None

    monkeypatch.setattr("enso.reports.pdf_pages", lambda b: _page43())
    needs = manual.ManualNeeds()
    out = bs.acquire(_Uploaded(routes), out, _Log(), date(2026, 10, 27), needs)
    top = out["bulletins"][0]
    assert top["number"] == 43 and top["channel"] == "relay-manual" and top["url"] is None
    assert needs.used and needs.used[0]["id"] == "imarpe-bsobp-2026-43" and not needs.items


def test_partial_run_keeps_the_published_bulletins(tmp_path):
    from enso import observatory as obs
    from conftest import FIX

    full = tmp_path / "full"
    obs.run(full, None, fixtures=FIX)
    assert (full / "imarpe-bsobp.json").exists()
    part = tmp_path / "part"
    obs.run(part, str(full), offline=True, only=["cpc-sstoi"])
    kept = json.loads((part / "imarpe-bsobp.json").read_text(encoding="utf-8"))
    assert kept["bulletins"][0]["number"] == 42
