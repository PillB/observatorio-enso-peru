"""Guardia de regresión entre corridas (``enso.drift``) con copias reales de las fuentes."""

from __future__ import annotations

import copy

from conftest import FIX
from enso import drift
from enso.feeds import cpc, peru
from enso.observatory import SOURCE_BY_ID

DRIFT = FIX.parent / "drift"


def _psl(name: str) -> list[dict]:
    return cpc.parse_psl_matrix((DRIFT / name).read_text(encoding="utf-8"), name="ersst6-nino34").data


def _codes(prev, cur) -> list[str]:
    return [c for c, _ in drift.compare(prev, cur, "x")]


def test_psl_nino34_rewrite_of_november_2026_is_flagged():
    """PSL reescribió toda la serie Niño 3.4 ERSSTv6 entre el 6 y el 18 de noviembre de 2026 con la misma cabecera
    (1997-12: +1,78 → +2,36). La huella de formato no cambió y nada avisó: esta guardia sí."""
    before, after = _psl("psl-nina34-20261106.data"), _psl("psl-nina34-20261118.data")
    out = drift.compare(before, after, "psl-ersst6-nino34")
    assert [c for c, _ in out] == ["history-rewritten"]
    assert "1997-12" in out[0][1] and "+1.78 → +2.36" in out[0][1]
    # La misma lectura dos veces no avisa nada.
    assert drift.compare(after, copy.deepcopy(after)) == []


def test_normal_monthly_update_is_quiet():
    """Un mes nuevo y revisiones de los últimos meses (ONI, ICEN) son lo normal."""
    oni = cpc.parse_seasonal((FIX / "cpc-oni.txt").read_text(encoding="utf-8"), name="oni").data
    older = copy.deepcopy(oni[:-1])
    older[-1]["value"] = round(older[-1]["value"] - 0.1, 2)  # la última estación se revisa
    assert drift.compare(older, oni) == []
    icen = peru.parse_icen_txt((FIX / "igp-icen.txt").read_text(encoding="utf-8")).data
    assert drift.compare(icen[:-1], icen) == []


def test_truncated_regressed_and_missing_series():
    sst = SOURCE_BY_ID["cpc-sstoi"]
    data = cpc.parse_nino_monthly((FIX / "cpc-sstoi.indices").read_text(encoding="utf-8"), name="sstoi").data
    # Archivo truncado: solo los últimos 5 años.
    cut = {k: {r: v[-60:] for r, v in d.items()} for k, d in data.items()}
    assert set(_codes(data, cut)) == {"series-shrunk"}
    # Copia vieja: dos meses menos al final (un espejo atrasado).
    old = {k: {r: v[:-2] for r, v in d.items()} for k, d in data.items()}
    assert "series-regressed" in _codes(data, old) and "series-shrunk" not in _codes(data, old)
    # Una región que deja de venir.
    gone = copy.deepcopy(data)
    del gone["anom"]["nino4"]
    assert _codes(data, gone) == ["series-missing"]
    assert sst.id == "cpc-sstoi"


def test_shifted_column_is_a_rewrite():
    """Una columna corrida (Niño 3 leído como Niño 1+2) mantiene forma y rangos, pero no la historia."""
    data = cpc.parse_nino_monthly((FIX / "cpc-sstoi.indices").read_text(encoding="utf-8"), name="sstoi").data
    shifted = copy.deepcopy(data)
    shifted["anom"]["nino12"] = copy.deepcopy(data["anom"]["nino3"])
    assert "history-rewritten" in _codes(data, shifted)


def test_weekly_and_text_sources_are_handled():
    wk = cpc.parse_weekly((FIX / "cpc-wksst9120.for").read_text(encoding="utf-8")).data
    assert {n for n, _ in drift.series(wk)} >= {"nino12", "nino34"}
    assert drift.compare(wk, wk) == []
    assert list(drift.series({"status": "El Niño Advisory", "listing": [{"id": "20-2026", "date": "2026-11-13"}]})) == []


def test_daily_acquire_logs_the_rewrite_and_sync_issues_keeps_it_open():
    """En la corrida diaria la guardia compara con ``sources/<id>.json`` de la publicación anterior; la incidencia
    queda abierta hasta que una persona revise los valores (``STICKY``), aunque mañana ya no se repita."""
    from enso import observatory as obs
    from enso.fetch import Response
    from tools import sync_issues

    src = SOURCE_BY_ID["psl-ersst6-nino34"]
    before = src.parse(Response(src.urls[0], (DRIFT / "psl-nina34-20261106.data").read_bytes(), "direct", 200))

    class Previous:
        state: dict = {}

        def get(self, name, carry=False, tries=1):
            return {"data": before.data, "fingerprint": before.fingerprint, "url": src.urls[0]}

    class Fetch:
        def get(self, urls, **kw):
            return Response(urls[0], (DRIFT / "psl-nina34-20261118.data").read_bytes(), "direct", 200)

    log = obs.EventLog()
    acq = obs.acquire(src, Fetch(), None, Previous(), log)
    assert acq.ok and not acq.format_drift  # la cabecera no cambió: la huella no lo ve
    ev = [e for e in log.events if e.code == "history-rewritten"]
    assert ev and ev[0].severity == "warning" and ev[0].source == "psl-ersst6-nino34"
    assert "history-rewritten" in sync_issues.STICKY
