"""Copias del flujo de n8n (rama ``data-n8n``) como canal «relay-n8n».

La copia la arma el mismo código que corre en los nodos de n8n
(``n8n/lib``), ejecutado con Node; si Node no está, se omiten.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from conftest import FIX
from enso.fetch import FetchError, Fetcher, Relay

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="hace falta Node para armar la copia de n8n")

FEED = FIX.parent / "news-probe" / "andina.xml"
ONI = FIX / "cpc-oni.txt"
PDF = next((FIX.parent / "live-run" / "raw" / "enfen-comunicados").glob("*.pdf"))
U_FEED = "https://andina.pe/agencia/rss/3.xml"
U_ONI = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
U_PDF = "https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/?wpdmdl=2165"
U_DHN = "https://www.dhn.mil.pe/Archivos/oceanografia/enfen/comunicado-oficial/18-2026.pdf"
CHALLENGE = "<!DOCTYPE html><html><head><title>Verificación de seguridad</title></head><body>g-recaptcha</body></html>"


def snapshot(tmp_path: Path, items: list[dict], previous: Path | None = None) -> Path:
    out = tmp_path / "n8n"
    out.mkdir(exist_ok=True)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(items), encoding="utf-8")
    env = {"PATH": str(Path(NODE).parent)}
    if previous:
        env["PREVIOUS"] = str(previous)
    subprocess.run([NODE, str(ROOT / "n8n/test/write-snapshot.mjs"), str(out), str(spec)], check=True, env=env)
    return out


@pytest.fixture
def n8n_dir(tmp_path):
    return snapshot(tmp_path, [
        {"url": U_FEED, "expect": "rss", "status": 200, "content_type": "application/rss+xml", "body_file": str(FEED)},
        {"url": U_ONI, "expect": "text", "status": 200, "content_type": "text/plain", "body_file": str(ONI)},
        {"url": U_PDF, "expect": "pdf", "status": 200, "content_type": "application/force-download", "body_file": str(PDF)},
        {"url": U_DHN, "expect": "pdf", "status": 200, "content_type": "text/html", "body": CHALLENGE},
        {"url": "https://www.senamhi.gob.pe/?p=aviso-meteorologico", "expect": "html", "error": "read ECONNRESET"},
    ])


def test_relay_reads_n8n_copies_with_their_channel(n8n_dir):
    relay = Relay(n8n_dir)
    assert relay.channel == "relay-n8n"
    for url, path in ((U_FEED, FEED), (U_ONI, ONI), (U_PDF, PDF)):
        got = relay.get(url)
        assert got is not None and got.body == path.read_bytes(), url
        assert got.channel == "relay-n8n"
    # Una verificación anti-robots o un error no dejan copia.
    assert relay.get(U_DHN) is None
    assert relay.get("https://www.senamhi.gob.pe/?p=aviso-meteorologico") is None
    idx = json.loads((n8n_dir / "index.json").read_text(encoding="utf-8"))
    dhn = next(e for e in idx["entries"] if e["url"] == U_DHN)
    assert (dhn["verdict"], dhn["block"], dhn["reach"]) == ("blocked", "human-verification", "challenge")
    hb = json.loads((n8n_dir / "heartbeat.json").read_text(encoding="utf-8"))
    assert hb["schema"] == "enso-relay-heartbeat/1" and hb["result"] == "ok" and hb["reachable"] == "3/5"


def test_fetcher_falls_back_to_n8n_when_the_source_blocks_actions(n8n_dir):
    def blocked(req):
        return httpx.Response(403, text="Forbidden")

    f = Fetcher(retries=1, polite_delay=0, allow_archive=False, relay=[None, Relay(n8n_dir)])
    f.client = httpx.Client(transport=httpx.MockTransport(blocked))
    got = f.get([U_PDF], accept=("pdf", "octet-stream", "force-download"))
    assert got.channel == "relay-n8n" and got.body[:5] == b"%PDF-"
    assert got.attempts[-1]["channel"] == "relay-n8n"
    with pytest.raises(FetchError):
        f.get([U_DHN])


def test_the_freshest_relay_wins(tmp_path, n8n_dir, monkeypatch):
    import enso.fetch

    monkeypatch.setattr(enso.fetch.time, "sleep", lambda s: None)
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(timespec="seconds")
    (tmp_path / "p").mkdir()
    peru = snapshot(tmp_path / "p", [
        {"url": U_ONI, "expect": "text", "status": 200, "content_type": "text/plain", "body": " SEAS  YR  viejo", "fetched_at": old},
    ])
    idx = json.loads((peru / "index.json").read_text(encoding="utf-8"))
    idx["collector"]["kind"] = "peru"
    (peru / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False, relay=[Relay(peru), Relay(n8n_dir)])
    f.client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    got = f.get([U_ONI])
    assert got.channel == "relay-n8n" and got.body == ONI.read_bytes()


def test_old_entries_are_not_used_even_in_a_fresh_index(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat(timespec="seconds")
    d = snapshot(tmp_path, [{"url": U_ONI, "expect": "text", "status": 200, "body": " SEAS  YR", "fetched_at": old}])
    assert Relay(d).get(U_ONI) is None
