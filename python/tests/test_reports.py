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


def test_informe_links_from_portal_listing():
    html = ('<a href="https://enfen.imarpe.gob.pe/download/informe-tecnico-enfen-ano-12-n18-al-13-de-octubre-de-2026-2/'
            '?wpdmdl=2166&#038;refresh=6ad8">x</a>')
    assert R.informe_links(html) == {18: "https://enfen.imarpe.gob.pe/download/informe-tecnico-enfen-ano-12-n18-al-13-"
                                         "de-octubre-de-2026-2/?wpdmdl=2166"}


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


# --- Adquisición: una vez por comunicado, último valor bueno si falla ---------------------------------------


class _Log:
    def __init__(self):
        self.events = []

    def add(self, severity, source, stage, code, message):
        self.events.append((severity, code, message))


class _Fetcher:
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


LATEST = {"number": 18, "id": "18-2026", "informe_url": "https://enfen.imarpe.gob.pe/download/informe-x/?wpdmdl=1"}


def test_acquire_reuses_the_informe_already_read():
    prev = {"number": 18, "icenProvisional": {"period": "2026-09", "icen": 4.15}}
    f = _Fetcher({})
    assert R.acquire_informe(LATEST, f, prev, _Log(), date(2026, 10, 21)) is prev and f.asked == []


def test_acquire_keeps_last_good_value_when_download_fails():
    prev = {"number": 17, "icenProvisional": {"period": "2026-08", "icen": 3.97}}
    log = _Log()
    res = R.acquire_informe(LATEST, _Fetcher({}), prev, log, date(2026, 10, 21))
    assert res["carried"] and res["icenProvisional"]["icen"] == 3.97 and res["number"] == 17
    assert any(c == "informe-unread" and s == "error" for s, c, _ in log.events)


def test_acquire_keeps_last_good_value_when_format_changes(monkeypatch):
    prev = {"number": 17, "icenProvisional": {"period": "2026-08", "icen": 3.97}}
    monkeypatch.setattr(R, "pdf_pages", lambda b: ["Documento sin tablas"])
    log = _Log()
    res = R.acquire_informe(LATEST, _Fetcher({LATEST["informe_url"]: b"%PDF-1.7 x"}), prev, log, date(2026, 10, 21))
    assert res["carried"] and "review" not in res  # sin servicio de modelo configurado no hay propuesta
    assert any("formato" in m for _, _, m in log.events)


def test_acquire_reads_a_new_informe(monkeypatch):
    pages, _ = _pages(N18)
    monkeypatch.setattr(R, "pdf_pages", lambda b: pages)
    res = R.acquire_informe(LATEST, _Fetcher({LATEST["informe_url"]: b"%PDF-1.7 x"}), None, _Log(), date(2026, 10, 21))
    assert res["number"] == 18 and res["icenProvisional"]["icen"] == 4.15 and res["communique"] == "18-2026"
    assert res["url"] == LATEST["informe_url"] and len(res["probabilities"]) == 2


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


def test_llm_failure_never_raises(monkeypatch):
    monkeypatch.setenv(R.LLM_URL_ENV, "https://n8n.example/webhook/extract")
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    assert R.llm_extract(client, "enfen-informe", "texto", url="u")["ok"] is False
