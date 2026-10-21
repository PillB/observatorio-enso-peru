"""Sondeo de feeds candidatos: ¿responde?, ¿es un feed?, ¿está al día?, ¿sirve?

Lee ``tools/feed_candidates.json`` (medios regionales, radios, entidades del
Estado, búsquedas de Google Noticias por departamento) y para cada candidato:

1. Prueba sus URLs de feed en orden.
2. Si ninguna sirve, descarga la portada y busca ``<link rel="alternate"
   type="application/rss+xml">``; luego prueba rutas habituales
   (``/feed/``, ``/rss``, ``/arcio/rss/``, …).
3. Lee el feed con el lector tolerante (``enso.feedparse``) y anota el
   formato, las reparaciones, el número de entradas, la más reciente, cuántas
   son relevantes para El Niño o sus impactos, y dónde se ubican.

Escribe ``report.json`` y el cuerpo de cada feed que funciona en ``--out``.
Pensado para GitHub Actions (el contenedor de desarrollo no llega a los
medios peruanos).

Uso:
    python -m tools.probe_feeds --out tests/fixtures/news-probe
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enso import feedparse, geo, news  # noqa: E402

UA = ("Mozilla/5.0 (compatible; Observatorio-ENSO-Peru/4.0; feed-probe; "
      "+https://github.com/PillB/observatorio-enso-peru)")
CANDIDATES = Path(__file__).resolve().parent / "feed_candidates.json"
COMMON_PATHS = ["/feed/", "/rss", "/rss.xml", "/feed", "/feed.xml", "/arcio/rss/", "/index.xml",
                "/?feed=rss2", "/rss/", "/feeds/posts/default?alt=rss", "/noticias/feed/"]
#: Portales donde probar rutas habituales no tiene sentido (una sola plataforma para todo).
NO_GUESS = {"www.gob.pe", "gob.pe", "news.google.com"}
ALT_RE = re.compile(r"<link\b[^>]*>", re.I)
MAX_SAVE = 1_500_000


def discover(home_html: str, home_url: str) -> list[str]:
    out = []
    for tag in ALT_RE.findall(home_html):
        if re.search(r"rel=[\"']?alternate", tag, re.I) and re.search(r"(rss|atom)\+xml|feed\+json", tag, re.I):
            m = re.search(r"href=[\"']([^\"']+)", tag, re.I)
            if m:
                out.append(urljoin(home_url, m.group(1).replace("&amp;", "&")))
    return list(dict.fromkeys(out))


class Probe:
    def __init__(self, timeout: float = 25.0):
        self.client = httpx.Client(timeout=timeout, follow_redirects=True,
                                   headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, "
                                            "application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5",
                                            "Accept-Language": "es-PE,es;q=0.9,en;q=0.5"})
        self.locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self.last: dict[str, float] = {}

    def get(self, url: str) -> tuple[int | None, bytes, str, str, str]:
        host = urlparse(url).netloc
        with self.locks[host]:
            wait = 1.5 - (time.monotonic() - self.last.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.client.get(url)
                return r.status_code, r.content[: feedparse.MAX_FEED_BYTES + 1], r.headers.get("content-type", ""), str(r.url), ""
            except httpx.HTTPError as exc:
                return None, b"", "", url, f"{type(exc).__name__}: {exc}"[:200]
            finally:
                self.last[host] = time.monotonic()


def evaluate(cand: dict, body: bytes, url: str, now: datetime) -> dict:
    kind = cand.get("kind", "diario")
    scope = cand.get("scope") or ("local" if cand.get("dep") else "hazard" if kind in ("gobierno", "agregador") else "general")
    feed = news.Feed(cand["id"], cand["name"], "peru" if cand.get("department") != "mundo" else "mundo", url,
                     kind=kind, department=cand.get("dep"), scope=scope)
    p = feedparse.parse(body, base_url=url, default_tz=feedparse.LIMA, now=now)
    dates = sorted((i["published"] for i in p.items if i["published"]), reverse=True)
    rel, deps, samples = 0, defaultdict(int), []
    gz = geo.gazetteer()
    for i in p.items:
        why = news.relevance(feed, i["title"], i["summary"])
        tag = gz.tag([i["title"], i["summary"], " ".join(i.get("categories") or [])], True, feed.department)
        for d in (tag or {}).get("departments", []):
            deps[d] += 1
        if why:
            rel += 1
            if len(samples) < 5:
                samples.append({"title": i["title"], "published": i["published"], "link": i["link"],
                                "places": [x["name"] for x in (tag or {}).get("places", [])]})
    week = (now - timedelta(days=7)).isoformat()
    return {"format": p.format, "repairs": p.repairs, "items": len(p.items), "latest": dates[0] if dates else None,
            "undated": sum(1 for i in p.items if not i["published"]),
            "lastWeek": sum(1 for d in dates if d >= week), "relevant": rel, "departments": dict(deps),
            "samples": samples, "firstTitles": [i["title"] for i in p.items[:3]]}


def probe_one(pr: Probe, cand: dict, now: datetime, out: Path) -> dict:
    res = {"id": cand["id"], "name": cand["name"], "department": cand.get("department"), "kind": cand.get("kind"),
           "tried": [], "ok": False}
    tried: list[str] = []

    def attempt(url: str) -> bool:
        if url in tried:
            return False
        tried.append(url)
        code, body, ctype, final, err = pr.get(url)
        rec = {"url": url, "status": code, "type": ctype[:60], "final": final if final != url else None, "error": err}
        res["tried"].append(rec)
        if code != 200 or not body:
            return False
        try:
            ev = evaluate(cand, body, final, now)
        except feedparse.FeedError as exc:
            rec["error"] = str(exc)[:200]
            rec["head"] = re.sub(r"\s+", " ", body[:300].decode("utf-8", errors="replace"))
            return False
        if not ev["items"]:
            rec["error"] = "sin entradas"
            return False
        res.update(ev, ok=True, url=final)
        if len(body) <= MAX_SAVE:
            (out / f"{cand['id']}.xml").write_bytes(body)
        return True

    for u in cand.get("feeds", []):
        if attempt(u):
            return res
    home = cand.get("home")
    if home:
        code, body, ctype, final, err = pr.get(home)
        res["home"] = {"status": code, "final": final, "error": err}
        if code == 200 and body:
            text = body.decode("utf-8", errors="replace")
            for u in discover(text, final)[:4]:
                if attempt(u):
                    res["discovered"] = True
                    return res
            if cand.get("savehtml"):
                (out / f"{cand['id']}.html").write_bytes(body[:800_000])
        base = f"{urlparse(final or home).scheme}://{urlparse(final or home).netloc}"
        if urlparse(base).netloc in NO_GUESS or code != 200:
            return res
        for path in COMMON_PATHS:
            if attempt(base + path):
                res["guessedPath"] = path
                return res
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, default=CANDIDATES)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    for old in a.out.glob("*.xml"):
        old.unlink()
    cands = json.loads(a.candidates.read_text(encoding="utf-8"))
    if a.only:
        cands = [c for c in cands if c["id"] in a.only]
    now = datetime.now(timezone.utc)
    pr = Probe()
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda c: probe_one(pr, c, now, a.out), cands))
    report = {"checkedAt": now.isoformat(timespec="seconds"), "total": len(results),
              "ok": sum(r["ok"] for r in results), "results": results}
    (a.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for r in results:
        state = "OK " if r["ok"] else "-- "
        extra = (f"{r['format']} {r['items']} entradas, última {r['latest']}, relevantes {r['relevant']}, "
                 f"reparaciones {r['repairs']}") if r["ok"] else "; ".join(
            f"{t['status']} {t['error']}"[:60] for t in r["tried"][-2:])
        print(f"{state}{r['id']:28} {extra}")
    print(f"{report['ok']} de {report['total']} candidatos responden con un feed válido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
