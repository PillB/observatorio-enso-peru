"""Backtesting de los lectores contra copias reales de cada fuente.

Cada archivo de ``history/`` es una versión publicada en otra fecha
(2004–2026) recuperada del Internet Archive. Si una institución cambió
su formato, estas pruebas lo muestran antes de que llegue a producción.
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import FIX, history, read
from enso.feeds import FormatChanged, cpc, peru


def _months(points):
    return [p["period"] for p in points]


def _ok_series(points, lo, hi, min_len=24):
    assert len(points) >= min_len
    per = _months(points)
    assert per == sorted(per) and len(per) == len(set(per)), "periodos desordenados o duplicados"
    vals = [p["value"] for p in points if p["value"] is not None]
    assert vals and all(lo <= v <= hi for v in vals)
    assert points[-1]["value"] is not None, "no debe terminar en valores faltantes de relleno"


# ---------------------------------------------------------------------------
# Fuentes actuales
# ---------------------------------------------------------------------------
def test_weekly_current_has_four_regions_and_recent_week():
    p = cpc.parse_weekly(read(FIX / "cpc-wksst9120.for"))
    assert set(p.data) == {"nino12", "nino3", "nino34", "nino4"}
    last = p.data["nino12"][-1]
    assert last["date"] >= "2026-10-01"
    assert -6 < last["anom"] < 8 and 15 < last["sst"] < 32


def test_monthly_oisst_and_ersst_columns_by_name():
    for name in ("cpc-sstoi.indices", "cpc-ersst5.nino.mth.91-20.ascii"):
        p = cpc.parse_nino_monthly(read(FIX / name), name=name)
        for k in ("nino12", "nino3", "nino34", "nino4"):
            _ok_series(p.data["anom"][k], -6, 8)
        # Las anomalías no pueden confundirse con temperaturas absolutas.
        assert all(abs(x["value"]) < 8 for x in p.data["anom"]["nino34"])


def test_roni_and_oni_map_season_to_centre_month():
    roni = cpc.parse_seasonal(read(FIX / "cpc-roni.txt"), name="roni").data
    oni = cpc.parse_seasonal(read(FIX / "cpc-oni.txt"), name="oni").data
    _ok_series(roni, -4, 4)
    _ok_series(oni, -4, 4)
    # DJF 1950 se centra en enero de 1950.
    assert roni[0]["period"] == "1950-01"
    assert roni[-1]["period"] >= "2026-07"


@pytest.mark.parametrize("name,lo,hi", [("cpc-soi.txt", -12, 12), ("cpc-wpac850.txt", -30, 30),
                                        ("cpc-cpac850.txt", -30, 30), ("cpc-epac850.txt", -30, 30)])
def test_year_matrix_sections(name, lo, hi):
    p = cpc.parse_year_matrix(read(FIX / name), lo=lo, hi=hi, name=name)
    sections = set(p.data)
    assert sections & {"anomaly", "standardized", "original"}
    for pts in p.data.values():
        per = _months(pts)
        assert per == sorted(per) and len(per) == len(set(per))


def test_wind_original_index_is_positive_for_easterlies():
    """CPC: valores positivos = viento del este. El clima medio del Pacífico central es de alisios."""
    p = cpc.parse_year_matrix(read(FIX / "cpc-cpac850.txt"), lo=-30, hi=30, name="cpac850")
    vals = [x["value"] for x in p.data["original"] if x["value"] is not None]
    assert sum(vals) / len(vals) > 3


def test_heat_content_index():
    p = cpc.parse_heat_content(read(FIX / "cpc-heat-content.txt"))
    assert set(p.data) == {"heat_130e80w", "heat_160e80w", "heat_180w100w"}
    _ok_series(p.data["heat_180w100w"], -6, 6)
    assert p.meta["climatology"] == "1981–2010"


def test_official_icen_file():
    p = peru.parse_icen_txt(read(FIX / "igp-icen.txt"))
    _ok_series(p.data, -4, 6, min_len=600)
    assert p.data[0]["period"] == "1950-01"
    assert p.data[-1]["period"] >= "2026-06"


def test_enso_discussion_current():
    d = cpc.parse_enso_discussion(read(FIX / "cpc-ensodisc.html")).data
    assert d["status"] and d["codes"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["issued"])
    assert d["next_issue"] > d["issued"]


def test_psl_csv_drops_minus_9999_fill():
    p = cpc.parse_psl_csv(read(FIX / "psl-nino12.long.anom.csv"), name="psl-nino12")
    assert all(x["value"] is None or x["value"] > -90 for x in p.data)
    assert p.data[-1]["value"] is not None


# ---------------------------------------------------------------------------
# Versiones históricas (formatos de otras épocas)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", history("cpc-ensodisc"), ids=lambda p: p.stem)
def test_enso_discussion_history(path):
    d = cpc.parse_enso_discussion(read(path)).data
    assert d["status"]
    year = int(path.stem.rsplit("-", 1)[1][:4])
    assert d["issued"] and abs(int(d["issued"][:4]) - year) <= 1


@pytest.mark.parametrize("path", history("cpc-roni"), ids=lambda p: p.stem)
def test_roni_history(path):
    _ok_series(cpc.parse_seasonal(read(path), name="roni").data, -4, 4)


@pytest.mark.parametrize("path", history("cpc-soi"), ids=lambda p: p.stem)
def test_soi_history(path):
    p = cpc.parse_year_matrix(read(path), lo=-12, hi=12, name="soi")
    assert p.data


@pytest.mark.parametrize("path", history("cpc-cpac850"), ids=lambda p: p.stem)
def test_wind_history(path):
    p = cpc.parse_year_matrix(read(path), lo=-30, hi=30, name="cpac850")
    assert p.data


@pytest.mark.parametrize("path", history("cpc-wksst") + history("cpc-wksst8110"), ids=lambda p: p.stem)
def test_weekly_history(path):
    p = cpc.parse_weekly(read(path))
    assert set(p.data) == {"nino12", "nino3", "nino34", "nino4"}
    assert len(p.data["nino34"]) > 100


@pytest.mark.parametrize("path", history("igp-icen") + history("igp-ICEN"), ids=lambda p: p.stem)
def test_icen_history(path):
    p = peru.parse_icen_txt(read(path))
    _ok_series(p.data, -4, 6, min_len=600)
    year = int(path.stem.rsplit("-", 1)[1][:4])
    assert int(p.data[-1]["period"][:4]) >= year - 1


def test_icen_history_values_are_stable_except_documented_revision():
    """El ICEN histórico solo cambia con una revisión metodológica.

    Hasta 2024 la base era fija (1981–2010); la Nota Técnica ENFEN 01-2024
    adoptó bases móviles de 30 años, lo que revisa todo el histórico. Entre
    copias anteriores a esa nota, 1997-12 debe coincidir.
    """
    pre = [p for p in history("igp-ICEN") if p.stem.rsplit("-", 1)[1][:4] < "2024"]
    vals = set()
    for path in pre:
        d = {x["period"]: x["value"] for x in peru.parse_icen_txt(read(path)).data}
        if "1997-12" in d:
            vals.add(round(d["1997-12"], 1))
    assert len(vals) <= 2


def _pdfs(prefix):
    return [p for p in history(prefix) if p.read_bytes()[:5] == b"%PDF-"]


@pytest.mark.parametrize("path", _pdfs("enfen-pdf-imarpe") + _pdfs("enfen-pdf-gob"), ids=lambda p: p.stem)
def test_enfen_communique_pdfs(path):
    c = peru.parse_enfen_communique(peru.pdf_text(path.read_bytes())).data
    assert c["status_code"] in {"no_activo", "vigilancia_nino", "alerta_nino", "vigilancia_nina", "alerta_nina"}
    assert 1 <= c["number"] <= 30 and 2015 <= c["year"] <= 2030
    assert c["issued"] and c["issued"][:4] in (str(c["year"]), str(c["year"] + 1))
    if c["next_issue"]:
        assert c["next_issue"] > c["issued"]


@pytest.mark.parametrize("path", history("enfen-comunicados"), ids=lambda p: p.stem)
def test_enfen_listing_current_portal(path):
    items = peru.parse_enfen_listing(read(path)).data
    assert items[0]["url"].startswith("http")
    year = int(path.stem.rsplit("-", 1)[1][:4])
    assert items[0]["year"] in (year, year - 1)


@pytest.mark.parametrize("path", history("enfen-gob-comunicado"), ids=lambda p: p.stem)
def test_enfen_listing_old_portal(path):
    year = int(path.stem.rsplit("-", 1)[1][:4])
    if year <= 2018:
        pytest.xfail("El portal de 2018 no enlazaba los comunicados con el patrón actual (limitación conocida)")
    items = peru.parse_enfen_listing(read(path)).data
    assert items[0]["year"] in (year, year - 1)


def test_format_change_is_reported_not_guessed():
    with pytest.raises(FormatChanged):
        peru.parse_icen_txt("<html><body>Mantenimiento</body></html>")
    with pytest.raises(FormatChanged):
        cpc.parse_heat_content("Página no disponible")
    with pytest.raises(FormatChanged):
        peru.parse_enfen_communique("Documento sin el encabezado esperado")


def test_fixture_index_matches_files():
    idx = json.loads((FIX / "index.json").read_text(encoding="utf-8"))
    for e in idx["entries"]:
        if e.get("status") == 200 and e.get("file"):
            assert (FIX / e["file"]).exists(), e["file"]
