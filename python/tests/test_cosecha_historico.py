"""Cosecha larga del catálogo histórico en GitHub Actions (``tools.cosecha_historico``) y lo que la hace posible en
``tools.build_historico``: descargas que se pueden cortar en cualquier momento y retomar, y la copia del IDMC en HDX
cuando falta la clave de su API."""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from tools import build_historico as B, cosecha_historico as H


def _manifest(*sources):
    return {"fuentes": [{"archivo": f"{s['id']}.json", "url": f"https://{s.pop('host', 'a.pe')}/x", **s} for s in sources]}


def _mock(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(B.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler),
                                                             **{k: v for k, v in kw.items() if k != "verify"}))


def test_groups_by_server_with_long_harvests_first():
    m = _manifest({"id": "a1", "host": "a.pe"}, {"id": "b1", "host": "b.pe", "descarga": "indeci-coen"},
                  {"id": "a2", "host": "a.pe", "descarga": "rpp"}, {"id": "c1", "host": "c.pe"},
                  {"id": "m", "host": "m.pe", "descarga": "manual"})
    m["fuentes"].append({"id": "curado", "lector": "curado", "url": "https://github.com/x"})
    gs = H.groups(H.harvestable(m))
    assert [[s["id"] for s in g] for g in gs] == [["a2", "a1"], ["b1"], ["c1"]]


def _script(code: str):
    """Un proceso hijo de prueba en lugar de ``--una``: ``code`` recibe la fuente y la caché."""
    return lambda src, cache: [sys.executable, "-c", f"import sys, pathlib, time; src, cache = {src['id']!r}, "
                                                     f"pathlib.Path({str(cache)!r}); {code}"]


def test_a_run_downloads_until_the_deadline_and_counts_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(H, "MIN_LEFT", 0)
    m = _manifest({"id": "lista"}, {"id": "lenta", "host": "b.pe"}, {"id": "rota", "host": "c.pe"})
    code = ("print('bajando', src, flush=True)\n"
            "if src == 'lista': (cache / 'lista.json').write_text('{}')\n"
            "elif src == 'lenta': (cache / 'lenta-partes').mkdir(exist_ok=True); time.sleep(60)\n"
            "else: sys.exit('rota: el servidor respondió HTTP 403')")
    for run in range(1, 4):
        st = H.harvest(m, tmp_path, minutes=2 / 60, command=_script(code))
        assert st["resultado"]["lenta"] == ("sigue", "venció el plazo de la corrida")
        assert st["resultado"]["rota"][0] == "falló" and "HTTP 403" in st["resultado"]["rota"][1]
        assert st["fuentes"]["rota"]["fallos"] == run and st["fuentes"]["lenta"]["fallos"] == 0
        assert st["corridas"] == run
    # «lista» ya no se pide; «rota» dejó de esperarse tras tres fallos seguidos, «lenta» sigue.
    assert "lista" not in st["resultado"] and st["fuentes"]["lista"]["avance"] == "completa"
    assert (st["estado"], st["faltan"], st["sin_esperar"]) == ("sigue", ["lenta"], ["rota"])
    assert st["fuentes"]["lenta"]["avance"] == "0 partes"
    md = H.table(st, m)
    assert "| rota | falló |" in md and "HTTP 403" in md and "| lista |" not in md

    (tmp_path / "lenta.json").write_text("{}")
    st = H.harvest(m, tmp_path, minutes=1, command=_script("sys.exit('rota: sigue rota')"))
    assert st["estado"] == "completa" and st["inicio"] == H.load_state(tmp_path)["inicio"]

    # Con el PR anotado no se baja nada.
    H.main(["--cache", str(tmp_path), "--pr", "https://github.com/x/y/pull/1"])
    assert H.harvest(m, tmp_path, minutes=1, command=_script("raise SystemExit('no debía correr')"))["estado"] == "hecha"


def test_progress_reads_the_parts_of_each_long_harvest(tmp_path):
    coen = {"id": "coen", "archivo": "coen.json", "descarga": "indeci-coen"}
    assert H.progress(coen, tmp_path) == "sin empezar"
    (tmp_path / "coen-partes" / "textos").mkdir(parents=True)
    (tmp_path / "coen-partes" / "lista.json").write_text('{"pagina": 12, "paginas": 1926}')
    (tmp_path / "coen-partes" / "textos" / "a.txt.gz").write_bytes(b"")
    assert H.progress(coen, tmp_path) == "listado: página 12 de 1926; 1 PDF leídos"
    wp = {"id": "wp", "archivo": "wp.json", "descarga": "wp-rest", "parametros": {"terminos": ["huaico", "helada"]}}
    (tmp_path / "wp-partes").mkdir()
    (tmp_path / "wp-partes" / B._wp_part("helada")).write_text("{}")
    assert H.progress(wp, tmp_path) == "1 de 2 términos"


def test_fetch_writes_the_file_before_deleting_the_parts(monkeypatch, tmp_path):
    src = {"id": "s", "archivo": "s.json", "descarga": "rpp", "url": "https://rpp.pe/archivo"}
    monkeypatch.setattr(B, "robots_check", lambda url: 0.0)
    parts = tmp_path / "s-partes"
    parts.mkdir()
    (parts / "2021-01-01.json").write_text("[]")

    def cut(src, parts, delay):
        raise SystemExit("cortado")

    monkeypatch.setattr(B, "rpp_archivo", cut)
    with pytest.raises(SystemExit):
        B.fetch(src, [tmp_path], accept_changes=True, offline=False)
    assert (parts / "2021-01-01.json").exists() and not (tmp_path / "s.json").exists()

    monkeypatch.setattr(B, "rpp_archivo", lambda src, parts, delay: b'{"notas": []}')
    B.fetch(src, [tmp_path], accept_changes=True, offline=False)
    assert (tmp_path / "s.json").read_bytes() == b'{"notas": []}' and not parts.exists()
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]  # sin temporales


def test_wp_rest_resumes_with_the_next_term(monkeypatch, tmp_path):
    asked = []

    def handler(request):
        term = request.url.params["search"]
        asked.append(term)
        posts = {"huaico": [{"id": 2, "date": "2023-03-10T08:00:00", "link": "https://x.pe/2",
                             "title": {"rendered": "Huaico en Chosica"}, "excerpt": {"rendered": "<p>Un huaico</p>"}}],
                 "helada": [{"id": 2, "date": "2023-03-10T08:00:00", "link": "https://x.pe/2",
                             "title": {"rendered": "Huaico en Chosica"}, "excerpt": {"rendered": "<p>Un huaico</p>"}},
                            {"id": 1, "date": "2022-07-01T08:00:00", "link": "https://x.pe/1",
                             "title": {"rendered": "Helada en Puno"}, "excerpt": {"rendered": ""}}]}[term]
        return httpx.Response(200, json=posts, headers={"X-WP-TotalPages": "1"})

    _mock(monkeypatch, handler)
    src = {"id": "wp", "url": "https://x.pe/wp-json/wp/v2/posts", "parametros": {"terminos": ["huaico", "helada"]}}
    full = json.loads(B.wp_rest(src, tmp_path / "p", delay=0))
    assert [(n["id"], n["terminos"]) for n in full["notas"]] == [(1, ["helada"]), (2, ["huaico", "helada"])]
    assert asked == ["huaico", "helada"]

    # Cortada tras el primer término: la siguiente pide solo el segundo y el resultado es el mismo.
    (tmp_path / "p" / B._wp_part("helada")).unlink()
    asked.clear()
    assert json.loads(B.wp_rest(src, tmp_path / "p", delay=0)) == full and asked == ["helada"]
    assert json.loads(B.ASSEMBLE["wp-rest"](src, tmp_path / "p")) == full


def test_idmc_without_key_uses_the_seed_in_the_repository(monkeypatch, tmp_path):
    def handler(request):
        raise AssertionError(f"no debía pedir {request.url}")

    _mock(monkeypatch, handler)
    monkeypatch.delenv("IDMC_CLIENT_ID", raising=False)
    m = {s["id"]: s for s in json.loads(B.MANIFEST.read_text(encoding="utf-8"))["fuentes"]}
    for sid in ("idmc-idu", "idmc-eventos"):
        src = {k: v for k, v in m[sid].items() if k != "copia"}
        path = B.fetch(src, [tmp_path], accept_changes=False, offline=False)  # con el SHA-256 del manifiesto
        assert src["copia"] == "semilla" and path.name == m[sid]["archivo"]
        # Sin red, la copia sigue anotada.
        again = {k: v for k, v in src.items() if k != "copia"}
        B.fetch(again, [tmp_path], accept_changes=False, offline=True)
        assert again["copia"] == "semilla"


def test_report_lists_changes_and_what_could_not_be_downloaded(monkeypatch, tmp_path):
    before = tmp_path / "antes"
    before.mkdir()
    old = {"fuentes": [{"id": "a", "registros": 10, "corroboran": 2, "parcial": True}, {"id": "b", "registros": 5}]}
    (before / "fuentes.json").write_text(json.dumps(old))
    (before / "resumen.json").write_text('{"registros": 100}')
    out = tmp_path / "out"
    out.mkdir()
    (out / "resumen.json").write_text('{"registros": 130}')
    new = tmp_path / "fuentes.json"
    new.write_text(json.dumps({"fuentes": [{"id": "a", "registros": 40, "corroboran": 9}, {"id": "b", "registros": 5},
                                           {"id": "c", "parcial": "pendiente"}]}))
    monkeypatch.setattr(B, "MANIFEST", new)
    monkeypatch.setattr(B, "OUT", out)
    state = {"inicio": "2026-10-28", "corridas": 7, "sin_esperar": ["c"],
             "fuentes": {"c": {"error": "c: el robots.txt del servidor no permite pedirlo a un programa"}}}
    md = H.report(before, state)
    assert "**Registros:** 100 → 130." in md and "| a | 40 | 9 | 10 / 2 (a medias) |" in md
    assert "| b |" not in md and "`c`: c: el robots.txt" in md and "**A medias o pendientes:** `c`" in md
