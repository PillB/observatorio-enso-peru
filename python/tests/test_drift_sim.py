"""Simulador de deriva (``tools/drift_sim.py``): ninguna fuente ni feed publica otra cosa sin aviso ante los cambios
que una fuente puede hacer sin anunciarlos.

La verdad de cada caso no se escribe a mano: es la lectura de la copia real sin mutar, por el mismo camino de la
corrida diaria (``observatory.acquire`` con la guardia de regresión y la huella; ``news._read_feed`` con
``persistent.feed_state``). Las pruebas de abajo comprueban además que el simulador detecta lo que dice detectar: con
una guardia apagada, la prueba principal falla (``test_*_guard_is_what_keeps_*``).
"""

from __future__ import annotations

import json
import math

import pytest
from hypothesis import given, settings, strategies as st

from enso import hazardparse as H
from enso import news as N
from enso import observatory as O
from enso.feeds import cpc
from tools import drift_sim as D


@pytest.fixture(scope="module")
def targets(tmp_path_factory):
    return D.build_targets(work=tmp_path_factory.mktemp("drift-sim"))


@pytest.fixture(scope="module")
def results(targets):
    return D.simulate(targets)


def _silent(results):
    return [r for r in results if r.verdict == D.SILENT and not D.allowed(r)]


def test_no_mutation_is_silent_wrong(results):
    bad = _silent(results)
    assert not bad, "publican otra cosa sin aviso:\n" + "\n".join(
        f"{r.target} · {r.mutation}: {r.detail}" for r in bad)


def test_every_source_and_every_reader_family_is_simulated(targets, results):
    # Sin esto, la prueba de arriba pasaría con una lista vacía o con una fuente que dejó de leerse.
    ids = {t.id for t in targets}
    assert {s.id for s in O.SOURCES} <= ids
    adapters = {N.FEED_BY_ID[t.id].adapter for t in targets if t.kind == "feed"}
    assert adapters == {f.adapter for f in N.FEEDS if (D.FIXTURES / f.fixture).exists()}
    ran = [r for r in results if r.verdict != D.NA]
    assert len(ran) > 600
    # Cada objetivo pasó por mutaciones de verdad (no solo N/A); GODAS solo por las de transporte (su cuerpo es el
    # resumen que arma la corrida con los GRIB), los demás por al menos diez.
    per = {t.id: sum(1 for r in ran if r.target == t.id) for t in targets}
    assert per.pop("cpc-godas-d20") >= 6 and min(per.values()) >= 10, per
    assert {r.verdict for r in ran} >= {D.LOUD, D.BENIGN}


def test_allowlist_entries_are_justified_and_still_needed(results):
    # Una entrada revisada que ya no hace falta se quita: si no, tapa el día en que vuelva a fallar otra cosa.
    used = set()
    for r in results:
        if r.verdict == D.SILENT and D.allowed(r):
            used |= {k for k in D.ALLOWLIST if k[1] == r.mutation and k[0] in (r.target, f"adapter:{r.group}", "*")}
    assert used == set(D.ALLOWLIST), f"entradas sin uso: {set(D.ALLOWLIST) - used}"
    assert all(len(why) > 120 for why in D.ALLOWLIST.values())


# --- El simulador mismo: que sus mutaciones hagan lo que dicen ---------------------------------------------------------
def test_table_mutations_change_values_as_described():
    # Contra números escritos a mano, no contra el propio simulador.
    body = b"YR MON  NINO1+2   ANOM\n2026   1   24.28   -0.24\n2026   2   25.38   -99.99\n" * 1
    ctx = {"family": "table"}
    assert D.MUTATIONS["scale-x10"].apply(body, ctx).split(b"\n")[1].split() == [b"2026", b"1", b"242.80", b"-2.40"]
    assert D.MUTATIONS["unit-F-anom"].apply(body, ctx).split(b"\n")[1].split()[-1] == b"-0.43"
    # El centinela no se escala ni se convierte: es un dato faltante.
    assert D.MUTATIONS["scale-x10"].apply(body, ctx).split(b"\n")[2].split()[-1] == b"-99.99"
    assert D.MUTATIONS["sentinel-999"].apply(body, ctx).split(b"\n")[2].split()[-1] == b"-999"
    assert D.MUTATIONS["decimal-comma"].apply(body, ctx).split(b"\n")[1].split()[-1] == b"-0,24"


def test_date_mutations_keep_the_instant():
    body = b"<rss><channel><item><title>t</title><link>https://x.pe/1</link>" \
           b"<pubDate>Fri, 20 Nov 2026 10:00:00 -0500</pubDate></item></channel></rss>"
    ctx = {"family": "xml", "region": "peru"}
    assert b"vie, 20 nov 2026 10:00:00 -0500" in D.MUTATIONS["date-es"].apply(body, ctx)
    assert b"2026-11-20T15:00:00Z" in D.MUTATIONS["date-utc"].apply(body, ctx)
    assert b">1795186800<" in D.MUTATIONS["date-epoch"].apply(body, ctx)
    assert b"2026-11-20 10:00:00<" in D.MUTATIONS["date-naive"].apply(body, ctx)  # hora local de Lima


def test_classify_is_not_identity():
    base = D.Outcome((), '{"a": 1}')
    assert D.classify(base, D.Outcome((), '{"a": 1}'), False)[0] == D.BENIGN
    assert D.classify(base, D.Outcome((), '{"a": 2}'), False)[0] == D.SILENT
    assert D.classify(base, D.Outcome(("warning:x",), '{"a": 2}'), False)[0] == D.LOUD
    assert D.classify(base, D.Outcome(("warning:x",), '{"a": 1}'), True)[0] == D.NOISY
    # Un aviso que ya daba la copia sin mutar no cuenta como aviso de la mutación.
    assert D.classify(D.Outcome(("warning:x",), "1"), D.Outcome(("warning:x",), "2"), False)[0] == D.SILENT


# --- No tautológica: con una guardia apagada, el simulador lo ve ---------------------------------------------------------
def _sim(monkeypatch, targets, ids, mutations):
    return D.simulate([t for t in targets if t.id in ids], mutations)


def test_drift_guard_is_what_keeps_column_swaps_loud(targets, monkeypatch):
    # El intercambio de columnas de la matriz del SOI pasa la validación de rangos: solo lo ve ``enso.drift``.
    on = _sim(monkeypatch, targets, {"cpc-soi"}, ["col-swap"])
    assert [r.verdict for r in on] == [D.LOUD] and "warning:history-rewritten" in on[0].signals
    monkeypatch.setattr(O.drift, "compare", lambda *a, **k: [])
    off = _sim(monkeypatch, targets, {"cpc-soi"}, ["col-swap"])
    assert [r.verdict for r in off] == [D.SILENT]


def test_empty_feed_state_is_what_keeps_empty_feeds_loud(targets, monkeypatch):
    feed = next(t.id for t in targets if t.kind == "feed" and N.FEED_BY_ID[t.id].adapter == "feed")
    on = _sim(monkeypatch, targets, {feed}, ["items-none"])
    assert [r.verdict for r in on] == [D.LOUD] and on[0].signals == ("degraded:empty",)
    real = D.P.feed_state
    monkeypatch.setattr(D.P, "feed_state", lambda st, *a, **k: (None, None) if not st.get("items") else real(st, *a, **k))
    assert [r.verdict for r in _sim(monkeypatch, targets, {feed}, ["items-none"])] == [D.SILENT]


def test_coordinate_guard_is_what_keeps_swapped_epicentres_loud(targets, monkeypatch):
    assert [r.verdict for r in _sim(monkeypatch, targets, {"usgs-sismos"}, ["json-coords-swap"])] == [D.LOUD]
    monkeypatch.setattr(H, "_query_box", lambda url: None)
    assert [r.verdict for r in _sim(monkeypatch, targets, {"usgs-sismos"}, ["json-coords-swap"])] == [D.SILENT]


# --- Relaciones metamórficas -------------------------------------------------------------------------------------------
PSL_TEXT = (D.FIXTURES / "psl-nina34.anom.data").read_text()


@settings(max_examples=25, deadline=None, derandomize=True)
@given(st.lists(st.integers(-30, 30), min_size=12, max_size=12).filter(lambda ks: any(abs(k) > 25 for k in ks)))
def test_psl_rebase_is_invariant_to_a_new_base_period(ks):
    """Si PSL cambia la base de la anomalía (1981–2010 → otra), cada mes del año se corre una constante y la serie que
    publica el sitio, llevada a 1991–2020 (``rebase_anomalies``), no cambia: el sitio no depende de la base de PSL.
    Hypothesis elige las doce constantes en el rango de un cambio de base real (±0,30 °C, en centésimas como el
    archivo), con al menos una mayor que el umbral de reescritura de ``enso.drift``."""
    text = PSL_TEXT
    shift = [k / 100 for k in ks]

    def shifted(line: str) -> str:
        p = line.split()
        if len(p) != 13 or not p[0].isdigit():
            return line
        return p[0] + "".join(f" {float(v) + shift[m]:8.2f}" if float(v) > -99 else f" {v:>8}" for m, v in enumerate(p[1:]))
    other = "\n".join(shifted(l) for l in text.splitlines())
    a = cpc.rebase_anomalies(cpc.parse_psl_matrix(text, name="x").data, (1991, 2020))
    b = cpc.rebase_anomalies(cpc.parse_psl_matrix(other, name="x").data, (1991, 2020))
    assert [p["period"] for p in a] == [p["period"] for p in b]
    worst = max(abs(x["value"] - y["value"]) for x, y in zip(a, b) if x["value"] is not None)
    assert worst <= 0.011  # el redondeo a dos decimales del archivo y del resultado
    assert any(abs(x["value"] - y["value"]) > 0.25 for x, y in zip(cpc.parse_psl_matrix(text, name="x").data,
                                                                   cpc.parse_psl_matrix(other, name="x").data)
               if x["value"] is not None)  # la mutación sí cambió el archivo


def test_feed_order_and_encoding_are_invariants(targets, results):
    # Metamórficas sobre todos los feeds simulados: el orden de las entradas y la codificación no cambian lo publicado.
    for r in results:
        if r.kind == "feed" and r.mutation in ("items-reversed", "crlf", "bom", "date-utc", "date-gmt"):
            assert r.verdict in (D.BENIGN, D.NA), (r.target, r.mutation, r.verdict, r.signals)


# --- Los hallazgos, cada uno con su copia real --------------------------------------------------------------------------
def test_bom_and_utf16_text_sources_read_the_same():
    src = O.SOURCE_BY_ID["cpc-oni"]
    body = (D.FIXTURES / src.fixture).read_bytes()
    from enso.fetch import Response

    plain = src.parse(Response(src.urls[0], body, "fixture", 200)).data
    for variant in (b"\xef\xbb\xbf" + body, body.decode().encode("utf-16")):
        assert src.parse(Response(src.urls[0], variant, "fixture", 200)).data == plain


def test_gzip_body_is_a_clear_format_change():
    assert "gzip" in O.binary_body(b"\x1f\x8b\x08\x00abc")
    assert O.binary_body(b"YR MON\n") == ""


def test_html_adapters_read_latin1_pages():
    f = N.FEED_BY_ID["gobpe-imarpe"]
    body = (D.FIXTURES / f.fixture).read_bytes()
    a = N.parse_feed(body, f.url, "gobpe")
    b = N.parse_feed(body.decode("utf-8").encode("cp1252", errors="xmlcharrefreplace"), f.url, "gobpe")
    assert [i["title"] for i in a] == [i["title"] for i in b] and "�" not in "".join(i["title"] for i in b)


def test_gobpe_listing_of_another_institution_is_rejected():
    f = N.FEED_BY_ID["gobpe-imarpe"]
    other = (D.FIXTURES.parent / "news-probe" / "gobpe-senamhi.html").read_bytes()
    with pytest.raises(N.FeedError, match="ninguna nota de «imarpe»"):
        N.parse_feed(other, f.url, "gobpe")
    # El listado de la PCM trae notas de la Presidencia y aun así es el de la PCM.
    pcm = (D.FIXTURES.parent / "news-probe" / "gobpe-pcm.html").read_bytes()
    assert N.parse_feed(pcm, "https://www.gob.pe/institucion/pcm/noticias", "gobpe")


def test_usgs_epicentre_outside_the_query_box_is_rejected():
    f = N.FEED_BY_ID["usgs-sismos"]
    data = json.loads((D.FIXTURES / f.fixture).read_bytes())
    for feat in data["features"]:
        c = feat["geometry"]["coordinates"]
        c[0], c[1] = c[1], c[0]
    with pytest.raises(N.FeedError, match="fuera del área pedida"):
        H.parse(json.dumps(data).encode(), f.url, "geojson")


def test_epoch_seconds_instead_of_milliseconds_is_rejected():
    f = N.FEED_BY_ID["usgs-sismos"]
    data = json.loads((D.FIXTURES / f.fixture).read_bytes())
    for feat in data["features"]:
        feat["properties"]["time"] //= 1000
    with pytest.raises(N.FeedError, match="anterior a 1995"):
        H.parse(json.dumps(data).encode(), f.url, "geojson")


def test_arcgis_layer_in_web_mercator_is_rejected():
    f = N.FEED_BY_ID["senamhi-lluvias"]
    data = json.loads((D.FIXTURES / f.fixture).read_bytes())
    r = 6378137.0

    def merc(c):
        if isinstance(c[0], (int, float)):
            return [math.radians(c[0]) * r, math.log(math.tan(math.pi / 4 + math.radians(c[1]) / 2)) * r]
        return [merc(x) for x in c]
    for feat in data["features"]:
        feat["geometry"]["coordinates"] = merc(feat["geometry"]["coordinates"])
    with pytest.raises(N.FeedError, match="no está en el Perú"):
        H.parse(json.dumps(data).encode(), f.url, "arcgis")
    assert H.parse((D.FIXTURES / f.fixture).read_bytes(), f.url, "arcgis").items  # la copia real sí


def test_arcgis_layer_answering_other_warnings_is_a_format_error():
    f = N.FEED_BY_ID["senamhi-hidrologicos"]
    fwi = (D.FIXTURES / N.FEED_BY_ID["senamhi-incendios"].fixture).read_bytes()
    st, items, _ = N._read_feed(f, lambda u: (200, fwi, "", ""), D.NOW)
    assert st.get("formatError") and not items and "«fwi»" in st["error"]
    assert H.arcgis_kind_error(f.layer, "hidrologico") == ""


def test_firms_semicolons_swaps_and_empty_files_are_rejected():
    body = (D.FIXTURES / "news-firms-focos.csv").read_text()
    head, *rows = body.splitlines()
    with pytest.raises(N.FeedError, match="faltan las columnas"):
        H.parse(body.replace(",", ";").encode(), "", "firms")
    swapped = "\n".join([head] + [",".join([r.split(",")[1], r.split(",")[0], *r.split(",")[2:]]) for r in rows])
    with pytest.raises(N.FeedError, match="fuera de Sudamérica"):
        H.parse(swapped.encode(), "", "firms")
    with pytest.raises(N.FeedError, match="ninguna fila"):
        H.parse((head + "\n").encode(), "", "firms")
    assert H.parse(body.encode(), "", "firms").items[0]["points"]


def test_truncated_feeds_are_unreadable_but_keep_the_rescued_entries():
    from enso import persistent as P

    f = N.FEED_BY_ID["andina"]
    body = (D.FIXTURES / f.fixture).read_bytes()
    st, items, _ = N._read_feed(f, lambda u: (200, body[: len(body) * 6 // 10], "", ""), D.NOW)
    assert st["ok"] and st["truncated"] and 0 < st["items"] < 20
    assert P.feed_state(st, f, {}, D.NOW, P.rules())[0] == "unreadable"
    st, _, _ = N._read_feed(f, lambda u: (200, body, "", ""), D.NOW)
    assert "truncated" not in st


def test_truncated_ensodisc_is_a_format_change_and_missing_next_issue_warns():
    doc = (D.FIXTURES / "cpc-ensodisc.html").read_text()
    with pytest.raises(cpc.FormatChanged, match="cortada"):
        cpc.parse_enso_discussion(doc[: len(doc) * 6 // 10])
    no_next = doc.replace("scheduled for", "programmed for")
    assert any("próxima discusión" in w for w in cpc.parse_enso_discussion(no_next).warnings)
    assert not cpc.parse_enso_discussion(doc).warnings


def test_atom_source_gives_the_outlet():
    body = (b'<feed xmlns="http://www.w3.org/2005/Atom"><title>x</title><entry><title>Huaico en Chosica</title>'
            b'<link href="https://n.pe/1"/><published>2026-11-20T10:00:00-05:00</published>'
            b'<source><title>Diario Correo</title><link href="https://diariocorreo.pe"/></source></entry></feed>')
    it = N.parse_feed(body)[0]
    assert it["outlet"] == "Diario Correo" and it["outletUrl"] == "https://diariocorreo.pe"


def test_ptwc_trailing_spaces_keep_the_threat_section():
    body = (D.FIXTURES / "news-ptwc-wepa40.txt").read_bytes()
    a = H.parse(body, "", "ptwc-text").items[0]
    b = H.parse(body.replace(b"\n", b"   \n"), "", "ptwc-text").items[0]
    assert a == b and "THREAT" in a["summary"]


def test_dhn_aviso_without_a_readable_date_is_a_format_error():
    f = N.FEED_BY_ID["dhn-avisos"]
    body = (D.FIXTURES / f.fixture).read_bytes()
    assert b"Callao, 20 de octubre 2026" in body
    english = body.replace(b"20 de octubre 2026", b"October 20, 2026").replace(b" de octubre ", b" October ")
    with pytest.raises(N.FeedError, match="no tiene una fecha"):
        H.parse(english, f.url, "dhn-avisos")
    assert all(i["published"] for i in H.parse(body, f.url, "dhn-avisos").items)


def test_report_mode_json(tmp_path, capsys):
    out = tmp_path / "sim.json"
    code = D.main(["--target", "cpc-oni", "--mutation", "col-swap", "--mutation", "crlf", "--json", str(out)])
    assert code == 0
    data = json.loads(out.read_text())
    assert {(r["target"], r["mutation"], r["verdict"]) for r in data["results"]} == {
        ("cpc-oni", "col-swap", D.LOUD), ("cpc-oni", "crlf", D.BENIGN)}
    assert D.main(["--mutation", "nope"]) == 2
    assert D.main(["--target", "no-such-source"]) == 2


def test_ptwc_exercise_as_last_message_never_escalates_as_an_emptied_feed():
    # PACWAVE26 (noviembre de 2026): el último mensaje del PTWC es el simulacro hasta el próximo sismo, que puede tardar
    # semanas. Sin entradas a propósito; con el estado «empty» abría un issue a los 14 días (umbral max(3, 365) → 14).
    from datetime import timedelta

    from enso import persistent as P

    f = N.FEED_BY_ID["ptwc-wepa40"]
    body = (D.FIXTURES / "news-ptwc-wepa40-test-pacwave26.txt").read_bytes()

    class Log:
        def __init__(self):
            self.events = []

        def add(self, *a):
            self.events.append(a)
    prev, log = None, Log()
    for day in range(20):
        now = D.NOW + timedelta(days=day)
        st, items, _ = N._read_feed(f, lambda u: (200, body, "text/plain", None), now)
        assert st["ok"] and not items and not st.get("error"), st
        prev = P.update(prev, now, log, feeds=[(f, st)], official=lambda x: True)
    assert not (prev.get("entities") or {}).get("feed:ptwc-wepa40")
    assert not [e for e in log.events if e[0] in ("warning", "error")]
    # El mensaje real sí trae su entrada (la excepción es solo para el simulacro).
    real = (D.FIXTURES / "news-ptwc-wepa40.txt").read_bytes()
    assert N._read_feed(f, lambda u: (200, real, "text/plain", None), D.NOW)[0]["items"] == 1


# --- Lo que la prueba principal no distinguía (mutantes que sobrevivían) ------------------------------------------------
def test_whole_cp1252_document_is_not_read_as_utf8_pairs():
    from enso.feedparse import mostly_cp1252, text_of

    # «Ú–» en windows-1252 es DA 96, que también es una secuencia UTF-8 válida (U+0696 «ږ»).
    # Un documento de verdad (una página con muchas tildes), no una línea: con pocos bytes la regla no decide (ver
    # el último assert de abajo).
    cp = ("<p>Tumbes de Miércoles · PERÚ–ECUADOR · alerta en Zarumilla y Aguas Verdes</p>"
          + "<p>Según el SENAMHI, la temporada de lluvias comenzó en diciembre; el río Tumbes subió más de lo habitual "
            "y la población de Pampa Grande evacuó sus viviendas. Información: COER Tumbes, teléfono de emergencia.</p>"
          ).encode("cp1252")
    assert b"\xda\x96" in cp and mostly_cp1252(cp)
    assert "PERÚ–ECUADOR" in text_of(cp) and "Miércoles" in text_of(cp)
    # UTF-8 con un solo byte suelto de Windows: lo UTF-8 se queda UTF-8.
    mixed = "Año niño señal «Perú» acción".encode("utf-8") + b" \x93cita\x94"
    assert not mostly_cp1252(mixed) and text_of(mixed) == "Año niño señal «Perú» acción “cita”"
    # Límite de la regla (compromiso declarado): una sola línea en windows-1252 con un par que parece UTF-8 no tiene
    # bytes suficientes para decidir y ese par se lee como UTF-8.
    assert not mostly_cp1252("Miércoles · PERÚ–ECUADOR".encode("cp1252"))


def test_acquire_names_the_gzip_body_instead_of_a_parse_error():
    src = O.SOURCE_BY_ID["cpc-oni"]
    import gzip

    acq, _ = D._acquire(src, gzip.compress((D.FIXTURES / src.fixture).read_bytes()), None)
    assert not acq.ok and "gzip sin Content-Encoding" in (acq.error or ""), acq.error


def test_non_numeric_table_values_name_the_value_and_month():
    text = (D.FIXTURES / O.SOURCE_BY_ID["cpc-sstoi"].fixture).read_text()
    lines = text.splitlines()
    lines[1] = lines[1].replace(".", ",", 1)
    with pytest.raises(cpc.FormatChanged, match="valor no numérico «[0-9-]+,[0-9]+»"):
        cpc.parse_nino_monthly("\n".join(lines) + "\n", name="sstoi")
    psl = PSL_TEXT.splitlines()
    i = next(k for k, l in enumerate(psl) if l.split()[:1] and l.split()[0].isdigit() and len(l.split()) == 13)
    psl[i] = psl[i].replace(".", ",", 1)
    with pytest.raises(cpc.FormatChanged, match="no numérico"):
        cpc.parse_psl_matrix("\n".join(psl), name="psl")


def test_godas_summary_that_is_not_json_is_a_format_change():
    from enso.fetch import Response

    with pytest.raises(cpc.FormatChanged, match="no es JSON"):
        O._parse_godas(Response("https://x", b"<html>error</html>", "fixture", 200))


def test_impossible_coordinates_are_rejected_on_any_hazard_reader():
    p = H.Parsed("dhn-html", [{"title": "x", "published": "2026-11-20T00:00:00Z", "points": [{"lat": 120.0, "lon": -77.0}]}])
    with pytest.raises(N.FeedError, match="coordenadas imposibles"):
        H._vet(p, "", "dhn")
    ok = H.Parsed("dhn-html", [{"title": "x", "published": "2026-11-20T00:00:00Z", "points": [{"lat": -12.0, "lon": -77.0}]}])
    assert H._vet(ok, "", "dhn") is ok


def test_firms_rows_without_numeric_coordinates_are_rejected():
    head, *rows = (D.FIXTURES / "news-firms-focos.csv").read_text().splitlines()
    blank = [",,".join([""] + r.split(",")[2:]) if k % 4 else r for k, r in enumerate(rows)]
    with pytest.raises(N.FeedError, match="coordenadas numéricas"):
        H.parse(("\n".join([head] + blank) + "\n").encode(), "", "firms")


def test_an_emptied_feed_escalates_to_an_issue_after_its_threshold():
    # Hasta acá solo se veía ``feed_state`` == «empty»; esto comprueba que de verdad abre un aviso (degradacion.json).
    from datetime import timedelta

    from enso import persistent as P

    f = N.FEED_BY_ID["andina"]
    body = D.MUTATIONS["items-none"].apply((D.FIXTURES / f.fixture).read_bytes(), {"family": "xml"})

    class Log:
        def __init__(self):
            self.events = []

        def add(self, *a):
            self.events.append(a)
    prev, first = None, None
    rule = P.threshold("empty", f.stale_days, P.rules(), "feed:andina")
    for day in range(16):
        log = Log()
        now = D.NOW + timedelta(days=day)
        st, _, _ = N._read_feed(f, lambda u: (200, body, "", ""), now)
        prev = P.update(prev, now, log, feeds=[(f, st)], official=lambda x: False)
        if first is None and any(e[0] == "warning" and e[3] == "degraded-persistent" for e in log.events):
            first = day
    assert rule["days"] == max(3, f.stale_days) and first == math.ceil(rule["days"]), (rule, first)

