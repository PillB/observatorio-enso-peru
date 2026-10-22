"""Informes en texto libre del ENFEN: lectura, esquema, plausibilidad y procedencia.

Backtesting sobre cinco informes técnicos reales (texto por página de los PDF de junio de 2024 a octubre de
2026, que cambian de maquetación) y el comunicado N° 18-2026.
"""

from __future__ import annotations

import copy
import gzip
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from enso import reports as R
from enso.feeds import peru

REP = Path(__file__).parent / "fixtures" / "reports"
INFORMES = sorted(REP.glob("informe-tecnico-*.pages.json.gz"))
C18 = peru.pdf_text((REP / "comunicado-enfen-18-2026.pdf").read_bytes())


def _pages(name: str) -> tuple[list[str], str]:
    d = json.loads(gzip.open(REP / name, "rt", encoding="utf-8").read())
    return d["pages"], d["source"]


N18 = "informe-tecnico-enfen-ano-12-n18-al-13-de-octubre-de-2026.pages.json.gz"
N17 = "informe-tecnico-enfen-ano-12-n17-al-25-de-setiembre-de-2026.pages.json.gz"

# Valores leídos a mano de cada PDF: (número, fecha, último ICEN oficial, ICEN temporal, columnas).
EXPECTED = {
    "informe-tecnico-enfen-ano-10-n09-al-12-de-junio-de-2024.pages.json.gz":
        (9, "2024-06-12", ("2024-04", -0.11), ("2024-05", -0.56), ["icen", "oni"]),
    "informe-tecnico-enfen-ano-11-n06-al-16-de-abril-de-2025.pages.json.gz":
        (6, "2025-04-16", ("2025-02", 0.45), ("2025-03", 0.72), ["icen", "oni"]),
    "informe-tecnico-enfen-ano-11-n14-al-16-de-diciembre-de-2025.pages.json.gz":
        (14, "2025-12-16", ("2025-10", -0.42), ("2025-11", -0.55), ["icen", "oni"]),
    N17: (17, "2026-09-25", ("2026-07", 3.38), ("2026-08", 3.97), ["icen", "roni", "oni"]),
    N18: (18, "2026-10-13", ("2026-08", 3.98), ("2026-09", 4.15), ["icen", "roni", "oni"]),
}


@pytest.mark.parametrize("name", list(EXPECTED))
def test_informe_index_table_backtest(name):
    pages, url = _pages(name)
    ext = R.parse_informe(pages, url)
    number, data_to, last, tmp, cols = EXPECTED[name]
    ind = ext.data["indices"]
    assert ext.data["number"] == number and ext.data["dataTo"] == data_to
    assert ind["columns"] == cols
    assert (ind["official"][-1]["period"], ind["official"][-1]["icen"]) == last
    assert (ind["provisional"][0]["period"], ind["provisional"][0]["icen"]) == tmp
    assert len(ind["official"]) == 12  # doce meses oficiales en todas las ediciones
    # Procedencia: la cita contiene el valor y la página es la de la tabla.
    ev = ind["provisional"][0]["evidence"]
    assert f"{abs(tmp[1]):.2f}" in ev["quote"] and 20 <= ev["page"] <= 40
    R.validate_informe(ext, today=date.fromisoformat(data_to))
    assert ext.publishable, ext.issues
    assert not R.check(R.SCHEMAS["enfen-informe"], ext.data)


@pytest.mark.parametrize("name", [n for n in EXPECTED if "2024" not in n])
def test_informe_probability_tables_sum_to_100(name):
    pages, url = _pages(name)
    ext = R.validate_informe(R.parse_informe(pages, url))
    probs = ext.data["probabilities"]
    assert sorted(t["region"] for t in probs) == ["nino12", "nino34"]
    for t in probs:
        assert len(t["months"]) == 9 and not t.get("invalid")
        assert len(t["categories"]) == 8  # cuatro frías/neutro y cuatro cálidas por región
        assert "calida_extraordinaria" in t["categories"] if t["region"] == "nino12" else "calida_muy_fuerte" in t["categories"]
        for i in range(9):
            assert 98 <= sum(v[i] for v in t["categories"].values()) <= 102


def test_informe_18_values_match_the_pdf():
    pages, url = _pages(N18)
    s = R.informe_summary(R.validate_informe(R.parse_informe(pages, url), today=date(2026, 10, 21)))
    n12 = next(t for t in s["probabilities"] if t["region"] == "nino12")
    assert n12["months"][0] == "2026-10" and n12["months"][-1] == "2027-06"
    assert n12["categories"]["calida_extraordinaria"] == [98, 95, 80, 65, 45, 34, 20, 14, 5]
    assert n12["review"]  # el ENFEN marcó la tabla con «(Revisar los valores)»
    assert s["icenProvisional"]["roni"] == 2.01 and s["icenProvisional"]["oni"] == 2.71


def test_summer_column_and_seasonal_tables():
    pages, url = _pages(N17)
    t = next(t for t in R.parse_informe(pages, url).data["probabilities"] if t["region"] == "nino12")
    assert t["summer"] == {"fria_fuerte": 0, "fria_moderada": 0, "fria_debil": 0, "neutro": 0, "calida_debil": 0,
                           "calida_moderada": 5, "calida_fuerte": 43, "calida_extraordinaria": 52}
    pages, url = _pages("informe-tecnico-enfen-ano-11-n14-al-16-de-diciembre-de-2025.pages.json.gz")
    seasonal = R.parse_informe(pages, url).data["seasonal"]
    n12 = next(s for s in seasonal if s["region"] == "nino12")
    assert n12["categories"]["neutro"] == 58 and sum(n12["categories"].values()) == 100


# --- Reglas de plausibilidad: lo que no cuadra no se publica --------------------------------------------


def _n18():
    pages, url = _pages(N18)
    return R.parse_informe(pages, url)


def test_probability_column_that_does_not_sum_100_is_withheld():
    ext = _n18()
    ext.data["probabilities"][0]["categories"]["calida_fuerte"][0] += 30
    s = R.informe_summary(R.validate_informe(ext))
    assert any(i.code == "informe-probability-sum" for i in ext.issues)
    assert [t["region"] for t in s["probabilities"]] == [ext.data["probabilities"][1]["region"]]


def test_implausible_provisional_icen_goes_to_review():
    ext = _n18()
    ext.data["indices"]["provisional"][0]["icen"] = 1.0  # 3 °C menos que el mes anterior
    s = R.informe_summary(R.validate_informe(ext))
    assert any(i.code == "informe-icen-jump" and i.severity == "error" for i in ext.issues)
    assert s["icenProvisional"] is None and s["lastOfficial"]["icen"] == 3.98


def test_out_of_range_value_fails_the_schema():
    ext = _n18()
    ext.data["indices"]["official"][3]["icen"] = 9.9
    errs = R.check(R.SCHEMAS["enfen-informe"], ext.data)
    assert errs and "official[3].icen" in errs[0]


def test_provisional_superseded_by_igp():
    ext = _n18()
    igp = [{"period": "2026-08", "value": 3.98}, {"period": "2026-09", "value": 4.10}]
    R.validate_informe(ext, icen_official=igp)
    assert any(i.code == "informe-provisional-superseded" for i in ext.issues)
    assert R.informe_summary(ext)["icenProvisional"] is None


def test_mismatch_with_igp_is_a_warning():
    ext = _n18()
    R.validate_informe(ext, icen_official=[{"period": "2026-08", "value": 3.70}])
    w = [i for i in ext.issues if i.code == "informe-icen-mismatch"]
    assert w and w[0].severity == "warning" and ext.publishable


def test_unrecognized_document_raises_format_changed():
    with pytest.raises(R.FormatChanged):
        R.parse_informe(["AÑO 12 N° 19 INFORME TÉCNICO ENFEN", "Sin tablas"], "")


# --- Comunicado: enlace al informe y perspectiva ----------------------------------------------------------


def test_informe_link_rejoins_the_wrapped_url():
    assert R.informe_link(C18) == ("https://enfen.imarpe.gob.pe/download/informe-tecnico-enfen-ano-12-n18-al-13-de-"
                                   "octubre-de-2026-2/?wpdmdl=2166")
    t = "consultar el Informe Técnico:\nhttps://enfen.imarpe.gob.pe/download/informe-tecnico-enfen-ano-11-n14-al-16-de-diciembre- de-2025/\n\n1 nota"
    assert R.informe_link(t).endswith("diciembre-de-2025/")


U18 = "https://enfen.imarpe.gob.pe/download/informe-tecnico-enfen-ano-12-n18-al-13-de-octubre-de-2026-2/?wpdmdl=2166"


def test_informe_entries_from_portal_listing():
    html = ('<a href="https://enfen.imarpe.gob.pe/download/informe-tecnico-enfen-ano-12-n18-al-13-de-octubre-de-2026-2/'
            '?wpdmdl=2166&#038;refresh=6ad8">x</a>')
    assert R.informe_entries(html) == [{"url": U18, "year": 2026, "n": 18, "dataTo": "2026-10-13"}]


def _a(slug):
    return f'<a href="https://enfen.imarpe.gob.pe/download/{slug}/">x</a>'


LISTING = "".join(_a(x) for x in (
    "informe-tecnico-enfen-ano-12-n12-al-12-de-junio-de2026", "informe-tecnico-enfen-ano-12-n12-al-24-de-junio-de2026",
    "informe-tecnico-enfen-ano-11-n06-al-16-de-abril-de-2025", "informe-tecnico-enfen-ano-11-n05-al-14-de-marzo-de-2025",
    "informe-tecnico-enfen-ano-10-n13-al-10-de-julio-de-2024"))


def test_informe_is_picked_by_date_not_by_number():
    e = R.informe_entries(LISTING)
    assert len(e) == 5  # dos «n12» del mismo año no se pisan
    # 2025 va un número adelante: el comunicado 05-2025 (18 de abril) cita el informe N° 06.
    assert R.pick_informe(e, {"id": "05-2025", "year": 2025, "issued": "2025-04-18"})["n"] == 6
    assert "24-de-junio" in R.pick_informe(e, {"id": "12-2026", "issued": "2026-06-26"})["url"]
    # El N° 13 de 2024 nunca es el informe del comunicado 13-2026.
    assert R.pick_informe(e, {"id": "13-2026", "year": 2026, "issued": "2026-07-10"}) is None


HIST = Path(__file__).parent / "fixtures" / "sources" / "history"


@pytest.mark.parametrize("name", ["enfen-pdf-imarpe-20250610123158.txt", "enfen-pdf-imarpe-20250610131514.txt",
                                  "enfen-pdf-imarpe-20250804102527.txt", "enfen-pdf-imarpe-20260214031330.txt",
                                  "enfen-pdf-imarpe-20261020175050.txt"])
def test_real_communiques_cite_an_informe_within_the_lag_window(name):
    # 2024 coincide en número, 2025 va uno adelante (05-2025 → N° 06, 13-2025 → N° 14): la fecha siempre encaja.
    t = peru.pdf_text((HIST / name).read_bytes())
    c = peru.parse_enfen_communique(t).data
    ref = R.informe_ref(R.informe_link(t))
    assert R.pick_informe([ref], c) == ref


def test_dhn_mirror_listing_and_url():
    html = '<a href="https://www.dhn.mil.pe/Archivos/oceanografia/enfen/informe-tecnico/16-2026.pdf">x</a>' \
           '<a href="https://www.dhn.mil.pe/Archivos/oceanografia/enfen/informe-tecnico/20-2025.pdf">y</a>'
    hit = R.pick_informe(R.dhn_entries(html), {"id": "17-2026", "year": 2026, "issued": "2026-10-02"})
    assert hit["url"].endswith("/informe-tecnico/16-2026.pdf")
    assert R.mirrors(U18) == [U18, "https://www.dhn.mil.pe/Archivos/oceanografia/enfen/informe-tecnico/18-2026.pdf"]


def test_communique_outlook_with_quote():
    out = {o["region"]: o for o in R.communique_outlook(C18)}
    assert out["nino12"]["magnitude"] == "extraordinaria" and out["nino12"]["until"] == "2027-01"
    assert out["nino12"]["then"] == "fuerte" and out["nino12"]["phase"] == "calida"
    assert out["nino34"]["magnitude"] == "muy_fuerte" and out["nino34"]["until"] == "2027-02"
    q = out["nino12"]["quote"]
    assert "región Niño 1+2" in q and "magnitud de extraordinaria hasta enero" in q  # sin la llamada de nota «2»
    assert q.replace("extraordinaria hasta", "extraordinaria2 hasta") in " ".join(C18.split())


def test_cold_outlook_is_marked_cold():
    t = ("PERSPECTIVAS El pronóstico de los modelos para el Pacífico ecuatorial central (región Niño 3.4) indica el "
         "desarrollo de condiciones frías, de magnitud moderada a fuerte, hasta fin de año.")
    assert R.communique_outlook(t)[0]["phase"] == "fria"


@pytest.mark.parametrize("text", [
    # El nombre del sistema de alerta menciona La Niña en la misma oración.
    "El ENFEN mantiene el estado del “sistema de alerta ante El Niño costero y La Niña costera” en “Alerta de El Niño "
    "costero”, debido a que en la región Niño 1+2 se espera que El Niño costero continúe con magnitud moderada hasta "
    "marzo de 2027.",
    # Una transición posterior a condiciones frías no cambia la fase de la perspectiva.
    "En la región Niño 1+2 se espera que El Niño costero continúe con magnitud débil hasta enero de 2027, para luego "
    "dar paso a condiciones neutras o frías.",
    "Sistema de alerta ante El Niño costero y La Niña costera: Alerta de El Niño Costero " + C18[C18.find("Frente"):],
])
def test_warm_outlook_is_not_read_as_la_nina(text):
    assert R.communique_outlook(text, "Alerta de El Niño Costero")[0]["phase"] == "calida"


def test_outlook_phase_falls_back_to_the_alert_state():
    t = "En la región Niño 1+2 se espera que continúe con magnitud débil hasta febrero de 2023."
    assert R.communique_outlook(t, "Alerta de La Niña Costera")[0]["phase"] == "fria"
    assert R.communique_outlook(t, "Alerta de El Niño Costero")[0]["phase"] == "calida"


def test_month_range_without_de_before_the_first_year():
    assert len(R._month_range("entre diciembre 2025 y agosto 2026")) == 9
    assert len(R._month_range("entre diciembre del 2025 y agosto del 2026")) == 9
    assert len(R._month_range("entre abril y diciembre 2025")) == 9


# --- Adquisición: una vez por comunicado, último valor bueno si falla ---------------------------------------


class _Log:
    def __init__(self):
        self.events = []

    def add(self, severity, source, stage, code, message):
        self.events.append((severity, code, message))


class _Fetcher:
    offline = True  # sin Internet Archive

    def __init__(self, responses: dict):
        self.responses, self.asked = responses, []
        self.client = None

    def get(self, urls, **kw):
        from enso.fetch import FetchError, Response

        for u in urls:
            self.asked.append(u)
            if u in self.responses:
                return Response(u, self.responses[u], "direct", 200)
        raise FetchError("sin respuesta", [])


LATEST = {"number": 18, "id": "18-2026", "year": 2026, "issued": "2026-10-16", "informe_url": U18}
DHN18 = "https://www.dhn.mil.pe/Archivos/oceanografia/enfen/informe-tecnico/18-2026.pdf"
PREV = {"number": 17, "communique": "17-2026", "url": "u17", "icenProvisional": {"period": "2026-08", "icen": 3.97}}


def test_acquire_reuses_the_informe_already_read():
    prev = {"number": 18, "communique": "18-2026", "icenProvisional": {"period": "2026-09", "icen": 4.15}}
    f = _Fetcher({})
    assert R.acquire_informe(LATEST, f, prev, _Log(), date(2026, 10, 21)) is prev and f.asked == []


def test_acquire_reads_the_new_informe_even_if_numbers_are_offset(monkeypatch):
    # 2025: el comunicado 06 trae el informe N° 07; el anterior (N° 06) iba con el comunicado 05.
    pages, _ = _pages(N18)
    monkeypatch.setattr(R, "pdf_pages", lambda b: pages)
    prev = {"number": 18, "communique": "17-2026", "url": "u17", "icenProvisional": {"period": "2026-08", "icen": 3.97}}
    f = _Fetcher({U18: b"%PDF-1.7 x"})
    res = R.acquire_informe(LATEST, f, prev, _Log(), date(2026, 10, 21))
    assert f.asked == [U18] and res["communique"] == "18-2026" and res["dataTo"] == "2026-10-13"


def test_acquire_keeps_last_good_value_when_download_fails():
    log = _Log()
    f = _Fetcher({})
    res = R.acquire_informe(LATEST, f, PREV, log, date(2026, 10, 21))
    assert res["carried"] and res["icenProvisional"]["icen"] == 3.97 and res["number"] == 17
    assert f.asked[:2] == [U18, DHN18]  # portal y réplica de la DHN
    # Un documento auxiliar que no responde no marca la publicación como degradada.
    assert [(s, c) for s, c, _ in log.events] == [("warning", "informe-unread")]


def test_acquire_uses_the_dhn_mirror(monkeypatch):
    pages, _ = _pages(N18)
    monkeypatch.setattr(R, "pdf_pages", lambda b: pages)
    docs = []
    res = R.acquire_informe(LATEST, _Fetcher({DHN18: b"%PDF-1.7 dhn"}), None, _Log(), date(2026, 10, 21), documents=docs)
    assert res["icenProvisional"]["icen"] == 4.15 and docs == [b"%PDF-1.7 dhn"]
    assert res["archive"].startswith("archive/sources/enfen-comunicados/") and res["archive"].endswith(".pdf")


def test_acquire_finds_the_informe_in_the_listing_by_date(monkeypatch):
    pages, _ = _pages(N18)
    monkeypatch.setattr(R, "pdf_pages", lambda b: pages)
    listing = _a("informe-tecnico-enfen-ano-12-n18-al-13-de-octubre-de-2026-2") + _a(
        "informe-tecnico-enfen-ano-11-n18-al-10-de-octubre-de-2025")
    url = "https://enfen.imarpe.gob.pe/download/informe-tecnico-enfen-ano-12-n18-al-13-de-octubre-de-2026-2/"
    f = _Fetcher({R.INFORMES_PAGE: listing.encode(), url: b"%PDF-1.7 x"})
    res = R.acquire_informe({**LATEST, "informe_url": None}, f, None, _Log(), date(2026, 10, 21))
    assert res["url"] == url and res["number"] == 18


def test_acquire_rejects_the_informe_of_another_communique(monkeypatch):
    pages, _ = _pages(N17)  # datos al 25 de setiembre: no es el informe de un comunicado del 30 de octubre
    monkeypatch.setattr(R, "pdf_pages", lambda b: pages)
    log = _Log()
    late = {**LATEST, "id": "18-2026", "issued": "2026-10-16"}
    res = R.acquire_informe(late, _Fetcher({U18: b"%PDF-1.7 x"}), PREV, log, date(2026, 10, 31))
    assert res["carried"] and res["number"] == 17
    # Lo esperable mientras la réplica se atrasa: solo una advertencia (la publicación no queda degradada) y el
    # PDF de otro periodo no se archiva.
    assert [(sev, c) for sev, c, _ in log.events] == [("warning", "informe-unread")]
    assert "no es el del comunicado 18-2026" in log.events[0][2]


def test_acquire_keeps_last_good_value_when_format_changes(monkeypatch):
    monkeypatch.setattr(R, "pdf_pages", lambda b: ["Documento sin tablas"])
    log = _Log()
    res = R.acquire_informe(LATEST, _Fetcher({U18: b"%PDF-1.7 x"}), PREV, log, date(2026, 10, 21))
    assert res["carried"] and "review" not in res  # sin servicio de modelo configurado no hay propuesta
    assert any("formato" in m and "Se conserva" in m for _, _, m in log.events)


def test_llm_proposal_survives_without_a_previous_informe(monkeypatch):
    monkeypatch.setattr(R, "pdf_pages", lambda b: ["Documento sin tablas"])
    calls = []
    monkeypatch.setattr(R, "llm_extract", lambda *a, **k: calls.append(1) or {"ok": True, "data": {"number": 18}})
    log = _Log()
    res = R.acquire_informe(LATEST, _Fetcher({U18: b"%PDF-1.7 x"}), None, log, date(2026, 10, 21))
    assert res["carried"] and res["review"]["proposal"]["data"] == {"number": 18} and not res.get("probabilities")
    assert any("queda para revisión" in m and "Se conserva" not in m for _, _, m in log.events)
    # Al día siguiente, el mismo PDF no se le vuelve a pasar al modelo.
    again = R.acquire_informe(LATEST, _Fetcher({U18: b"%PDF-1.7 x"}), res, _Log(), date(2026, 10, 22))
    assert len(calls) == 1 and again["review"] == res["review"]


def test_acquire_reads_a_new_informe(monkeypatch):
    pages, _ = _pages(N18)
    monkeypatch.setattr(R, "pdf_pages", lambda b: pages)
    res = R.acquire_informe(LATEST, _Fetcher({U18: b"%PDF-1.7 x"}), None, _Log(), date(2026, 10, 21))
    assert res["number"] == 18 and res["icenProvisional"]["icen"] == 4.15 and res["communique"] == "18-2026"
    assert res["url"] == U18 and len(res["probabilities"]) == 2


def test_informe_periods_must_fit_its_date():
    pages, url = _pages(N18)
    ext = R.parse_informe([p.replace("de 2026 y", "de 2016 y").replace("de 2027", "de 2017") for p in pages], url)
    R.validate_informe(ext, today=date(2026, 10, 21))
    assert any(i.code.startswith("informe-period") for i in ext.issues) and not R.informe_summary(ext)["probabilities"]


def test_seasonal_label_variants_do_not_block_other_values():
    pages, url = _pages("informe-tecnico-enfen-ano-11-n14-al-16-de-diciembre-de-2025.pages.json.gz")
    for variant in ("diciembre 2025 – marzo 2026", "diciembre de 2025 a marzo de 2026", "verano 2026"):
        alt = [p.replace("diciembre 2025 - marzo 2026", variant) for p in pages]
        ext = R.validate_informe(R.parse_informe(alt, url), today=date(2025, 12, 20))
        s = R.informe_summary(ext)
        assert s["icenProvisional"] and len(s["probabilities"]) == 2, variant
        assert not any(i.code.startswith("informe-schema") for i in ext.issues), variant


# --- Respaldo con modelo de lenguaje: validado y solo como propuesta -----------------------------------------


def test_llm_extract_is_off_without_endpoint(monkeypatch):
    monkeypatch.delenv(R.LLM_URL_ENV, raising=False)
    assert R.llm_extract(httpx.Client(), "enfen-informe", "x", url="u") is None


def test_llm_output_is_schema_checked(monkeypatch):
    monkeypatch.setenv(R.LLM_URL_ENV, "https://n8n.example/webhook/extract")
    sent = {}

    def handler(req):
        sent.update(json.loads(req.content))
        bad = {"number": 18, "indices": {"official": [{"period": "2026-08", "icen": 12.0}], "provisional": []},
               "probabilities": []}
        return httpx.Response(200, json={"data": bad, "model": "modelo-x",
                                              "evidence": {"indices.official.0.icen": "ICEN 12,0"}})

    res = R.llm_extract(httpx.Client(transport=httpx.MockTransport(handler)), "enfen-informe", "texto", url="u")
    assert sent["schema"] == R.SCHEMAS["enfen-informe"] and sent["kind"] == "enfen-informe"
    assert res["ok"] and res["model"] == "modelo-x" and any("icen" in e for e in res["schemaErrors"])
    assert res["evidence"] == {"indices.official.0.icen": "ICEN 12,0"}


@pytest.mark.parametrize("reply", [[{"data": {}, "model": "m"}], "ok", 5])
def test_llm_reply_that_is_not_an_object_never_raises(monkeypatch, reply):
    monkeypatch.setenv(R.LLM_URL_ENV, "https://n8n.example/webhook/extract")
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=reply)))
    res = R.llm_extract(client, "enfen-informe", "texto", url="u")
    assert res["ok"] is False and res["model"] is None


def test_llm_failure_never_raises(monkeypatch):
    monkeypatch.setenv(R.LLM_URL_ENV, "https://n8n.example/webhook/extract")
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    assert R.llm_extract(client, "enfen-informe", "texto", url="u")["ok"] is False


# --- Documentos que hay que bajar a mano (enso.manual) ----------------------------------------------------


class _ManualFetcher(_Fetcher):
    """Las URL de ``manual`` llegan como copias subidas en la consola (canal «relay-manual»)."""

    def __init__(self, responses: dict, manual: dict):
        super().__init__(responses)
        self.manual = manual

    def get(self, urls, **kw):
        from enso.fetch import Response

        for u in urls:
            if u in self.manual:
                self.asked.append(u)
                return Response(u, self.manual[u], "relay-manual", 200, archived_at="2026-10-21T21:00:00+00:00")
        return super().get(urls, **kw)

    def copy(self, url, accept=()):
        from enso.fetch import Response

        body = self.manual.get(url)
        return Response(url, body, "relay-manual", 200, archived_at="2026-10-21T21:00:00+00:00") if body else None


def test_informe_that_no_route_brings_is_listed_for_manual_download():
    from enso import manual

    needs = manual.ManualNeeds()
    R.acquire_informe(LATEST, _Fetcher({}), PREV, _Log(), date(2026, 10, 21), needs=needs)
    item = needs.items["informe-18-2026"]
    assert item["kind"] == "informe" and U18 in item["urls"] and DHN18 in item["urls"]
    assert manual.key("enfen-informe", "18-2026") in item["urls"]
    assert item["open"][0] == U18 and R.INFORMES_PAGE in item["open"]
    assert not any(u.startswith("manual://") for u in item["open"])
    assert "verificación humana" in item["reason"]


def test_informe_uploaded_by_hand_is_read_and_reported(monkeypatch):
    from enso import manual

    pages, _ = _pages(N18)
    monkeypatch.setattr(R, "pdf_pages", lambda b: pages)
    needs = manual.ManualNeeds()
    res = R.acquire_informe(LATEST, _ManualFetcher({}, {U18: b"%PDF-1.7 a mano"}), PREV, _Log(), date(2026, 10, 21),
                            needs=needs)
    assert res["channel"] == "relay-manual" and res["number"] == 18 and not res.get("carried")
    assert not needs.items and [u["id"] for u in needs.used] == ["informe-18-2026"]


def test_informe_uploaded_by_hand_of_another_period_is_not_published(monkeypatch):
    from enso import manual

    pages, _ = _pages(N17)
    monkeypatch.setattr(R, "pdf_pages", lambda b: pages)
    needs = manual.ManualNeeds()
    res = R.acquire_informe(LATEST, _ManualFetcher({}, {U18: b"%PDF-1.7 otro"}), PREV, _Log(), date(2026, 10, 21),
                            needs=needs)
    assert res["carried"] and not needs.used
    assert "N° 17" in needs.items["informe-18-2026"]["problem"]


def test_informe_without_a_known_url_is_read_from_the_upload_key(monkeypatch):
    from enso import manual

    pages, _ = _pages(N18)
    monkeypatch.setattr(R, "pdf_pages", lambda b: pages)
    needs = manual.ManualNeeds()
    f = _ManualFetcher({}, {manual.key("enfen-informe", "18-2026"): b"%PDF-1.7 a mano"})
    res = R.acquire_informe({**LATEST, "informe_url": None}, f, None, _Log(), date(2026, 10, 21), needs=needs)
    assert res["number"] == 18 and res["url"] == f"{R.INFORMES_PAGE}#comunicado-18-2026"
    # Sin copia: queda pendiente con la clave y los listados para abrir.
    needs = manual.ManualNeeds()
    R.acquire_informe({**LATEST, "informe_url": None}, _ManualFetcher({}, {}), None, _Log(), date(2026, 10, 21), needs=needs)
    assert needs.items["informe-18-2026"]["urls"] == [manual.key("enfen-informe", "18-2026")]
    assert needs.items["informe-18-2026"]["open"] == [R.INFORMES_PAGE, R.DHN_INFORMES_PAGE]


def test_one_tables_period_does_not_withhold_the_provisional_icen():
    pages, url = _pages(N18)
    ext = R.parse_informe(pages, url)
    t34 = next(t for t in ext.data["probabilities"] if t["region"] == "nino34")
    t34["months"] = [m.replace("2026", "2016").replace("2027", "2017") for m in t34["months"]]
    R.validate_informe(ext, today=date(2026, 10, 21))
    s = R.informe_summary(ext)
    assert s["icenProvisional"]["icen"] == 4.15
    assert [t["region"] for t in s["probabilities"]] == ["nino12"]
    assert {i.code for i in ext.issues} >= {"informe-period-probabilities"}


# --- Segunda revisión de PR #11 ----------------------------------------------------------------------------


def test_llm_error_never_publishes_the_secret_webhook_url(monkeypatch):
    secret = "https://n8n.example/webhook/s3cr3t-token-path"
    monkeypatch.setenv(R.LLM_URL_ENV, secret)
    for reply in (lambda req: httpx.Response(500), lambda req: httpx.Response(403, text=f"denied {secret}")):
        res = R.llm_extract(httpx.Client(transport=httpx.MockTransport(reply)), "enfen-informe", "t", url="u")
        assert res["ok"] is False and res["transport"] and "HTTP" in res["error"]
        assert "s3cr3t" not in json.dumps(res)

    def boom(req):
        raise httpx.ConnectError(f"no route to {secret}")

    res = R.llm_extract(httpx.Client(transport=httpx.MockTransport(boom)), "enfen-informe", "t", url="u")
    assert "s3cr3t" not in json.dumps(res) and res["error"] == "no se pudo conectar con el servicio"


def test_llm_transport_failure_is_retried_next_run_and_a_reply_is_not(monkeypatch):
    monkeypatch.setattr(R, "pdf_pages", lambda b: ["Documento sin tablas"])
    replies = [{"ok": False, "transport": True, "error": "el servicio respondió HTTP 503"},
               {"ok": True, "data": {"number": 18}}]
    calls = []
    monkeypatch.setattr(R, "llm_extract", lambda *a, **k: calls.append(1) or replies[len(calls) - 1])
    day1 = R.acquire_informe(LATEST, _Fetcher({U18: b"%PDF-1.7 x"}), None, _Log(), date(2026, 10, 21))
    day2 = R.acquire_informe(LATEST, _Fetcher({U18: b"%PDF-1.7 x"}), day1, _Log(), date(2026, 10, 22))
    day3 = R.acquire_informe(LATEST, _Fetcher({U18: b"%PDF-1.7 x"}), day2, _Log(), date(2026, 10, 23))
    assert len(calls) == 2 and day2["review"]["proposal"]["ok"] and day3["review"] == day2["review"]


def test_a_later_download_failure_keeps_the_review(monkeypatch):
    monkeypatch.setattr(R, "pdf_pages", lambda b: ["Documento sin tablas"])
    calls = []
    monkeypatch.setattr(R, "llm_extract", lambda *a, **k: calls.append(1) or {"ok": True, "data": {"number": 18}})
    day1 = R.acquire_informe(LATEST, _Fetcher({U18: b"%PDF-1.7 x"}), PREV, _Log(), date(2026, 10, 21))
    day2 = R.acquire_informe(LATEST, _Fetcher({}), day1, _Log(), date(2026, 10, 22))  # portal y DHN caídos
    assert day2["review"] == day1["review"]
    R.acquire_informe(LATEST, _Fetcher({U18: b"%PDF-1.7 x"}), day2, _Log(), date(2026, 10, 23))
    assert len(calls) == 1


def test_undated_dhn_pick_is_downloaded_and_validated_not_reused(monkeypatch):
    """Comunicado 18 sin enlace, portal caído y la DHN todavía solo con el informe 17: no se publica el 17 como
    el del 18, y cuando la DHN trae el 18 se lee."""
    dhn17 = R.DHN_INFORME.format(n=17, year=2026)
    prev = {"number": 17, "communique": "17-2026", "url": dhn17, "dataTo": "2026-09-25",
            "icenProvisional": {"period": "2026-08", "icen": 3.97}}
    latest = {**LATEST, "informe_url": None}
    listing17 = f'<a href="/Archivos/oceanografia/enfen/informe-tecnico/17-2026.pdf">17</a>'.encode()
    p17, _ = _pages(N17)
    monkeypatch.setattr(R, "pdf_pages", lambda b: p17)
    log = _Log()
    res = R.acquire_informe(latest, _Fetcher({R.DHN_INFORMES_PAGE: listing17, dhn17: b"%PDF-1.7 17"}), prev, log,
                            date(2026, 10, 21))
    assert res["carried"] and res["communique"] == "17-2026"  # no se presenta como el del comunicado 18
    assert [s for s, _, _ in log.events] == ["warning"]
    p18, _ = _pages(N18)
    monkeypatch.setattr(R, "pdf_pages", lambda b: p18)
    dhn18 = R.DHN_INFORME.format(n=18, year=2026)
    listing18 = listing17 + b'<a href="/Archivos/oceanografia/enfen/informe-tecnico/18-2026.pdf">18</a>'
    res = R.acquire_informe(latest, _Fetcher({R.DHN_INFORMES_PAGE: listing18, dhn18: b"%PDF-1.7 18"}), res, _Log(),
                            date(2026, 10, 22))
    assert res["number"] == 18 and res["communique"] == "18-2026" and not res.get("carried")


def test_outlook_subject_before_the_region():
    t = "Para el Pacífico central, La Niña (región Niño 3.4 - Figura 1) se mantendría con una magnitud débil hasta enero de 2027."
    assert [(o["region"], o["phase"]) for o in R.communique_outlook(t, "No activo")] == [("nino34", "fria")]
    assert [(o["region"], o["phase"]) for o in R.communique_outlook(t, "Alerta de El Niño Costero")] == [("nino34", "fria")]


def test_outlook_unread_detects_one_reworded_region_and_other_wordings():
    from enso.feeds import peru

    pdf = next((Path(__file__).parent / "fixtures" / "live-run" / "raw" / "enfen-comunicados").glob("*.pdf")).read_bytes()
    text = peru.pdf_text(pdf)
    assert R.outlook_unread(text, R.communique_outlook(text, "x")) == []
    reworded = text.replace("magnitud de extraordinaria", "categoría extraordinaria").replace(
        "magnitud extraordinaria", "categoría extraordinaria")
    assert R.outlook_unread(reworded, R.communique_outlook(reworded, "x")) == ["nino12"]
    assert R.outlook_unread("Se prevé un evento extraordinario en la región Niño 1+2.", []) == ["nino12"]
    assert R.outlook_unread("Son más probables las condiciones cálidas moderadas en febrero.", []) == ["general"]
