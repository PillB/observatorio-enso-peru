"""Páginas de verificación antirobots que llegan con HTTP 200 en lugar del contenido.

En noviembre de 2026 varios sitios WordPress en hostings con Imunify360 (Sol TV, Radio Huancayo, CIIFEN, Los Andes…)
empezaron a responder de vez en cuando a GitHub Actions con «One moment, please...» y HTTP 200. El cliente lo tomaba
como respuesta válida: el lector de feeds fallaba con «la respuesta es una página HTML, no un feed» (anotado solo como
``info``), no se usaba la copia de n8n, que sí traía el feed, y la página quedaba archivada en ``data-archive`` como si
fuera el feed (38 copias). Estas pruebas fijan que una página así se reconoce, no se usa ni se archiva, y que se sigue
con las copias de los recolectores.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import httpx
import pytest

from conftest import FIX
from enso import reach
from enso.fetch import FetchError, Fetcher, Relay, block_page

IMUNIFY = (FIX / "blocked" / "imunify360-soltv-piura-20261119.html").read_bytes()
FEED_URL = "https://soltvperu.com/category/regiones/piura-noticias/feed/"
RSS = (b'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Sol TV</title>'
       b"<item><title>Lluvias en Piura</title><link>https://soltvperu.com/a</link>"
       b"<pubDate>Wed, 18 Nov 2026 03:10:36 +0000</pubDate></item></channel></rss>")


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    import enso.fetch

    monkeypatch.setenv("ENSO_REGISTRY_FILE", str(tmp_path / "sin-registro.json"))
    monkeypatch.setattr(enso.fetch.time, "sleep", lambda s: None)


def _relay(tmp_path, body: bytes, kind: str = "n8n") -> Relay:
    root = tmp_path / "relay"
    (root / "files").mkdir(parents=True)
    sha = hashlib.sha256(body).hexdigest()
    name = f"files/{sha[:16]}.xml"
    (root / name).write_bytes(body)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (root / "index.json").write_text(json.dumps({
        "schema": "enso-relay/1", "collected_at": now, "collector": {"kind": kind},
        "entries": [{"url": FEED_URL, "status": 200, "file": name, "sha256": sha, "fetched_at": now,
                     "content_type": "application/rss+xml", "detected": "rss"}]}), encoding="utf-8")
    return Relay(root)


def _fetcher(relay=None) -> Fetcher:
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False, relay=relay)
    f.client = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=IMUNIFY, headers={"content-type": "text/html; charset=utf8"})))
    return f


def test_imunify360_interstitial_is_a_challenge():
    assert reach.block_mark(IMUNIFY) == "imunify360"
    assert reach.classify(200, IMUNIFY, headers={"content-type": "text/html"}) == "challenge"
    assert block_page(IMUNIFY) == "imunify360"
    # Un feed o una página normal que nombre la frase en un artículo largo no es una verificación.
    assert block_page(RSS) == ""
    assert block_page(b"<html><body>" + b"x" * 50000 + b" one moment, please... </body></html>") == ""


def test_challenge_with_http_200_falls_back_to_collector_copy(tmp_path):
    f = _fetcher(_relay(tmp_path, RSS))
    r = f.get([FEED_URL], archive=False)
    assert r.channel == "relay-n8n" and r.body == RSS
    first = r.attempts[0]
    assert first["status"] == 200 and first["class"] == "challenge" and "imunify360" in first["error"]


def test_challenge_without_copy_fails_loudly_instead_of_passing_as_content():
    f = _fetcher()
    with pytest.raises(FetchError) as exc:
        f.get([FEED_URL], archive=False)
    last = exc.value.attempts[-1]
    assert last["class"] == "challenge" and "verificación antirobots (imunify360)" in last["error"]


def test_relay_never_serves_a_saved_challenge_page(tmp_path):
    assert _relay(tmp_path, IMUNIFY).get(FEED_URL) is None


def _hazard_run(tmp_path, monkeypatch, prev_ok: bool, relay=None, prev_at="2026-11-19T13:54:57+00:00", prev_extra=None):
    """Una corrida de noticias con un solo feed oficial de peligros (CIIFEN) que responde con la página de Imunify360."""
    from datetime import datetime, timezone

    from enso import news as N
    from enso import observatory as obs

    feed = N.FEED_BY_ID["ciifen"]
    monkeypatch.setattr(N, "FEEDS", [feed])
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(
        lambda req: httpx.Response(200, content=IMUNIFY, headers={"content-type": "text/html"}))}))
    site = tmp_path / "site"
    (site / "news").mkdir(parents=True)
    (site / "news" / "feeds.json").write_text(json.dumps({"feeds": [
        {"id": "ciifen", "ok": prev_ok, "error": "" if prev_ok else "x", "checkedAt": prev_at, **(prev_extra or {})}]}),
        encoding="utf-8")
    fetcher = Fetcher(polite_delay=0, relay=relay)
    log = obs.EventLog()
    now = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log, now, None)
    return {s["id"]: s for s in got["feeds"]["feeds"]}["ciifen"], log


def test_official_hazard_feed_down_twice_is_a_warning(tmp_path, monkeypatch):
    st, log = _hazard_run(tmp_path, monkeypatch, prev_ok=False)
    assert not st["ok"] and "imunify360" in st["error"]
    warn = [e for e in log.events if e.code == "hazard-feed-down"]
    assert len(warn) == 1 and warn[0].severity == "warning" and warn[0].source == "news-ciifen"


def test_hazard_feed_down_once_stays_info(tmp_path, monkeypatch):
    st, log = _hazard_run(tmp_path, monkeypatch, prev_ok=True)
    assert not st["ok"]
    assert not [e for e in log.events if e.code == "hazard-feed-down"]
    assert [e for e in log.events if e.code == "feed-down" and e.severity == "info"]


# --- Marcas genéricas (reCAPTCHA, «security check») en páginas normales ------------------------------------------

#: Una página de avisos de 9 KB con un formulario de suscripción con reCAPTCHA: con la marca «g-recaptcha» y menos de
#: ``SMALL_PAGE`` bytes, ``block_page`` la descartaba como verificación y ``Fetcher.get`` perdía la fuente.
NOTICE = ("<!DOCTYPE html><html lang='es'><head><title>Avisos meteorológicos</title>"
          "<script src='https://www.google.com/recaptcha/api.js' async defer></script></head><body>"
          "<h1>Avisos meteorológicos vigentes</h1>"
          + "".join(f"<article><h2>Aviso {n}: lluvias de moderada a fuerte intensidad en la sierra</h2>"
                    f"<p>Se prevén precipitaciones acompañadas de descargas eléctricas y ráfagas de viento en "
                    f"Cajamarca, Amazonas y San Martín entre el {n} y el {n + 2} de noviembre.</p></article>"
                    for n in range(1, 13))
          + "<form action='/suscribir' method='post'><input name='correo'><div class='g-recaptcha' "
            "data-sitekey='k'></div><button>Suscribirse</button></form>"
            "<p>Complete el security check del formulario para recibir los avisos por correo.</p></body></html>"
          ).encode()


def _serving(body: bytes, ct: str = "text/html; charset=utf-8") -> Fetcher:
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False)
    f.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=body,
                                                                                         headers={"content-type": ct})))
    return f


def test_small_page_with_a_recaptcha_form_is_content():
    assert len(NOTICE) < reach.SMALL_PAGE and reach.block_mark(NOTICE) == "human-verification"
    assert reach.classify(200, NOTICE, headers={"content-type": "text/html"}) == "challenge"  # n8n: sin cambio
    assert block_page(NOTICE) == ""
    r = _serving(NOTICE).get(["https://example.gob.pe/avisos"], archive=False, accept=("html",))
    assert r.channel == "direct" and r.body == NOTICE


def test_generic_mark_with_challenge_evidence_is_still_a_challenge():
    # Casi sin texto (hCaptcha, «Verify you are human»).
    bare = b"<html><head><title>Security check</title></head><body><div class='h-captcha'></div></body></html>"
    assert block_page(bare) == "human-verification"
    # Con texto, pero se recarga sola.
    reload_ = NOTICE.replace(b"</head>", b"<meta http-equiv='refresh' content='5'></head>")
    assert block_page(reload_) == "human-verification"
    js = NOTICE.replace(b"</body>", b"<script>setTimeout(function(){location.reload()},5000)</script></body>")
    assert block_page(js) == "human-verification"
    # HTML en lugar del PDF pedido.
    assert block_page(NOTICE, accept=("pdf", "octet-stream")) == "human-verification"
    with pytest.raises(FetchError) as exc:
        _serving(NOTICE).get(["https://example.gob.pe/x.pdf"], archive=False, accept=("pdf", "octet-stream"))
    assert exc.value.attempts[-1]["class"] == "challenge"
    # HTML en lugar del feed XML o del JSON pedido («xml» está en «application/xhtml+xml», pero no se pidió HTML).
    assert block_page(NOTICE, accept=("xml",)) == "human-verification"
    assert block_page(NOTICE, accept=("json",)) == "human-verification"
    assert block_page(NOTICE, accept=("html",)) == "" and block_page(NOTICE, accept=("text",)) == ""
    # Un script sin cerrar no cuenta como texto visible.
    unclosed = b"<html><body><p>Verify you are human</p><script>" + b"var token = compute(i);" * 200
    assert block_page(unclosed) == "human-verification"
    # Las verificaciones reales archivadas siguen siéndolo.
    assert block_page((FIX / "blocked" / "dhn-human-check-informe-20-2026.html").read_bytes()) == "human-verification"
    assert block_page(IMUNIFY) == "imunify360"


def test_own_family_marks_need_no_extra_evidence():
    """Una marca propia de un cortafuegos (Imunify360, Cloudflare) basta aunque la página tenga texto."""
    page = NOTICE.replace(b"<form ", b"<form id='wsidchk' ")
    assert reach.block_families(page) == ["human-verification", "captcha", "imunify360"]
    assert reach.block_mark(page) == "human-verification"  # la primera, como n8n
    assert block_page(page) == "imunify360"
    assert block_page(NOTICE, headers={"cf-mitigated": "challenge"}) == "cloudflare-challenge"


def test_relay_serves_a_copy_with_a_recaptcha_form(tmp_path):
    assert _relay(tmp_path, NOTICE).get(FEED_URL) is not None
