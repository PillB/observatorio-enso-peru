"""Lectura diaria del escenario de riesgo por distrito del CENEPRED (``enso.cenepred_escenario``): qué escenario se
elige, qué pasa cuando el SIGRID o sus copias fallan o cambian de forma, su fila de vigencia y su paso por n8n, el
recolector del Perú, el archivo del sitio y la publicación."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import pytest

from enso import cenepred_escenario as CE
from enso.feeds import FormatChanged
from enso.fetch import FetchError, Relay, Response
from test_escenario_distritos import _xlsx

LIST = [  # como la del SIGRID: sin orden
    {"id": "40", "mes_inicio_vigencia": "2022-05-01", "mes_fin_vigencia": "2022-07-01", "mes_elaboracion": "2022-05-01", "id_documento": "1"},
    {"id": "102", "mes_inicio_vigencia": "2026-11-01", "mes_fin_vigencia": "2027-01-01", "mes_elaboracion": "2026-10-01", "id_documento": "23277"},
    {"id": "99", "mes_inicio_vigencia": "2026-09-01", "mes_fin_vigencia": "2026-11-01", "mes_elaboracion": "2026-08-01", "id_documento": "3"},
    {"id": "103", "mes_inicio_vigencia": "2027-01-01", "mes_fin_vigencia": "2027-03-01", "mes_elaboracion": "2026-10-01", "id_documento": "23278"},
    {"id": "101", "mes_inicio_vigencia": "2026-10-01", "mes_fin_vigencia": "2026-12-01", "mes_elaboracion": "2026-09-01", "id_documento": "4"},
]
TODAY = date(2026, 11, 10)
N = 1850  # más que MIN_DISTRICTS


def _list(rows=LIST) -> bytes:
    return json.dumps({"draw": 0, "recordsTotal": len(rows), "data": rows}).encode()


def _zip(n: int = N, level: str = "Alto") -> bytes:
    codes = [f"{150101 + i:06d}" for i in range(n)]
    mm = [["UBIGEO", "nriesg_mm", "pob_smm", "viv_smm", "eess_smm", "iiee_smm", "vias_smm"]] + \
        [[c, level, 10, 3, 0, 1, 2.5] for c in codes]
    inu = [["UBIGEO", "nriesg_inu", "pob_sinu", "viv_sinu", "eess_sinu", "iiee_sinu", "vias_sinu"]] + \
        [[c, "Bajo", 0, 0, 0, 0, 0] for c in codes]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Tablas/Dist_Riesgo_MMasa.xlsx", _xlsx({"BD_ERMMasa": mm}))
        z.writestr("Tablas/Dist_Riesgo_Inundacion.xlsx", _xlsx({"BD_ERInund": inu}))
    return buf.getvalue()


ZIP = _zip()


class _Fetcher:
    """Responde por URL: bytes (respuesta directa), una ``Response`` (p. ej. de un relay) o una excepción."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.asked: list[tuple[str, tuple]] = []

    def get(self, urls, *, archive=True, save=False, accept=()):
        url = urls[0]
        self.asked.append((url, accept))
        r = self.routes.get(url)
        if r is None or isinstance(r, Exception):
            raise r if isinstance(r, Exception) else FetchError(f"sin respuesta válida para {url}", [])
        return r if isinstance(r, Response) else Response(url, r, "direct", 200, "application/json")


class _Log:
    def __init__(self):
        self.events: list[tuple[str, str]] = []

    def add(self, severity, source, stage, code, message):
        assert source == CE.SOURCE
        self.events.append((severity, code))

    def codes(self):
        return [c for _, c in self.events]


def _ok_routes(zip_bytes=ZIP, sid="102"):
    return {CE.LIST_URL: _list(), CE.TABLE_URL.format(id=sid): zip_bytes}


def _previous(sid="101") -> dict:
    doc = CE.build({**[s for s in LIST if s["id"] == sid][0]}, CE.read_tables(ZIP), "x")
    return {**doc, "retrievedAt": "2026-10-01T05:00:00+00:00", "channel": "direct", "carried": False,
            "schema": "observatorio-enso/4", "publicationId": "p", "generatedAt": "g"}


# --- Qué escenario se publica ----------------------------------------------------------------------------------------

def test_publishes_the_scenario_in_force_today_prepared_most_recently_and_names_the_next():
    shown, why, nxt = CE.choose(CE.scenarios(_list()), TODAY)
    # 99 (septiembre a noviembre), 101 (octubre a diciembre) y 102 (noviembre a enero) están vigentes: gana el más
    # reciente; el 103 (enero a marzo) ya está publicado y es el siguiente.
    assert (shown["id"], why, nxt["id"]) == ("102", "vigente", "103")


def test_with_two_in_force_the_most_recently_prepared_wins_then_the_latest_start_then_the_number():
    rows = LIST + [{"id": "104", "mes_inicio_vigencia": "2026-12-01", "mes_fin_vigencia": "2027-02-01",
                    "mes_elaboracion": "2026-11-01", "id_documento": "9"}]
    assert CE.choose(CE.scenarios(_list(rows)), date(2027, 1, 5))[0]["id"] == "104"  # 102, 103 y 104 vigentes
    same = [{**LIST[1], "id": "120", "mes_inicio_vigencia": "2026-11-01"}, LIST[1]]
    assert CE.choose(CE.scenarios(_list(same)), TODAY)[0]["id"] == "120"


def test_before_any_is_in_force_the_next_to_start_and_when_all_ended_the_last_one():
    future = [s for s in LIST if s["id"] == "103"]
    assert CE.choose(CE.scenarios(_list(future)), TODAY)[:2] == (CE.scenarios(_list(future))[0], "proximo")
    shown, why, nxt = CE.choose(CE.scenarios(_list()), date(2027, 6, 1))
    assert (shown["id"], why, nxt) == ("103", "vencido", None)


@pytest.mark.parametrize("body, why", [
    (b"<html>login</html>", "no es JSON"),
    (json.dumps({"data": []}).encode(), "vacía"),
    (json.dumps({"rows": LIST}).encode(), "no trae"),
    (_list([{**LIST[0], "id": "4 0"}]), "otra forma"),
    (_list([{**LIST[0], "mes_fin_vigencia": "julio"}]), "otra forma"),
    (_list([{**LIST[0], "mes_inicio_vigencia": "2022-09-01"}]), "termina antes de empezar"),
])
def test_a_list_with_another_shape_stops_instead_of_guessing(body, why):
    with pytest.raises(FormatChanged, match=why):
        CE.scenarios(body)


# --- Lectura diaria ---------------------------------------------------------------------------------------------------

def test_reads_the_list_and_the_zip_of_todays_scenario_with_provenance():
    f, log = _Fetcher(_ok_routes()), _Log()
    doc = CE.acquire(f, None, log, TODAY)
    assert log.events == []
    assert [u for u, _ in f.asked] == [CE.LIST_URL, CE.TABLE_URL.format(id="102")]
    assert f.asked[1][1] == ("zip",)  # una página HTML en lugar del ZIP no sirve, tampoco la de una copia
    assert doc["scenario"] == {"id": "102", "from": "2026-11", "until": "2027-01", "prepared": "2026-10"}
    assert doc["channel"] == "direct" and doc["carried"] is False and doc["retrievedAt"]
    assert doc["listed"]["next"]["id"] == "103" and doc["listed"]["count"] == len(LIST)
    assert len(doc["districts"]) == N and doc["_raw"] == ZIP and len(doc["tableSha256"]) == 64
    assert doc["generatedBy"].startswith("enso.cenepred_escenario")


def test_a_copy_from_n8n_or_peru_keeps_its_channel_and_the_time_it_was_collected():
    routes = _ok_routes()
    routes[CE.TABLE_URL.format(id="102")] = Response(CE.TABLE_URL.format(id="102"), ZIP, "relay-n8n", 200,
                                                     "application/x-zip-compressed", archived_at="2026-11-10T03:50:00+00:00")
    doc = CE.acquire(_Fetcher(routes), None, _Log(), TODAY)
    assert (doc["channel"], doc["retrievedAt"]) == ("relay-n8n", "2026-11-10T03:50:00+00:00")


def test_when_sigrid_and_its_copies_fail_the_published_scenario_is_kept_and_marked():
    log = _Log()
    doc = CE.acquire(_Fetcher({}), _previous(), log, TODAY)
    assert log.codes() == ["escenario-unreachable"]
    assert doc["scenario"]["id"] == "101" and doc["carried"] is True and doc["checkedAt"] == TODAY.isoformat()
    assert "no respondió" in doc["problem"] and doc["retrievedAt"] == "2026-10-01T05:00:00+00:00"


def test_without_a_previous_scenario_the_copy_bundled_with_the_site_is_published():
    log = _Log()
    doc = CE.acquire(_Fetcher({}), None, log, TODAY)
    assert log.codes() == ["escenario-unreachable", "escenario-seed"]
    assert doc["seed"] is True and doc["channel"] == "seed" and doc["retrievedAt"] is None
    assert len(doc["districts"]) >= 1891


@pytest.mark.parametrize("body", [b"<!doctype html><html>Iniciar sesi\xc3\xb3n</html>", b"PK\x03\x04roto", _zip(n=40),
                                  _zip(level="Altísimo")])
def test_a_table_that_is_not_the_expected_zip_is_an_error_and_the_previous_stays(body):
    log = _Log()
    doc = CE.acquire(_Fetcher(_ok_routes(body)), _previous(), log, TODAY)
    assert log.events == [("error", "escenario-format")]
    assert doc["scenario"]["id"] == "101" and doc["carried"] and doc["listed"]["next"]["id"] == "103"


def test_a_list_with_another_shape_is_an_error_and_the_previous_stays():
    log = _Log()
    doc = CE.acquire(_Fetcher({CE.LIST_URL: b"<html>mantenimiento</html>"}), _previous(), log, TODAY)
    assert log.events == [("error", "escenario-format")] and doc["scenario"]["id"] == "101"


def test_a_newer_scenario_whose_zip_does_not_arrive_says_so():
    log = _Log()
    doc = CE.acquire(_Fetcher({CE.LIST_URL: _list()}), _previous("101"), log, TODAY)
    assert log.codes() == ["escenario-newer-unread"] and doc["scenario"]["id"] == "101"
    log = _Log()
    CE.acquire(_Fetcher({CE.LIST_URL: _list()}), _previous("102"), log, TODAY)
    assert log.codes() == ["escenario-unreachable"]  # el mismo escenario: no hay uno nuevo sin leer


def test_a_previous_publication_that_is_broken_is_not_carried():
    bad = {**_previous(), "districts": {"150101": [[0, 1, 1, 1, 1, 1], None]}}
    log = _Log()
    doc = CE.acquire(_Fetcher({}), bad, log, TODAY)
    assert doc["seed"] is True and "escenario-seed" in log.codes()


def test_when_every_scenario_ended_it_still_publishes_the_last_one_and_warns():
    log = _Log()
    doc = CE.acquire(_Fetcher(_ok_routes(sid="103")), None, log, date(2027, 6, 1))
    assert log.codes() == ["escenario-vencido"] and doc["scenario"]["id"] == "103"


# --- Vigencia ---------------------------------------------------------------------------------------------------------

def _fresh(today, **kw):
    doc = CE.acquire(_Fetcher(_ok_routes()), None, _Log(), TODAY)
    return CE.freshness_item({**doc, **kw}, today)


def test_freshness_row_is_up_to_date_until_a_newer_monthly_scenario_is_overdue():
    it = _fresh(TODAY)
    assert (it["state"], it["observed"], it["observedKind"], it["expectedNext"]) == ("al-dia", "2026-10", "month", "2026-12-01")
    assert it["validFrom"] == "2026-11" and it["validUntil"] == "2027-01" and "N° 102" in it["document"]
    assert "N° 103" in it["note"]  # el siguiente ya publicado
    assert _fresh(date(2026, 12, 16))["state"] == "al-dia"  # 15 días de margen
    assert _fresh(date(2026, 12, 17))["state"] == "atrasado"
    assert _fresh(date(2027, 2, 1))["state"] == "vencido" and "terminó" in _fresh(date(2027, 2, 1))["note"]


def test_freshness_row_of_a_kept_or_bundled_scenario_is_late_and_says_why():
    it = _fresh(TODAY, carried=True, problem="la lista de escenarios del SIGRID no respondió")
    assert it["state"] == "atrasado" and "no respondió" in it["note"]
    seed = CE.freshness_item(CE.from_seed(TODAY), TODAY)
    assert seed["state"] == "atrasado" and "copia incluida en el sitio" in seed["note"]
    assert CE.freshness_item(None, TODAY)["state"] == "sin-dato"


def test_mi_zona_has_its_own_freshness_view_and_a_late_scenario_is_logged():
    from enso import freshness

    doc = CE.acquire(_Fetcher(_ok_routes()), None, _Log(), TODAY)
    fresh = freshness.build({}, None, {}, {}, None, None, date(2026, 12, 20), None, escenario=doc)
    assert fresh["views"]["zona"]["items"] == ["alerts", "escenario"]
    assert fresh["items"]["escenario"]["state"] == "atrasado"

    class L:
        events = []

        def add(self, *a):
            self.events.append(a)

    log = L()
    freshness.log_late(fresh, log)
    assert any(e[3] == "late-escenario" for e in log.events)


# --- n8n, el Perú, el registro y el archivo -------------------------------------------------------------------------

def test_the_registry_rule_is_the_one_the_collectors_follow():
    from enso import registry

    e = next(s for s in registry.build(reach={})["sources"] if s["id"] == "cenepred-sigrid-escenarios")
    assert e["url"] == CE.LIST_URL and e["follow"] == CE.FOLLOW and e["expect"] == "json"
    assert {"actions", "n8n"} <= set(e["channels"])


def test_peru_collector_follows_the_template_highest_numbers_first_same_host_only(monkeypatch):
    from tools import peru_collector as pc

    got = []
    monkeypatch.setattr(pc, "fetch", lambda client, url, expect=None: got.append((url, expect)) or {"url": url})
    body = json.dumps({"data": LIST + [{"id": "1/../x"}, {"id": "7\""}]}).encode()
    page = {"url": CE.LIST_URL, "status": 200, "body": body}
    seen: set[str] = set()
    pc.follow_links(None, page, CE.FOLLOW, seen)
    assert got == [(CE.TABLE_URL.format(id=i), "zip") for i in ("103", "102", "101")]
    # Fuera del servidor de la lista no se sigue (su robots.txt no se leyó).
    got.clear()
    pc.follow_links(None, page, {**CE.FOLLOW, "template": "https://otro.example/{1}.zip"}, set())
    assert got == []
    groups, follow = pc.plan({"sources": []})
    assert CE.LIST_URL in groups["cenepred"] and follow[CE.LIST_URL] == CE.FOLLOW
    assert pc.EXPECT[CE.LIST_URL] == "json" and pc.EXT["zip"] == ".zip"


def test_a_zip_is_recognised_kept_and_served_by_every_channel(tmp_path):
    import hashlib

    from enso import archive, reach

    assert reach.detect(ZIP) == "zip"
    assert reach.judge(200, ZIP, "application/x-zip-compressed", "zip")[0] == "ok"
    cls, _, why = reach.judge(200, b"<!doctype html><html>" + b"x" * 600, "text/html", "zip")
    assert cls == "empty" and "ZIP" in why
    assert archive.kind(ZIP) == "zip" and archive.kind(b"PK\x03\x04roto") == "txt"
    assert archive._is_archive_path(archive.source_path(CE.SOURCE, ZIP))
    sha = hashlib.sha256(ZIP).hexdigest()
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / f"{sha[:16]}.zip").write_bytes(ZIP)
    url = CE.TABLE_URL.format(id="102")
    (tmp_path / "index.json").write_text(json.dumps({"schema": "enso-relay/1", "collected_at": "2099-01-01T00:00:00+00:00",
        "collector": {"kind": "n8n"}, "entries": [{"url": url, "status": 200, "file": f"files/{sha[:16]}.zip", "sha256": sha,
                                                   "content_type": "application/x-zip-compressed", "detected": "zip",
                                                   "fetched_at": "2099-01-01T00:00:00+00:00"}]}), encoding="utf-8")
    r = Relay(tmp_path, max_age_hours=10**9).get(url, ("zip",))
    assert r is not None and r.body == ZIP and r.channel == "relay-n8n"


def test_n8n_classifier_detects_a_zip_like_python(tmp_path):
    import shutil
    import subprocess

    from conftest import ROOT

    node = shutil.which("node")
    if not node:
        pytest.skip("sin Node")
    js = ("const c=require(%r);const b=Buffer.from(process.argv[1],'base64');"
          "console.log(c.detectFormat(new Uint8Array(b),'')+' '+c.fileExtension('zip'))") % str(ROOT.parent / "n8n" / "lib" / "classify.js")
    import base64

    out = subprocess.run([node, "-e", js, base64.b64encode(ZIP[:64]).decode()], capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["zip", "zip"]


# --- La publicación ---------------------------------------------------------------------------------------------------

def test_the_publication_carries_the_scenario_its_archived_zip_and_the_freshness_row(tmp_path, monkeypatch):
    from conftest import FIX
    from enso import observatory as obs

    full = tmp_path / "full"
    obs.run(full, None, fixtures=FIX)  # con fixtures: la copia incluida en el sitio
    doc = json.loads((full / "escenario-distritos.json").read_text(encoding="utf-8"))
    assert doc["seed"] is True and doc["schema"] == obs.SCHEMA and len(doc["districts"]) >= 1891
    dash = json.loads((full / "dashboard.json").read_text(encoding="utf-8"))
    assert dash["freshness"]["items"]["escenario"]["source"] == CE.SOURCE
    assert dash["freshness"]["views"]["zona"]["items"] == ["alerts", "escenario"]

    # Una corrida en vivo que lee el SIGRID: el JSON y el ZIP archivado, enlazado desde el JSON.
    monkeypatch.setattr(obs, "acquire_escenario", lambda *a, **k: CE.acquire(_Fetcher(_ok_routes()), None, _Log(), TODAY))
    live = tmp_path / "live"
    obs.run(live, str(full), fixtures=FIX)
    doc = json.loads((live / "escenario-distritos.json").read_text(encoding="utf-8"))
    assert "_raw" not in doc and doc["archive"].endswith(".zip") and (live / doc["archive"]).read_bytes() == ZIP
    index = json.loads((live / "archive" / "index.json").read_text(encoding="utf-8"))
    assert any(f["path"] == doc["archive"] and f["source"] == CE.SOURCE for f in index["files"])

    # Una corrida parcial sin red conserva el publicado y su copia archivada.
    monkeypatch.undo()
    part = tmp_path / "part"
    obs.run(part, str(live), offline=True, only=["cpc-sstoi"])
    kept = json.loads((part / "escenario-distritos.json").read_text(encoding="utf-8"))
    assert kept["scenario"]["id"] == "102" and kept["carried"] is True and (part / kept["archive"]).read_bytes() == ZIP


def test_the_scenario_is_also_published_as_a_csv_with_district_names():
    import csv

    doc = CE.from_seed(TODAY)
    rows = list(csv.DictReader(io.StringIO(CE.csv_text(doc))))
    assert len(rows) == len(doc["districts"])
    lima = next(r for r in rows if r["ubigeo"] == "150101")
    mm, inu = doc["districts"]["150101"]
    assert (lima["departamento"], lima["distrito"]) == ("Lima", "Lima")
    assert lima["nivel_movimientos_en_masa"] == doc["levels"][mm[0]] and lima["nivel_inundaciones"] == doc["levels"][inu[0]]
    assert int(lima["personas_inundaciones"]) == inu[1] and lima["escenario"] == doc["scenario"]["id"]
    assert not any(v.startswith(("=", "+", "@")) for r in rows for v in r.values())
