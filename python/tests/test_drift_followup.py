"""Revisión adversarial del PR #131 (21 de noviembre de 2026): cada caso que las guardias nuevas no cubrían.

Guardia de regresión con base arrastrada o ilegible, códigos de ``enso.drift`` que no se cierran solos, avisos de
fuentes de peligros (copias que n8n arrastra, feeds no pedidos, dos corridas el mismo día), páginas de verificación en
el Internet Archive, simulacros del PTWC, ``valuesInTextBasis`` anclado a la fecha de la discusión y la auditoría
semanal (``tools.drift_audit``: ventana, hallazgos revisados, códigos de salida)."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, datetime, timezone

import httpx
import pytest

from conftest import FIX
from enso import drift
from enso import observatory as obs
from enso.fetch import Fetcher, Response, block_page
from enso.observatory import SOURCE_BY_ID

DRIFT = FIX.parent / "drift"
SRC = SOURCE_BY_ID["psl-ersst6-nino34"]


def _parse(name: str):
    return SRC.parse(Response(SRC.urls[0], (DRIFT / name).read_bytes(), "direct", 200))


class _Previous:
    def __init__(self, doc, state="ok"):
        self.doc, self.base = doc, "https://example.org/data"
        self.state = {f"sources/{SRC.id}.json": state}

    def get(self, name, carry=False, tries=1):
        return self.doc


class _Fetch:
    def get(self, urls, **kw):
        return Response(urls[0], (DRIFT / "psl-nina34-20261118.data").read_bytes(), "direct", 200)


def test_carried_previous_publication_is_still_the_baseline():
    """Un día sin respuesta arrastra el dato; si la reescritura llega el día en que la fuente vuelve, igual se ve."""
    before = _parse("psl-nina34-20261106.data")
    prev = {"data": before.data, "fingerprint": before.fingerprint, "url": SRC.urls[0], "carried": True,
            "retrievedAt": "2026-11-06T13:30:00+00:00"}
    log = obs.EventLog()
    obs.acquire(SRC, _Fetch(), None, _Previous(prev), log)
    ev = [e for e in log.events if e.code == "history-rewritten"]
    assert ev and "arrastrada" in ev[0].message and "2026-11-06T13:30" in ev[0].message


def test_unreadable_previous_publication_is_logged_not_silent():
    log = obs.EventLog()
    obs.acquire(SRC, _Fetch(), None, _Previous(None, state="unreachable"), log)
    assert [e for e in log.events if e.code == "drift-unchecked" and e.severity == "info"]
    # Una fuente nueva (sin publicación anterior) no es una comparación perdida.
    log = obs.EventLog()
    obs.acquire(SRC, _Fetch(), None, _Previous(None, state="missing"), log)
    assert not [e for e in log.events if e.code == "drift-unchecked"]


def test_one_point_without_period_does_not_make_the_series_missing():
    pts = [{"period": f"2020-{m:02d}", "value": 0.1 * m} for m in range(1, 13)]
    broken = pts[:5] + [{"value": 9.9}] + pts[5:]
    assert dict(drift.series(broken))["$"] == pts
    assert not drift.compare(pts, broken)


def test_exactly_the_threshold_is_not_a_rewrite():
    """2,61 − 2,36 en coma flotante da 0,2500000000000001: sin redondeo, un cambio de 0,25 exacto contaba."""
    old = [{"period": f"{2000 + i // 12}-{i % 12 + 1:02d}", "value": 2.36} for i in range(120)]
    new = [dict(p, value=2.61) for p in old]
    assert not drift.compare(old, new)
    assert [c for c, _ in drift.compare(old, [dict(p, value=2.62) for p in old])] == ["history-rewritten"]


def test_drift_codes_stay_open_with_their_own_wording():
    """Comparan con la publicación anterior: al día siguiente no se repiten aunque el dato malo siga publicado."""
    from tools import sync_issues as S

    assert {"history-rewritten", "series-shrunk", "series-regressed", "series-missing"} <= S.STICKY
    assert S.NOUN["history-rewritten"] != S.NOUN["format-drift"]


# --- Fuentes oficiales de peligros -------------------------------------------------------------------------------

def _st(ok=False, at="2026-11-20T13:38:00+00:00", **kw):
    return {"id": "igp-cenvul-alertas", "ok": ok, "checkedAt": at, "error": "" if ok else "HTTP 500", **kw}


def test_hazard_down_counts_carried_n8n_copies_and_ignores_unrequested_feeds():
    assert obs.hazard_down(_st())
    assert obs.hazard_down(_st(ok=True, upstreamDown={"status": 500}))
    assert not obs.hazard_down(_st(ok=True))
    assert not obs.hazard_down(_st(omitted="deadline"))
    assert not obs.hazard_down(_st(error="omitido: se agotó el tiempo de la recolección de noticias"))
    assert not obs.hazard_down(_st(skipped=True)) and not obs.hazard_down(None)


def test_two_runs_forty_minutes_apart_are_not_two_days_down():
    assert obs._hours_between(_st(at="2026-11-19T20:29:02+00:00"), _st(at="2026-11-19T21:07:11+00:00")) < 6
    assert obs._hours_between(_st(at="2026-11-19T13:38:00+00:00"), _st(at="2026-11-20T04:20:00+00:00")) > 6
    assert obs._hours_between({"checkedAt": "x"}, _st()) == 24.0


def test_relay_passes_on_that_n8n_carried_its_copy(tmp_path):
    from enso.fetch import Relay
    import hashlib

    body = b"<html><body>" + b"<div>bolet\xc3\xadn</div>" * 400 + b"</body></html>"
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "0123456789abcdef.html").write_bytes(body)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (tmp_path / "index.json").write_text(json.dumps({
        "schema": "enso-relay/1", "collected_at": now, "collector": {"kind": "n8n"},
        "entries": [{"url": "https://cenvul.igp.gob.pe/x", "status": 200, "file": "files/0123456789abcdef.html",
                     "sha256": hashlib.sha256(body).hexdigest(), "content_type": "text/html", "fetched_at": now,
                     "carried": True, "last_attempt": {"at": now, "verdict": "server_error", "status": 500}}]}),
        encoding="utf-8")
    got = Relay(tmp_path).get("https://cenvul.igp.gob.pe/x")
    assert got is not None and got.upstream_down == {"status": 500, "verdict": "server_error", "at": now}


def test_feeds_skipped_for_the_deadline_are_marked_omitted():
    from enso import news as N

    feeds = [f for f in N.FEEDS if obs.official_alerts(f)][:3]
    _, statuses, _ = N.collect(lambda u: (200, b"<rss/>", "", ""), datetime.now(timezone.utc), feeds=feeds,
                             deadline=-1)
    assert statuses and all(st.get("omitted") == "deadline" for st in statuses)
    assert not any(obs.hazard_down(st) for st in statuses)


# --- Páginas de verificación ---------------------------------------------------------------------------------------

def test_internet_archive_copy_of_a_challenge_page_is_not_used(monkeypatch):
    page = (FIX / "blocked" / "imunify360-soltv-piura-20261119.html").read_bytes()
    url = "https://example.pe/feed/"

    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if "robots.txt" in u:
            return httpx.Response(404)
        if "/cdx/search/cdx" in u:
            return httpx.Response(200, json=[["urlkey", "timestamp", "original"], ["k", "20261119000000", url]])
        if "web.archive.org/web/" in u:
            return httpx.Response(200, content=page, headers={"content-type": "text/html"})
        return httpx.Response(503)

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(handler)}))
    f = Fetcher(polite_delay=0, retries=1)
    attempts: list = []
    assert f._from_archive(url, attempts, fresh=False) is None
    assert any(a.get("class") == "challenge" for a in attempts)


def test_dhn_human_check_in_place_of_a_pdf_is_a_challenge():
    """Desde noviembre de 2026 cada PDF de /Archivos de la DHN redirige a /human-check.php (Turnstile)."""
    assert block_page((FIX / "blocked" / "dhn-human-check-informe-20-2026.html").read_bytes())


def test_ptwc_exercise_message_is_not_an_alert():
    from enso.hazardparse import parse_ptwc_text

    assert parse_ptwc_text((FIX / "news-ptwc-wepa40-test-pacwave26.txt").read_bytes()).items == []
    assert len(parse_ptwc_text((FIX / "news-ptwc-wepa40.txt").read_bytes()).items) == 1


# --- Contrastes del informe y de la discusión de NOAA ----------------------------------------------------------

def test_values_basis_is_anchored_to_the_discussion_date():
    """Tres semanas después de la discusión las series ya tienen semanas nuevas: el campo no debe cambiar."""
    b = obs.Builder({}, obs.EventLog(), date(2026, 12, 3))
    wk = {"nino34": [{"date": "2026-11-04", "anom": 3.2}, {"date": "2026-11-11", "anom": 3.3},
                     {"date": "2026-11-18", "anom": 2.9}, {"date": "2026-11-25", "anom": 2.7}]}
    b.data = lambda sid: {"cpc-wksst": wk, "cpc-sstoi": {}}.get(sid)
    assert b.ensodisc_basis({"nino34": 3.3}, "2026-11-12") == "traditional-weekly"
    assert b.ensodisc_basis({"nino34": 3.3}) == "other"  # sin fecha: las dos últimas semanas


def test_equal_distances_do_not_pick_a_side():
    from test_cross_checks import _builder, _informe

    inf = _informe()
    inf["icenProvisional"] = dict(inf["icenProvisional"], icen=4.74)  # a 0,24 de los dos
    b = _builder()
    out = b.informe(inf)
    assert out["icenMismatch"]["consistentWith"] == "undetermined"
    assert "no permite decidir" in next(e for e in b.log.events if e.code == "informe-icen-mismatch").message


def test_oni_difference_of_exactly_one_tenth_is_not_flagged():
    from test_cross_checks import _builder, _informe

    for oni in (2.36, 2.56):  # el informe dice +2,46; 0,1 exacto en coma flotante a veces pasaba
        b = _builder(oni_sep=oni)
        b.informe(_informe())
        assert not [e for e in b.log.events if e.code == "informe-oni-mismatch"], oni


# --- Auditoría semanal -----------------------------------------------------------------------------------------

def _archive(tmp_path):
    repo = tmp_path / "repo"
    d = repo / "sources" / SRC.id
    d.mkdir(parents=True)
    shutil.copy(DRIFT / "psl-nina34-20261106.data", d / "2026-11-06-a.txt")
    shutil.copy(DRIFT / "psl-nina34-20261118.data", d / "2026-11-18-b.txt")
    (repo / "sources" / "news-ciifen").mkdir()
    shutil.copy(FIX / "blocked" / "imunify360-soltv-piura-20261119.html",
                repo / "sources" / "news-ciifen" / "2026-11-19-c.html")
    for cmd in (["init", "-q"], ["add", "-A"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "a"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    return repo


def test_audit_window_keeps_the_previous_version_as_baseline(tmp_path, monkeypatch):
    from tools import drift_audit as A

    monkeypatch.setattr(A, "ROOT", _archive(tmp_path))
    kinds = sorted(f["kind"] for f in A.audit("HEAD", since="2026-11-15"))
    assert kinds == ["archived-block-page", "history-rewritten"]  # .html también se revisa
    assert A.audit("HEAD", since="2026-11-20") == []
    assert [f["kind"] for f in A.audit("HEAD", only={SRC.id})] == ["history-rewritten"]  # --source limita todo


def test_audit_exit_codes(tmp_path, monkeypatch, capsys):
    from tools import drift_audit as A

    monkeypatch.setattr(A, "ROOT", _archive(tmp_path))
    monkeypatch.setattr(A, "KNOWN", tmp_path / "none.json")
    assert A.main(["--ref", "HEAD"]) == 1
    assert A.main(["--ref", "no-such-ref"]) == 2
    assert A.main(["--ref", "HEAD", "--source", "no-such-source"]) == 2
    reviewed = tmp_path / "known.json"
    reviewed.write_text(json.dumps({"findings": [f | {"note": "revisado"} for f in
                                                 ({"kind": k, "file": p} for k, p in (
                                                     ("history-rewritten", f"sources/{SRC.id}/2026-11-18-b.txt"),
                                                     ("archived-block-page", "sources/news-ciifen/2026-11-19-c.html")))]}),
                        encoding="utf-8")
    monkeypatch.setattr(A, "KNOWN", reviewed)
    assert A.main(["--ref", "HEAD"]) == 0
    assert A.main(["--ref", "HEAD", "--all"]) == 1
    assert "ya revisados" in capsys.readouterr().err


def test_reviewed_findings_file_is_well_formed():
    from tools import drift_audit as A

    doc = json.loads(A.KNOWN.read_text(encoding="utf-8"))
    assert doc["findings"] and all({"kind", "file", "note"} <= set(f) and f["note"] for f in doc["findings"])
    assert {f["kind"] for f in doc["findings"]} == {"archived-block-page", "history-rewritten"}
