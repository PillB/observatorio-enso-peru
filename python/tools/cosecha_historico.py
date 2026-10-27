"""Cosecha larga del catálogo histórico en GitHub Actions (``.github/workflows/memoria-cosecha.yml``).

Varias fuentes de ``data/historico/fuentes.json`` toman días a la pausa de cortesía (los reportes del COEN, los
decretos de El Peruano, las fichas del INGEMMET, el archivo de RPP): no caben en una corrida de Actions (6 h) ni en un
contenedor que se reinicia. Esta herramienta baja en cada corrida lo que falte hasta un plazo y se detiene; lo bajado
queda en la caché (``actions/cache``) y la corrida siguiente sigue donde quedó.

* Cada fuente se baja en un proceso propio (``--una``) con ``build_historico.fetch``. Al vencer el plazo se corta, y
  como cada parte y el archivo final se escriben de una vez (``build_historico.write_atomic``), lo bajado sirve.
* Las fuentes de un mismo servidor van una tras otra (la pausa entre pedidos es de cada fuente: en paralelo se
  sumarían); los servidores van en paralelo, primero los de las cosechas largas.
* ``cosecha-estado.json``, en la caché, lleva la fecha en que empezó la cosecha y, de cada fuente, los intentos, los
  fallos seguidos y el último error. Una fuente que falla en ``--fallos`` corridas seguidas (no por el plazo) deja de
  esperarse: el catálogo se construye sin ella y el PR lo dice. Se sigue intentando en las corridas siguientes.
* Cuando no falta nada, escribe ``estado=completa`` en ``$GITHUB_OUTPUT``: el flujo construye el catálogo sin red y
  abre el PR. Con el PR ya anotado (``--pr``, en ``cosecha-pr.json``) no baja nada: ``estado=hecha``.

Uso:
    python -m tools.cosecha_historico --cache ~/.cache/enso-historico --minutos 320
    python -m tools.cosecha_historico --cache DIR --solo coen-reportes,prensa-rpp
    python -m tools.cosecha_historico --cache DIR --informe ANTES   # cuerpo del PR (ANTES: fuentes.json y resumen.json previos)
    python -m tools.cosecha_historico --cache DIR --pr URL          # anota el PR abierto
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import build_historico as B  # noqa: E402

STATE = "cosecha-estado.json"
PR = "cosecha-pr.json"
#: Descargas largas y reanudables: sus servidores empiezan primero, para que tengan todo el plazo.
LONG = ("indeci-coen", "elperuano", "dspace", "rpp", "sinpad-api", "loc-chronam", "sitemaps", "wp-rest")
#: Fallos seguidos (no por el plazo) tras los que una fuente deja de esperarse.
FAILS = 3
#: Segundos de plazo por debajo de los que una fuente ya no empieza.
MIN_LEFT = 30


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def harvestable(manifest: dict) -> list[dict]:
    """Las fuentes que se descargan con un programa (no las curadas ni las que se bajan a mano)."""
    return [s for s in manifest["fuentes"] if s.get("archivo") and s.get("descarga") != "manual"]


def host(src: dict) -> str:
    return urlsplit(src.get("url_robots") or src["url"]).netloc


def groups(sources: list[dict]) -> list[list[dict]]:
    """Las fuentes agrupadas por servidor, primero los grupos con una descarga larga (en el orden del manifiesto)."""
    by: dict[str, list[dict]] = defaultdict(list)
    for s in sources:
        by[host(s)].append(s)
    out = [sorted(g, key=lambda s: s.get("descarga") not in LONG) for g in by.values()]
    return sorted(out, key=lambda g: g[0].get("descarga") not in LONG)


def load_state(cache: Path) -> dict:
    f = cache / STATE
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"inicio": today(), "corridas": 0, "fuentes": {}}


def save_state(cache: Path, state: dict) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    B.write_atomic(cache / STATE, json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def _count(d: Path, pattern: str = "*") -> int:
    return sum(1 for _ in d.glob(pattern)) if d.is_dir() else 0


def progress(src: dict, cache: Path) -> str:
    """Cuánto lleva bajado una fuente, en palabras."""
    path = cache / src["archivo"]
    if path.exists():
        return "completa"
    parts = cache / f"{path.stem}-partes"
    if not parts.is_dir():
        return "sin empezar"
    kind = src.get("descarga")
    month = "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"
    if kind == "indeci-coen":
        st = json.loads((parts / "lista.json").read_text(encoding="utf-8")) if (parts / "lista.json").exists() else {}
        return (f"listado: página {st.get('pagina', 0)} de {st.get('paginas') or '?'}; "
                f"{_count(parts / 'textos', '*.txt.gz')} PDF leídos")
    if kind == "elperuano":
        return f"{_count(parts, month)} meses buscados; {_count(parts / 'textos', '*.txt.gz')} decretos leídos"
    if kind == "sinpad-api":
        return f"{_count(parts, month)} meses"
    if kind == "rpp":
        days = sorted(parts.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json"))
        return f"{len(days)} días, hasta {days[-1].stem}" if days else "sin días"
    if kind == "dspace":
        lst = parts / "lista.json"
        total = len(json.loads(lst.read_text(encoding="utf-8"))) if lst.exists() else "?"
        return f"{sum(1 for f in parts.glob('*.json') if f.stem.isdigit())} de {total} fichas"
    if kind == "wp-rest":
        terms = src.get("parametros", {}).get("terminos", B.NEWS_TERMS)
        return f"{sum((parts / B._wp_part(t)).exists() for t in terms)} de {len(terms)} términos"
    if kind == "loc-chronam":
        queries = src.get("parametros", {}).get("consultas", [])
        return (f"{sum((parts / B._loc_part(q)).exists() for q in queries)} de {len(queries)} consultas; "
                f"{_count(parts / 'fragmentos')} fragmentos leídos")
    return f"{_count(parts)} partes"


def child_command(src: dict, cache: Path) -> list[str]:
    return [sys.executable, "-m", "tools.cosecha_historico", "--una", src["id"], "--cache", str(cache)]


def run(src: dict, cache: Path, deadline: float, log: Callable[[str], None],
        command: Callable[[dict, Path], list[str]] = child_command) -> tuple[str, str]:
    """Baja una fuente en un proceso propio hasta ``deadline`` (``time.monotonic``). Devuelve (resultado, detalle):
    «completa», «sigue» (venció el plazo; lo bajado queda en las partes), «falló» (con las últimas líneas) o «sin
    tiempo» (no llegó a empezar)."""
    left = deadline - time.monotonic()
    if left < MIN_LEFT:
        return "sin tiempo", ""
    p = subprocess.Popen(command(src, cache), cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True,
                         env={**os.environ, "PYTHONUNBUFFERED": "1"})
    killed = threading.Event()

    def stop():
        killed.set()
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except ProcessLookupError:
                return
            try:
                p.wait(10)
                return
            except subprocess.TimeoutExpired:
                continue

    timer = threading.Timer(left, stop)
    timer.start()
    tail: deque[str] = deque(maxlen=5)
    try:
        for line in p.stdout:
            line = line.rstrip()
            if line:
                tail.append(line)
                log(f"[{src['id']}] {line}")
        p.wait()
    finally:
        timer.cancel()
    if killed.is_set():
        return "sigue", "venció el plazo de la corrida"
    if p.returncode == 0:
        return "completa", ""
    return "falló", " | ".join(tail)[-500:] or f"código {p.returncode}"


def harvest(manifest: dict, cache: Path, minutes: float, only: Optional[set] = None, workers: int = 32,
            command: Callable[[dict, Path], list[str]] = child_command, fails: int = FAILS) -> dict:
    """Una corrida: baja en paralelo por servidor lo que falte hasta el plazo y actualiza ``cosecha-estado.json``.
    Devuelve el estado, con ``resultado`` (de esta corrida) y ``estado`` (completa, sigue o hecha)."""
    cache.mkdir(parents=True, exist_ok=True)
    state = load_state(cache)
    if (cache / PR).exists():
        state["estado"] = "hecha"
        state["pr"] = json.loads((cache / PR).read_text(encoding="utf-8"))
        return state
    sources = harvestable(manifest)
    todo = [s for s in sources if not (cache / s["archivo"]).exists() and (not only or s["id"] in only)]
    deadline = time.monotonic() + minutes * 60
    lock = threading.Lock()
    results: dict[str, tuple[str, str]] = {}

    def log(line: str) -> None:
        with lock:
            print(line, flush=True)

    def work(group: list[dict]) -> None:
        for s in group:
            results[s["id"]] = run(s, cache, deadline, log, command)
            log(f"[{s['id']}] {results[s['id']][0]} {results[s['id']][1]}".rstrip())

    gs = groups(todo)
    if gs:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(gs)))) as ex:
            list(ex.map(work, gs))
    state["corridas"] = state.get("corridas", 0) + 1
    state["ultima"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for s in sources:
        st = state["fuentes"].setdefault(s["id"], {"intentos": 0, "fallos": 0})
        got, detail = results.get(s["id"], (None, ""))
        if got in ("completa", "sigue", "falló"):
            st["intentos"] += 1
        if got == "falló":
            st["fallos"] += 1
            st["error"] = detail
        elif got in ("completa", "sigue"):
            st["fallos"] = 0
            st.pop("error", None)
        if (cache / s["archivo"]).exists():
            st.setdefault("completa", today())
            st["fallos"] = 0
            st.pop("error", None)
        st["avance"] = progress(s, cache)
    missing = [s["id"] for s in sources if not (cache / s["archivo"]).exists()
               and state["fuentes"][s["id"]]["fallos"] < fails]
    state["faltan"] = missing
    state["sin_esperar"] = [s["id"] for s in sources if not (cache / s["archivo"]).exists() and s["id"] not in missing]
    save_state(cache, state)
    state["resultado"] = results
    state["estado"] = "sigue" if missing else "completa"
    return state


def table(state: dict, manifest: dict) -> str:
    """Resumen de la corrida en Markdown (para ``$GITHUB_STEP_SUMMARY`` y el registro)."""
    res = state.get("resultado", {})
    lines = [f"### Cosecha del catálogo histórico ({state['estado']})", "",
             f"Empezó el {state['inicio']}; corrida {state.get('corridas', 0)}. "
             f"Faltan {len(state.get('faltan', []))} fuentes; {len(state.get('sin_esperar', []))} dejaron de esperarse "
             f"tras {FAILS} fallos seguidos.", "", "| Fuente | Esta corrida | Avance | Último error |", "|---|---|---|---|"]
    for s in harvestable(manifest):
        st = state["fuentes"].get(s["id"], {})
        if st.get("completa") and s["id"] not in res:
            continue
        err = (st.get("error") or "").replace("|", "/")[:160]
        lines.append(f"| {s['id']} | {res.get(s['id'], ('—',))[0]} | {st.get('avance', '')} | {err} |")
    done = sum(1 for s in harvestable(manifest) if state["fuentes"].get(s["id"], {}).get("completa"))
    lines += ["", f"{done} fuentes completas no se listan."]
    return "\n".join(lines) + "\n"


def report(before: Path, state: dict) -> str:
    """Cuerpo del PR: qué cambió en cada fuente y en el total respecto de lo publicado (``before``: ``fuentes.json``
    y ``resumen.json`` previos), y qué falta."""
    old = {s["id"]: s for s in json.loads((before / "fuentes.json").read_text(encoding="utf-8"))["fuentes"]}
    new = json.loads(B.MANIFEST.read_text(encoding="utf-8"))
    total = lambda d: json.loads((d / "resumen.json").read_text(encoding="utf-8"))["registros"]  # noqa: E731
    now = total(B.OUT)
    prev = total(before) if (before / "resumen.json").exists() else None
    lines = ["El catálogo histórico de la pestaña «Memoria de desastres», reconstruido sin red con la cosecha completa "
             f"que empezó el {state['inicio']} ({state.get('corridas', 0)} corridas de "
             "`.github/workflows/memoria-cosecha.yml`).", "",
             f"**Registros:** {prev if prev is not None else '?'} → {now}.", "",
             "| Fuente | Registros | Corroboran | Antes |", "|---|---|---|---|"]
    for s in new["fuentes"]:
        o = old.get(s["id"], {})
        keys = ("registros", "corroboran", "parcial")
        if all(o.get(k) == s.get(k) for k in keys):
            continue
        was = f"{o.get('registros', '—')} / {o.get('corroboran', '—')}" + (" (a medias)" if o.get("parcial") else "")
        lines.append(f"| {s['id']} | {s.get('registros', '—')} | {s.get('corroboran', '—')} | {was} |")
    skipped = state.get("sin_esperar", [])
    if skipped:
        lines += ["", "**No se pudieron bajar** (fallaron en varias corridas seguidas; el catálogo sigue sin ellas):", ""]
        lines += [f"* `{i}`: {state['fuentes'].get(i, {}).get('error', '')[:300]}" for i in skipped]
    partial = [s["id"] for s in new["fuentes"] if s.get("parcial")]
    if partial:
        lines += ["", "**A medias o pendientes:** " + ", ".join(f"`{i}`" for i in partial)]
    lines += ["", "Las pruebas corren en este PR con `ci.yml` (lanzado por el flujo: un PR abierto por GitHub Actions no "
              "lanza flujos solo). Para reconstruir con lo bajado: correr el flujo con «reconstruir»; para una cosecha "
              "nueva desde cero: con «renovar»."]
    return "\n".join(lines) + "\n"


def output(**kw) -> None:
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            for k, v in kw.items():
                f.write(f"{k}={v}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, default=B.CACHE)
    ap.add_argument("--minutos", type=float, default=320, help="plazo de la corrida (por omisión 320)")
    ap.add_argument("--solo", default="", help="ids separados por comas (vacío: todas las que falten)")
    ap.add_argument("--hilos", type=int, default=32, help="servidores a la vez")
    ap.add_argument("--fallos", type=int, default=FAILS)
    ap.add_argument("--una", help=argparse.SUPPRESS)  # proceso hijo: baja una fuente
    ap.add_argument("--informe", type=Path, help="carpeta con fuentes.json y resumen.json previos: escribe el cuerpo del PR")
    ap.add_argument("--pr", help="anota el PR abierto con la cosecha completa")
    a = ap.parse_args(argv)
    manifest = json.loads(B.MANIFEST.read_text(encoding="utf-8"))
    if a.una:
        src = next(s for s in manifest["fuentes"] if s["id"] == a.una)
        B.fetch(src, [a.cache], accept_changes=True, offline=False)
        return 0
    if a.informe:
        sys.stdout.write(report(a.informe, load_state(a.cache)))
        return 0
    if a.pr:
        B.write_atomic(a.cache / PR, json.dumps({"url": a.pr, "fecha": today()}) + "\n")
        return 0
    only = {x.strip() for x in a.solo.split(",") if x.strip()} or None
    state = harvest(manifest, a.cache, a.minutos, only, a.hilos, fails=a.fallos)
    if state["estado"] == "hecha":
        print(f"La cosecha que empezó el {state['inicio']} ya terminó y su PR está abierto o se cerró "
              f"({state['pr']['url']}). Para una nueva, correr el flujo con «renovar».")
    else:
        md = table(state, manifest)
        print(md)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(md)
    output(estado=state["estado"], inicio=state["inicio"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
