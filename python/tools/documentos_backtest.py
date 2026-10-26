"""Prueba hacia atrás de la lectura de los PDF del COEN (``enso.documentos``) sobre el histórico publicado.

    python -m tools.documentos_backtest --items items.jsonl --since 2026-09-01 --out /tmp/bt

Para cada publicación del COEN del histórico (reportes de emergencia y boletines de aviso) baja la página y el
PDF (con pausa de cortesía y una caché en ``--out/cache``) y compara los lugares leídos del PDF con:

* **Reportes**: el lugar que nombra su propio titular («Incendio forestal en el distrito de Talavera
  (Apurímac)»), que el COEN escribe a mano para cada reporte. Un departamento del PDF que el titular no nombra es
  un *falso positivo*; un distrito del titular que el PDF no da, un *falso negativo*. Los distritos de más (el
  titular nombra uno y la tabla del PDF varios) se listan aparte para revisarlos a mano.
* **Avisos**: la lista de departamentos del PDF se muestra junto al párrafo de donde sale, para revisarla a mano;
  y sirve de verdad para medir la aproximación por regiones (``senamhi_avisos.region_departments``).

También mide la ubicación por el texto (la de antes) contra la misma verdad. Escribe ``--out/report.md`` y
``--out/rows.jsonl`` (una fila por publicación, con el extracto del PDF que decide el lugar).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from enso import documentos as D
from enso.geo import gazetteer, key
from enso.news import FEED_BY_ID, read_jsonl
from enso.senamhi_avisos import region_departments

_WHERE_RE = re.compile(r"\ben (?:el|los) distritos? de (?P<d>.+?) \((?P<dep>[^)]+)\)|\ben (?:la|las) provincias? de (?P<p>.+?) "
                       r"\((?P<pdep>[^)]+)\)|\ben (?:el departamento de|la región) (?P<only>[A-ZÁÉÍÓÚÑ][\w ]+)", re.I)


def title_truth(title: str) -> dict:
    """Departamento y distritos (o provincias) que nombra el titular de un reporte del COEN."""
    gz = gazetteer()
    m = _WHERE_RE.search(title)
    if not m:
        return {}
    dep_name = m.group("dep") or m.group("pdep") or m.group("only")
    deps = gz.find(dep_name.strip(), "departamento")
    if len(deps) != 1:
        return {"unparsed": dep_name}
    dep = deps[0]
    names = m.group("d") or m.group("p") or ""
    level = "distrito" if m.group("d") else "provincia" if m.group("p") else ""
    parts = [x.strip() for x in re.split(r",\s*|\s+y\s+", names) if x.strip()]
    return {"dep": dep, "level": level, "names": parts}


def _fetcher(cache_dir: Path, delay: float):
    from enso.fetch import FetchError, Fetcher

    f = Fetcher(timeout=40.0, retries=1, polite_delay=delay)
    cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(url):
        p = cache_dir / hashlib.sha256(url.encode()).hexdigest()[:20]
        if p.exists():
            return 200, p.read_bytes(), "", ""
        try:
            r = f.get([url], archive=False)
        except FetchError as exc:
            last = exc.attempts[-1] if exc.attempts else {}
            return last.get("status"), b"", "", last.get("error") or "error"
        p.write_bytes(r.body)
        return 200, r.body, r.content_type, ""

    return fetch


def _names(codes: list[str]) -> list[str]:
    gz = gazetteer()
    return [gz.label(c)["name"] for c in codes if gz.valid(c)]


def _excerpt(text: str, doc: dict) -> str:
    if doc.get("basis", "").startswith("ubicación"):
        m = re.search(r"UBICACI[ÓO]N.{0,400}", text, re.S)
    else:
        m = re.search(r"DEPARTAMENTOS?[^:\n]{0,60}:.{0,400}|DEPARTAMENTOS\s+PROVINCIAS\s+EXPUESTAS.{0,300}|LITORAL.{0,200}",
                      text, re.S)
    return re.sub(r"\s+", " ", m.group(0))[:420] if m else ""


def extra_items(urls: list[str], fetch) -> list[dict]:
    """Publicaciones de otras páginas del feed del COEN, con el titular que les da el lector del sitio."""
    from enso.geo import locate_item
    from enso.hazardparse import parse_coen

    out = []
    for url in urls:
        code, body, *_ = fetch(url)
        if code != 200:
            print(f"{url}: {code}", file=sys.stderr)
            continue
        for e in parse_coen(body, url).items:
            g = locate_item({"title": e["title"], "summary": e["summary"]}, FEED_BY_ID["indeci-coen"])
            out.append({"feed": "indeci-coen", "link": e["link"], "title": e["title"], "summary": e["summary"],
                        "published": e["published"], "first_seen": e["published"] or "", "geo": g})
    return out


def run(items: list[dict], fetch, since: str) -> list[dict]:
    rows = []
    coen = [i for i in items if getattr(FEED_BY_ID.get(i.get("feed") or ""), "adapter", "") == "indeci-coen"
            and (i.get("published") or i["first_seen"]) >= since]
    seen = set()
    for n, it in enumerate(coen, 1):
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        row = {"link": it["link"], "title": it["title"], "bulletin": D.is_bulletin(it),
               "textGeo": [p["code"] for p in (it.get("geo") or {}).get("places") or []]}
        code, body, *_ = fetch(it["link"])
        if code != 200:
            row["status"] = f"página {code}"
            rows.append(row)
            continue
        pdf = D.pdf_link(body.decode("utf-8", errors="replace"), it["title"])
        if not pdf:
            row["status"] = "sin-pdf"
            rows.append(row)
            continue
        code, data, *_ = fetch(D.safe_url(pdf))
        if code != 200 or not data.startswith(b"%PDF"):
            row["status"] = f"pdf {code}"
            rows.append(row)
            continue
        try:
            text = D.pdf_text(data)
        except Exception as exc:  # noqa: BLE001
            row["status"] = f"pypdf {type(exc).__name__}"
            rows.append(row)
            continue
        doc = D.read(text, it["title"])
        row.update(status="ok", pdf=D.safe_url(pdf), codes=doc.get("codes") or [], basis=doc.get("basis", ""),
                   excerpt=_excerpt(text, doc))
        if not row["bulletin"]:
            row["truth"] = title_truth(it["title"])
        else:
            names, phrase = region_departments(f"{it['title']} {it.get('summary') or ''}")
            gz = gazetteer()
            row["regionGuess"] = [gz.find(x, "departamento")[0] for x in names]
            row["regionPhrase"] = phrase
        rows.append(row)
        print(f"{n}/{len(coen)} {row['status']} {it['title'][:70]}", file=sys.stderr)
    return rows


def judge(row: dict) -> dict:
    """Verdadero/falso positivo y negativo de un reporte, contra su titular."""
    t = row.get("truth") or {}
    if not t.get("dep"):
        return {"verdict": "sin-verdad"}
    gz = gazetteer()
    codes = row.get("codes") or []
    deps = {c[:2] for c in codes}
    out = {"fpDeps": sorted(deps - {t["dep"]}), "depFound": t["dep"] in deps}
    if t["level"]:
        n = 6 if t["level"] == "distrito" else 4
        want = [x for x in t["names"]]
        got = {key(gz.label(c)["name"]) for c in codes if len(c) == n and c.startswith(t["dep"])}
        out["missing"] = [x for x in want if key(x) not in got]
        out["extra"] = sorted(_names([c for c in codes if len(c) == n and key(gz.label(c)["name"]) not in {key(x) for x in want}]))
        # Más grueso de lo pedido: el departamento o la provincia, sin el distrito.
        out["coarse"] = bool(out["missing"]) and any(len(c) < n and c.startswith(t["dep"]) for c in codes)
    if not codes:
        out["verdict"] = "FN"
    elif out["fpDeps"]:
        out["verdict"] = "FP"
    elif out.get("missing"):
        out["verdict"] = "parcial"
    else:
        out["verdict"] = "TP"
    # La ubicación por el texto del titular, contra la misma verdad.
    tg = row.get("textGeo") or []
    n = 6 if t.get("level") == "distrito" else 4 if t.get("level") == "provincia" else 2
    tgot = {key(gz.label(c)["name"]) for c in tg if len(c) == n and gz.valid(c)} if n > 2 else {c[:2] for c in tg}
    out["textVerdict"] = ("FN" if not tg else "FP" if {c[:2] for c in tg} - {t["dep"]} else
                          "TP" if (n == 2 or all(key(x) in tgot for x in t["names"])) else "parcial")
    return out


def report(rows: list[dict]) -> str:
    rep = [r for r in rows if not r["bulletin"]]
    bul = [r for r in rows if r["bulletin"]]
    for r in rep:
        if r.get("status") == "ok":
            r["judge"] = judge(r)
    ok = [r for r in rep if r.get("status") == "ok" and r["judge"]["verdict"] != "sin-verdad"]
    count = lambda k, v: sum(1 for r in ok if r["judge"][k] == v)  # noqa: E731
    lines = ["# Lectura de los PDF del COEN: prueba hacia atrás", "",
             f"Publicaciones: {len(rows)} ({len(rep)} reportes, {len(bul)} boletines de aviso). "
             f"PDF leídos: {sum(1 for r in rows if r.get('status') == 'ok')}; sin PDF o sin respuesta: "
             f"{sum(1 for r in rows if r.get('status') != 'ok')}.", "",
             "## Reportes de emergencia (verdad: el lugar del titular)", "",
             "| | PDF | Texto del titular (antes) |", "|---|---|---|"]
    for v in ("TP", "parcial", "FN", "FP"):
        lines.append(f"| {v} | {count('verdict', v)} | {count('textVerdict', v)} |")
    lines += ["", f"Evaluados: {len(ok)}. «parcial»: el departamento correcto sin todos los distritos del titular.", ""]
    for label, cond in (("Falsos positivos", lambda r: r["judge"]["verdict"] == "FP"),
                        ("Falsos negativos y parciales", lambda r: r["judge"]["verdict"] in ("FN", "parcial")),
                        ("Distritos de más (revisar a mano)", lambda r: r["judge"].get("extra"))):
        sel = [r for r in ok if cond(r)]
        lines += [f"### {label} ({len(sel)})", ""]
        for r in sel:
            j = r["judge"]
            lines.append(f"- [{r['title']}]({r['link']}): PDF → {', '.join(_names(r['codes'])) or '—'}"
                         f"{'; departamentos de más: ' + ', '.join(_names(j['fpDeps'])) if j['fpDeps'] else ''}"
                         f"{'; faltan: ' + ', '.join(j.get('missing') or []) if j.get('missing') else ''}"
                         f"{'; de más: ' + ', '.join(j.get('extra') or []) if j.get('extra') else ''}. "
                         f"Extracto: «{r.get('excerpt', '')[:240]}»")
        lines.append("")
    lines += ["## Boletines de aviso (verdad: revisión a mano del extracto)", "",
              "| Boletín | Lugares del PDF | Extracto | Regiones del texto: aciertos / de más / faltan |", "|---|---|---|---|"]
    for r in bul:
        codes = set(r.get("codes") or [])
        deps = {c[:2] for c in codes}
        guess = set(r.get("regionGuess") or [])
        cmp = (f"{len(guess & deps)} / {', '.join(_names(sorted(guess - deps))) or '0'} / "
               f"{', '.join(_names(sorted(deps - guess))) or '0'}") if deps and guess else "—"
        lines.append(f"| [{r['title'][:80]}]({r['link']}) | {', '.join(_names(sorted(deps)))[:200] or r.get('status')} | "
                     f"{r.get('excerpt', '')[:200]} | {cmp} |")
    tp = sum(len(set(r.get("regionGuess") or []) & {c[:2] for c in r.get("codes") or []}) for r in bul)
    fp = sum(len(set(r.get("regionGuess") or []) - {c[:2] for c in r.get("codes") or []}) for r in bul if r.get("codes"))
    fn = sum(len({c[:2] for c in r.get("codes") or []} - set(r.get("regionGuess") or [])) for r in bul if r.get("regionGuess"))
    if tp:
        lines += ["", f"Aproximación por regiones contra los PDF: precisión {tp / (tp + fp):.0%}, exhaustividad "
                      f"{tp / (tp + fn):.0%} (departamentos)."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--items", required=True, help="news/items.jsonl (del sitio publicado)")
    ap.add_argument("--since", default="2026-09-01")
    ap.add_argument("--out", required=True)
    ap.add_argument("--feed", action="append", default=[],
                    help="feed del COEN más (p. ej. una página de su búsqueda, ?s=reporte&paged=7) cuyas publicaciones se suman")
    ap.add_argument("--delay", type=float, default=1.0, help="pausa de cortesía entre pedidos al mismo servidor (s)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    items = read_jsonl(Path(a.items).read_text(encoding="utf-8"))
    fetch = _fetcher(out / "cache", a.delay)
    items += extra_items(a.feed, fetch)
    rows = run(items, fetch, a.since)
    (out / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (out / "report.md").write_text(report(rows), encoding="utf-8")
    print(out / "report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
