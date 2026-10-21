"""Clasificaciones, señal GRD, eventos, SOI Troup y publicación completa."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from conftest import FIX, ROOT, history, read
from enso import observatory as obs
from enso import signals as sig
from enso.feeds import cpc, peru


# ---------------------------------------------------------------------------
# ICEN (Nota Técnica ENFEN 01-2024)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("v,expected", [
    (-1.31, "Fría fuerte"), (-1.3, "Fría moderada"), (-1.11, "Fría moderada"), (-1.1, "Fría débil"),
    (-0.71, "Fría débil"), (-0.7, "Neutra"), (0.0, "Neutra"), (0.5, "Neutra"), (0.51, "Cálida débil"),
    (1.3, "Cálida débil"), (1.31, "Cálida moderada"), (2.1, "Cálida moderada"), (2.11, "Cálida fuerte"),
    (3.5, "Cálida fuerte"), (3.51, "Cálida extraordinaria"),
])
def test_icen_category_edges(v, expected):
    assert sig.icen_category(v)["short"] == expected


def test_icen_policy_document_matches_code():
    doc = yaml.safe_load((ROOT.parent / "config" / "threshold-policies" / "enfen-icen-2024.yaml").read_text(encoding="utf-8"))
    for c in doc["categories"]:
        for v in c["examples"]:
            assert sig.icen_category(v)["short"] == c["label"], (c["label"], v)


def test_events_match_enfen_record():
    """Backtest contra la lista oficial de eventos del IGP/ENFEN."""
    pts = peru.parse_icen_txt(read(FIX / "igp-icen.txt")).data
    ev = {e["start"][:4]: e for e in sig.icen_events(pts) if e["phase"] == "warm"}
    assert ev["1982"]["magnitude"] == "extraordinaria"
    assert ev["1997"]["magnitude"] == "extraordinaria" and ev["1997"]["months"] >= 15
    assert ev["2015"]["magnitude"] == "fuerte"
    assert ev["2017"]["magnitude"] == "moderada"
    assert ev["2023"]["magnitude"] == "fuerte"
    assert sum(e["ongoing"] for e in sig.icen_events(pts)) <= 1


def test_events_need_three_consecutive_months():
    pts = [{"period": f"2020-{m:02d}", "value": v} for m, v in zip(range(1, 7), [0.9, 0.9, 0.2, 0.9, 0.9, 0.9])]
    ev = sig.icen_events(pts)
    assert len(ev) == 1 and ev[0]["start"] == "2020-04" and ev[0]["months"] == 3


# ---------------------------------------------------------------------------
# Señal GRD
# ---------------------------------------------------------------------------
def grd(**inputs):
    return {s["id"]: s for s in sig.grd_signals({k: {"value": v, "period": "2026-09", "source": "t"} for k, v in inputs.items()})["signals"]}


def test_grd_transcription():
    s = grd(coastal_sst=0.0, basin_sst=1.2, soi_troup=-14.5)
    assert s["coastal_sst"]["level"] == "ok"
    assert s["basin_sst"]["level"] == "watch"
    assert s["soi_troup"]["level"] == "alert"
    assert grd(coastal_sst=2.7)["coastal_sst"]["level"] == "alert"
    assert grd(coastal_sst=1.3)["coastal_sst"]["level"] == "watch"


@pytest.mark.parametrize("key,v", [("coastal_sst", 1.0), ("coastal_sst", 2.05), ("coastal_sst", -0.9),
                                   ("basin_sst", 0.8), ("basin_sst", -0.6), ("soi_troup", 9.0)])
def test_grd_gaps_are_never_green(key, v):
    s = grd(**{key: v})[key]
    assert s["level"] == "unclassified" and s["reason"]


def test_grd_stale_and_missing_have_no_colour():
    out = {s["id"]: s for s in sig.grd_signals({"coastal_sst": {"value": 3.0, "period": "2025-01", "stale": True}})["signals"]}
    assert out["coastal_sst"]["level"] == "na"
    assert out["d20_coastal"]["level"] == "na" and "D20" in out["d20_coastal"]["reason"]


def test_grd_wind_direction_uses_cpc_sign():
    s = grd(wind_coastal=3.8, wind_global=-0.4)
    assert s["wind_coastal"]["level"] == "ok" and s["wind_coastal"]["direction"] == "Este a oeste"
    assert s["wind_global"]["level"] == "alert" and s["wind_global"]["direction"] == "Oeste a este"


# ---------------------------------------------------------------------------
# SOI en escala Troup frente a la Oficina de Meteorología de Australia
# ---------------------------------------------------------------------------
def _bom(text):
    """SOI de 30 días de BoM (``inicio,fin,valor``): se toman las ventanas que
    cubren exactamente un mes calendario, equivalentes al SOI mensual."""
    import calendar

    out = {}
    for line in text.splitlines():
        x = line.strip().split(",")
        if len(x) != 3 or not x[0].isdigit():
            continue
        s, e, v = x
        if s[6:] == "01" and s[:6] == e[:6] and int(e[6:]) == calendar.monthrange(int(e[:4]), int(e[4:6]))[1]:
            out[f"{e[:4]}-{e[4:6]}"] = float(v)
    return out


def test_troup_soi_agrees_with_bom_archive():
    t = cpc.parse_year_matrix(read(FIX / "cpc-tahiti.txt"), lo=-50, hi=1100, name="tahiti").data
    d = cpc.parse_year_matrix(read(FIX / "cpc-darwin.txt"), lo=-50, hi=1100, name="darwin").data
    tp = t.get("original") or next(iter(t.values()))
    dp = d.get("original") or next(iter(d.values()))
    ours = {p["period"]: p["value"] for p in obs.troup_soi(tp, dp)}
    bom = {}
    for path in history("bom-soi"):
        bom.update(_bom(read(path)))
    common = sorted(set(ours) & set(bom))
    assert len(common) >= 40
    diffs = [abs(ours[k] - bom[k]) for k in common]
    same_sign = sum((ours[k] < 0) == (bom[k] < 0) for k in common if abs(bom[k]) > 7) / max(1, sum(abs(bom[k]) > 7 for k in common))
    assert sum(diffs) / len(diffs) < 1.2, "SOI Troup difiere demasiado del de BoM"
    assert same_sign > 0.95, "las fases ±7 deben coincidir con BoM"


# ---------------------------------------------------------------------------
# Publicación completa sin red
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pub(tmp_path_factory):
    out = tmp_path_factory.mktemp("pub") / "data"
    res = obs.run(out, None, fixtures=FIX)
    return out, res


def test_publication_is_coherent(pub):
    out, res = pub
    ids = {json.loads(p.read_text(encoding="utf-8"))["publicationId"] for p in out.rglob("*.json")
           if "archive/sources" not in p.as_posix()}  # copias de terceros, tal como se bajaron
    assert ids == {res["publicationId"]}
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for f in man["files"]:
        assert (out / f).exists(), f


def test_publication_contents(pub):
    out, _ = pub
    d = json.loads((out / "dashboard.json").read_text(encoding="utf-8"))
    assert d["official"]["noaa"]["status"]
    for k in ("icen", "roni", "nino12_oisst", "nino34_oisst", "soi_troup", "cpac850", "heat_180w100w"):
        assert d["series"][k]["latest"]["value"] is not None, k
    assert d["series"]["icen"]["latest"]["category"]["short"] == sig.icen_category(d["series"]["icen"]["latest"]["value"])["short"]
    assert len(d["grd"]["signals"]) == 7
    assert any(e["ongoing"] for e in d["events"])
    assert d["weekly"]["nino12"]["latest"]["date"] >= "2026-10-01"
    # No hay campos inventados ni archivos sintéticos del prototipo.
    # ERSSTv6 alimenta Niño 1+2 y 3.4 mensuales; no se publica un ICEN estimado
    # con él porque difiere del oficial hasta 0,7 °C.
    assert d["series"]["nino12"]["source"] == "psl-ersst6-nino12"
    assert "icen_calc" not in d["series"]
    for legacy in ("all-series.json", "latest-grid.json", "forecasts.json", "regional-impact.json"):
        assert not (out / legacy).exists()


def test_stale_official_status_is_flagged(pub):
    """El último PDF disponible en fixtures es anterior al listado: no puede mostrarse como vigente."""
    out, _ = pub
    e = json.loads((out / "dashboard.json").read_text(encoding="utf-8"))["official"]["enfen"]
    assert e["stale"] is True


def test_csv_formula_injection():
    assert obs.csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert obs.csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert obs.csv_safe(-1.5) == "-1.5"
    assert obs.csv_safe("+2.3") == "+2.3"


def test_csv_outputs(pub):
    out, _ = pub
    head = (out / "csv" / "icen.csv").read_text(encoding="utf-8").splitlines()[0]
    assert head == "periodo,valor,unidad,serie,fuente,publicacion"
    assert (out / "csv" / "semanal-regiones-nino.csv").exists()


def test_failed_source_keeps_last_valid_value(pub, tmp_path):
    """Si una fuente falla, se conserva el último dato de la publicación anterior y se registra."""
    prev, _ = pub
    fx = tmp_path / "fx"
    shutil.copytree(FIX, fx, ignore=shutil.ignore_patterns("history"))
    (fx / "igp-icen.txt").unlink()
    idx = json.loads((fx / "index.json").read_text(encoding="utf-8"))
    idx["entries"] = [e for e in idx["entries"] if e.get("file") != "igp-icen.txt"]
    (fx / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    out = tmp_path / "data"
    obs.run(out, str(prev), fixtures=fx)
    d = json.loads((out / "dashboard.json").read_text(encoding="utf-8"))
    assert d["series"]["icen"]["latest"]["carried"] is True
    rep = json.loads((out / "run-report.json").read_text(encoding="utf-8"))
    codes = {(e["source"], e["code"]) for e in rep["events"]}
    assert ("igp-icen", "unreachable") in codes and ("igp-icen", "carried-forward") in codes


def test_format_drift_is_detected(pub, tmp_path):
    prev, _ = pub
    s = json.loads((prev / "sources" / "cpc-roni.json").read_text(encoding="utf-8"))
    s["fingerprint"] = "otra-huella"
    p2 = tmp_path / "prev"
    shutil.copytree(prev, p2)
    (p2 / "sources" / "cpc-roni.json").write_text(json.dumps(s), encoding="utf-8")
    out = tmp_path / "data"
    obs.run(out, str(p2), fixtures=FIX)
    rep = json.loads((out / "run-report.json").read_text(encoding="utf-8"))
    assert any(e["source"] == "cpc-roni" and e["code"] == "format-drift" for e in rep["events"])


def test_a_run_without_news_serves_the_previous_news(pub, tmp_path):
    """Si las noticias no se leyeron (aquí, con --only), la publicación no se cae y sirve las anteriores:
    la siguiente corrida encuentra el histórico donde siempre."""
    prev, _ = pub
    out = tmp_path / "data"
    obs.run(out, str(prev), fixtures=FIX, only=["cpc-roni"])
    for name in ("items.jsonl", "items.csv"):
        assert (out / "news" / name).read_bytes() == (prev / "news" / name).read_bytes(), name
    stamp = ("schema", "publicationId", "generatedAt")
    for name in ("geo/overrides.json", "geo/items.json"):
        a, b = (json.loads((d / name).read_text(encoding="utf-8")) for d in (out, prev))
        assert {k: v for k, v in a.items() if k not in stamp} == {k: v for k, v in b.items() if k not in stamp}, name
    # El estado de los feeds dice de cuándo es y que esta corrida no agregó notas.
    feeds, before = (json.loads((d / "news" / "feeds.json").read_text(encoding="utf-8")) for d in (out, prev))
    assert feeds["carriedFrom"] == before["generatedAt"] and feeds["history"]["added"] == 0
    assert feeds["feeds"] == before["feeds"] and feeds["history"]["items"] == before["history"]["items"]
    # Los grupos enlazan a páginas del archivo que existen; la respuesta cruda de aquel día no se sirve.
    clusters = json.loads((out / "news" / "clusters.json").read_text(encoding="utf-8"))["clusters"]
    links = [link for c in clusters for link in c["links"]]
    assert links and not any("snapshot" in link for link in links)
    assert all((out / link["archive"].split("#")[0]).exists() for link in links if link.get("archive"))
    d = json.loads((out / "dashboard.json").read_text(encoding="utf-8"))
    assert d["news"]["items"] == json.loads((prev / "dashboard.json").read_text(encoding="utf-8"))["news"]["items"]
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert "news/items.jsonl" in man["files"]


def test_a_run_whose_news_failed_keeps_the_last_alerts_and_says_no_source_was_read(pub, tmp_path, monkeypatch):
    """Si leer las noticias falla, las alertas son las últimas conocidas y cada fuente de alertas figura
    como no leída (sin avisos no es sin peligro). Dos corridas así seguidas dicen de cuándo son las noticias."""
    prev, _ = pub

    def boom(*a, **kw):
        raise RuntimeError("simulado")

    monkeypatch.setattr(obs, "acquire_news", boom)
    out = tmp_path / "data"
    obs.run(out, str(prev), fixtures=FIX)
    groups = {g["id"]: g for g in json.loads((out / "feed.json").read_text(encoding="utf-8"))["groups"]}
    before = {g["id"]: g for g in json.loads((prev / "feed.json").read_text(encoding="utf-8"))["groups"]}
    assert groups["alertas"]["items"] and len(groups["alertas"]["items"]) == len(before["alertas"]["items"])
    assert groups["alertas"]["sources"] and not any(s["ok"] for s in groups["alertas"]["sources"])
    for it in groups["alertas"]["items"]:
        assert (out / it["archive"].split("#")[0]).exists()
    first = json.loads((out / "news" / "feeds.json").read_text(encoding="utf-8"))["carriedFrom"]
    again = tmp_path / "data2"
    obs.run(again, str(out), fixtures=FIX)
    assert json.loads((again / "news" / "feeds.json").read_text(encoding="utf-8"))["carriedFrom"] == first


def test_the_last_alerts_keep_their_place_corrections(pub, tmp_path, monkeypatch):
    """Revisión: en una corrida sin noticias las alertas salían del JSONL tal como se guardó, sin la ubicación
    rehecha ni las correcciones de la consola: un aviso corregido volvía a su lugar automático."""
    import shutil

    prev, _ = pub
    alert = next(g for g in json.loads((prev / "feed.json").read_text(encoding="utf-8"))["groups"]
                 if g["id"] == "alertas")["items"][0]
    fix = tmp_path / "fix"
    shutil.copytree(FIX, fix)
    (fix / "geo-overrides.json").write_text(json.dumps({"overrides": [
        {"id": alert["id"].removeprefix("alert-"), "action": "set", "places": ["200101"], "rev": 1}]}), encoding="utf-8")
    out = tmp_path / "data"
    obs.run(out, str(prev), fixtures=fix)

    def where(d):
        g = next(g for g in json.loads((d / "feed.json").read_text(encoding="utf-8"))["groups"] if g["id"] == "alertas")
        return next(i for i in g["items"] if i["id"] == alert["id"])["where"]

    assert where(out) == ["Piura (Piura)"] != alert["where"]

    def boom(*a, **kw):
        raise RuntimeError("simulado")

    monkeypatch.setattr(obs, "acquire_news", boom)
    # Una corrida con capturas no le pide nada a la consola, aunque el entorno tenga su dirección.
    monkeypatch.setenv("GEO_OVERRIDES_URL", "http://127.0.0.1:9/api/geo/overrides")
    again = tmp_path / "data2"
    obs.run(again, str(out), fixtures=fix)
    assert where(again) == ["Piura (Piura)"]
    report = json.loads((again / "run-report.json").read_text(encoding="utf-8"))
    assert not any(e.get("code", "").startswith("overrides-") for e in report.get("events", []))


def test_a_failure_while_looking_for_the_latest_communique_does_not_stop_the_publication(pub, tmp_path, monkeypatch):
    prev, _ = pub

    def boom(*a, **kw):
        raise ValueError("simulado")

    monkeypatch.setattr(obs, "enfen_latest", boom)
    out = tmp_path / "data"
    obs.run(out, str(prev), fixtures=FIX)
    report = json.loads((out / "run-report.json").read_text(encoding="utf-8"))
    assert (out / "dashboard.json").exists()
    assert any(e.get("code") == "latest-exception" for e in report.get("events", []))


def test_the_enfen_communique_is_looked_up_before_the_other_official_sources(pub, tmp_path, monkeypatch):
    """Revisión 7: el tiempo de las fuentes oficiales es uno solo y el ENFEN se pedía al final: un día malo de NOAA
    (lento, 503 o 429) lo agotaba y el comunicado publicado ese día no se leía. Ahora se pide primero (con la
    búsqueda del último comunicado justo después), luego el ICEN y la Discussion; la publicación no cambia de orden."""
    prev, _ = pub
    order = []
    real_acquire, real_latest = obs.acquire, obs.enfen_latest
    monkeypatch.setattr(obs, "acquire", lambda src, *a, **k: order.append(src.id) or real_acquire(src, *a, **k))
    monkeypatch.setattr(obs, "enfen_latest", lambda *a, **k: order.append("latest") or real_latest(*a, **k))
    out = tmp_path / "data"
    obs.run(out, str(prev), fixtures=FIX)
    assert order[:4] == ["enfen-comunicados", "latest", "igp-icen", "cpc-ensodisc"]
    assert sorted(order[4:]) == sorted(s.id for s in obs.SOURCES if s.id not in obs.OFFICIAL_FIRST)
    reg = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in reg["sources"]]
    assert ids == [s.id for s in obs.SOURCES if s.id in ids]


def test_raw_archive_skips_fixtures(tmp_path):
    a = obs.Acquired(obs.SOURCE_BY_ID["cpc-roni"], raw=b"datos", channel="direct", sha256="ab" * 32)
    b = obs.Acquired(obs.SOURCE_BY_ID["cpc-oni"], raw=b"datos", channel="fixture", sha256="cd" * 32)
    assert obs.archive_raw(tmp_path, {"cpc-roni": a, "cpc-oni": b}, date(2026, 10, 20)) == 1
    assert obs.archive_raw(tmp_path, {"cpc-roni": a}, date(2026, 10, 21)) == 0


def test_second_thursday():
    assert obs.second_thursday_after("2026-10-08", date(2026, 10, 20)) == "2026-11-12"


def test_archive_fallback_uses_existing_copy_when_save_fails():
    """Sin DNS hacia la fuente: se usa la copia del archivo (consulta CDX
    codificada) y, si pedir una copia nueva falla, se conserva la existente."""
    import httpx

    from enso.fetch import Fetcher

    seen = []

    def handler(req):
        u = str(req.url)
        seen.append(u)
        if "enfen.imarpe.gob.pe" in req.url.host:
            raise httpx.ConnectError("Temporary failure in name resolution")
        if "/cdx/" in u:
            return httpx.Response(200, json=[["urlkey", "timestamp", "original"],
                                             ["x", "20261014125242", "https://enfen.imarpe.gob.pe/comunicados/"]])
        if "/save/" in u:
            return httpx.Response(523)
        return httpx.Response(200, text="<html>listado</html>")

    f = Fetcher(retries=1, polite_delay=0, allow_save=True)
    f.client = httpx.Client(transport=httpx.MockTransport(handler))
    r = f.get(["https://enfen.imarpe.gob.pe/wp-json/wp/v2/posts?per_page=10&search=comunicado"], save=True)
    assert r.channel == "archive" and r.archived_at.startswith("2026-10-14")
    assert any("url=https%3A%2F%2Fenfen.imarpe.gob.pe%2Fwp-json%2Fwp%2Fv2%2Fposts%3Fper_page%3D10%26search%3Dcomunicado" in u for u in seen)
    assert any("/save/" in u for u in seen)


def test_every_link_has_an_archived_copy_on_the_site(pub):
    """Cada dato y noticia enlaza a una copia servida por el propio sitio, que existe."""
    out, _ = pub
    idx = json.loads((out / "archive" / "index.json").read_text(encoding="utf-8"))
    listed = {f["path"] for f in idx["files"]}
    for f in idx["files"]:
        assert (out / f["path"]).exists(), f
        assert f["path"].rsplit(".", 1)[-1] in {"pdf", "json", "csv", "txt", "html"}, f
    d = json.loads((out / "dashboard.json").read_text(encoding="utf-8"))
    assert d["official"]["enfen"]["archive"].endswith(".pdf")
    assert (out / d["official"]["enfen"]["archive"]).read_bytes()[:5] == b"%PDF-"
    assert d["official"]["noaa"]["archive"] in listed
    for sid, m in d["sources"].items():
        assert m["live"].startswith("http"), sid
        assert m["archive"] in listed, sid
    feed = json.loads((out / "feed.json").read_text(encoding="utf-8"))
    for g in feed["groups"]:
        for it in g["items"]:
            if it.get("url"):
                page, _, anchor = it.get("archive", "").partition("#")
                assert page in listed, it["id"]
                if anchor:  # las alertas enlazan a su entrada en la página del día del archivo de noticias
                    assert f'id="{anchor}"' in (out / page).read_text(encoding="utf-8")
                if it.get("snapshot"):
                    assert it["snapshot"] in listed
    alerts = next(g for g in feed["groups"] if g["id"] == "alertas")["items"]
    assert alerts and feed["groups"][0]["id"] == "alertas"
    assert any(it.get("snapshot") for it in alerts)
    clusters = json.loads((out / "news" / "clusters.json").read_text(encoding="utf-8"))["clusters"]
    assert clusters
    for c in clusters:
        for link in c["links"]:
            page, anchor = link["archive"].split("#")
            assert page in listed
            assert f'id="{anchor}"' in (out / page).read_text(encoding="utf-8")
            if link.get("snapshot"):
                assert link["snapshot"] in listed
    assert all("raw.githubusercontent" not in p and "data-archive" not in p for p in listed)
    # La validación de la publicación ignora las copias de terceros, pero no el índice.
    assert idx["publicationId"] == d["publicationId"]
