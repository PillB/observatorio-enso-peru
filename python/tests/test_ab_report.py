"""tools/ab_report.py contra la copia real de /api/ab/stats?days=60 del 2026-11-21 (tests/fixtures/ab/).

Los valores esperados están calculados a mano (la cuenta va en el comentario) o vienen del propio servidor: los
intervalos de Wilson de ``decision.rows`` los calculó functions/_lib/ab.js en JavaScript, una implementación
independiente de la de Python.
"""

from __future__ import annotations

import copy
import http.server
import json
import math
import threading
from pathlib import Path

import pytest

from tools import ab_report as R

FIX = Path(__file__).parent / "fixtures" / "ab" / "stats-2026-11-21.json"

# Días UTC con un «Merge pull request» en la historia de primer padre (git log, TZ=UTC), entre el 22-10 y el 20-11.
MERGE_DAYS = {"2026-10-21", "2026-10-22", "2026-10-26", "2026-10-27", "2026-10-28", "2026-11-02", "2026-11-03",
              "2026-11-04", "2026-11-05", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-18",
              "2026-11-19", "2026-11-20"}


@pytest.fixture(scope="module")
def data():
    return R.load(str(FIX), None)


def _row(data, exp, v):
    return next(r for r in R.arm_rows(data["experiments"][exp]) if r["v"] == v)


def test_wilson_matches_the_servers_intervals_in_every_row(data):
    # 16 filas (4 + 4 + 3 + 3 + 2 versiones) con el intervalo que calculó el servidor en JS.
    n = 0
    for exp in data["experiments"].values():
        for row in exp["decision"]["rows"]:
            lo, hi = R.wilson(row["use"], row["view"])
            assert (lo, hi) == pytest.approx((row["lo"], row["hi"]), abs=1e-12), row
            n += 1
    assert n == 16


def test_wilson_by_hand_for_sitio_a():
    # 3 de 7: z² = 3,8414589; den = 1 + z²/7 = 1,5487798; centro = (0,4285714 + z²/14)/den = 0,7029614/1,5487798
    # = 0,4538807; medio = z·√(0,4285714·0,5714286/7 + z²/196)/den = 1,959964·√0,0545847/1,5487798 = 0,2956609.
    lo, hi = R.wilson(3, 7)
    assert lo == pytest.approx(0.4538807 - 0.2956609, abs=2e-7)
    assert hi == pytest.approx(0.4538807 + 0.2956609, abs=2e-7)
    assert R.wilson(0, 0) == (0.0, 1.0)


def test_randomized_and_self_selected_views(data):
    # Sorteo = view − chosen. Totales: view 28 + 23 + 15 + 47 + 36 = 149; chosen 27 + 22 + 13 + 42 + 27 = 131.
    rows = [r for e in data["experiments"].values() for r in R.arm_rows(e)]
    sums = {key: sum(r[key] for r in rows) for key in ("view", "chosen", "random")}
    assert sums == {"view": 149, "chosen": 131, "random": 18}
    assert _row(data, "sitio", "A")["random"] == 6  # 7 − 1
    assert _row(data, "boletin", "mapa")["random"] == 0  # 24 − 24: todo el «ganador» aparente es autoelegido
    out = "\n".join(R.table_mix(data))
    assert "| total | 149 | 131 | 18 | 12,1 % | | |" in out  # 18/149 = 0,1208


def test_srm_sitio_randomized_views_by_hand():
    # A 6, B 3, reparto 1/2: esperado 4,5 cada uno; χ² = 2·1,5²/4,5 = 1; p = erfc(√(1/2)) = 0,317311.
    # Exacta = binomial bilateral: 2·P(X ≤ 3), X ~ B(9, ½) = 2·(1 + 9 + 36 + 84)/512 = 260/512.
    s = R.srm([6, 3], [0.5, 0.5])
    assert s["chi2"] == pytest.approx(1.0)
    assert s["p_chi2"] == pytest.approx(math.erfc(math.sqrt(0.5)), rel=1e-9)
    assert s["p_exact"] == pytest.approx(260 / 512, rel=1e-12)


def test_srm_sitio_all_views_by_hand():
    # A 7, B 29: χ² = 2·11²/18 = 13,4444; p = erfc(√6,7222) = 0,000246.
    # Exacta: 2·Σ_{k≤7} C(36,k)/2³⁶ = 2·(1+36+630+7140+58905+376992+1947792+8347680)/68 719 476 736
    #       = 2·10 739 176/68 719 476 736 = 3,1255e-4.
    s = R.srm([7, 29], [0.5, 0.5])
    assert s["chi2"] == pytest.approx(121 / 9)
    assert s["p_chi2"] == pytest.approx(2.457e-4, rel=1e-3)
    assert s["p_exact"] == pytest.approx(2 * 10_739_176 / 2**36, rel=1e-12)


def test_srm_three_arms_exact_by_hand():
    # Boletín, sorteo 0 / 3 / 2 (n = 5, ⅓ cada una). χ²: esperado 5/3; (25/9 + 16/9 + 1/9)/(5/3) = 2,8; gl 2,
    # p = e^(−1,4) = 0,246597. Exacta: P(x) = coef. multinomial/3⁵; el observado tiene 5!/(0!3!2!) = 10. Tan o menos
    # probables: (5,0,0) ×3 coef 1, (4,1,0) ×6 coef 5, (3,2,0) ×6 coef 10 → (3 + 30 + 60)/243 = 93/243.
    s = R.srm([0, 3, 2], [1 / 3] * 3)
    assert s["chi2"] == pytest.approx(2.8)
    assert s["p_chi2"] == pytest.approx(math.exp(-1.4), rel=1e-9)
    assert s["p_exact"] == pytest.approx(93 / 243, rel=1e-12)


def test_chi2_sf_closed_forms_at_df_1_2_3():
    # gl 1: erfc(√(x/2)); gl 2: e^(−x/2); gl 3: erfc(√(x/2)) + √(2x/π)·e^(−x/2).
    for x in (0.5, 3.0, 7.81):
        assert R.chi2_sf(x, 1) == pytest.approx(math.erfc(math.sqrt(x / 2)), rel=1e-9)
        assert R.chi2_sf(x, 2) == pytest.approx(math.exp(-x / 2), rel=1e-9)
        assert R.chi2_sf(x, 3) == pytest.approx(math.erfc(math.sqrt(x / 2)) + math.sqrt(2 * x / math.pi) * math.exp(-x / 2), rel=1e-9)
    assert R.chi2_sf(7.814728, 3) == pytest.approx(0.05, abs=1e-6)  # valor crítico tabulado


def test_intended_allocation_follows_ab_js_assign():
    assert R.intended_allocation(["A", "B"], None) == [0.5, 0.5]
    # Con ganadora B en 4 versiones: 0,8 a B y 0,2/3 a cada una de las otras.
    got = R.intended_allocation(["A", "B", "C", "D"], "B")
    assert got == pytest.approx([0.2 / 3, 0.8, 0.2 / 3, 0.2 / 3])


def test_consistency_flags_legacy_rows_and_lost_choose_beacons(data):
    mapa = R.consistency("mapa", data["experiments"]["mapa"], legacy_known=True)
    # Legado: 28 visitas en los totales, 2 + 1 + 0 + 2 = 5 en la decisión → 23 de ab_daily.
    assert any(m.startswith("23 de 28 visitas son de ab_daily") for m in mapa)
    # leave 4+4+4+5 = 17 > choose 4+3+4+5 = 16.
    assert any(m.startswith("leave=17 > choose=16") for m in mapa)
    noticias = R.consistency("noticias", data["experiments"]["noticias"], legacy_known=True)
    assert any(m.startswith("leave=12 > choose=11") for m in noticias)  # 4+5+3 contra 3+5+3
    # boletín: leave 6+8+1 = 15 = choose 8+5+2; use 6 = select 3 + detail 3 (en el borde de arriba): nada que decir.
    assert R.consistency("boletin", data["experiments"]["boletin"], legacy_known=True) == []
    assert any("segunda pestaña" in m for m in R.consistency("sitio", data["experiments"]["sitio"], True))


def test_consistency_without_the_same_window_does_not_guess_legacy(data):
    # Con days ≠ decideDays la diferencia totales − decisión mezcla días fuera de la ventana: no se atribuye.
    mapa = R.consistency("mapa", data["experiments"]["mapa"], legacy_known=False)
    assert not any("ab_daily" in m for m in mapa)


@pytest.mark.parametrize(("use", "flag"), [(7, "use=7 > select+detail=6"), (6, None), (3, None), (2, "use=2 < max(select, detail)=3")])
def test_use_bounds_at_their_edges(data, use, flag):
    # boletín «mapa»: select 3, detail 3 → 3 ≤ use ≤ 6.
    exp = copy.deepcopy(data["experiments"]["boletin"])
    exp["totals"]["mapa"]["use"] = use
    got = [m for m in R.consistency("boletin", exp, True) if m.startswith("mapa:")]
    assert got == ([f"mapa: {flag}"] if flag else [])


def test_traffic_and_the_60_day_window(data):
    end = R.snapshot_day(data)
    assert end.isoformat() == "2026-11-21"  # since 2026-09-23 + 59 días
    # Boletín: 24 + 8 + 15 = 47 visitas del 10-11 al 21-11 (11 días) = 4,27/día, 1,424 por versión y día;
    # hacen falta 3·200/60 = 10 por día; 200/1,424 = 140,4 → 141 días.
    b = R.traffic("boletin", data["experiments"]["boletin"], end)
    assert (b["days"], b["tracked"]) == (11, 47)
    assert b["need_per_day"] == pytest.approx(10)
    assert b["days_to_200"] == 141
    assert b["reachable"] is False
    # Sitio: 36 en 10 días; 2·200/60 = 6,667 por día; 200/1,8 = 111,1 → 112.
    s = R.traffic("sitio", data["experiments"]["sitio"], end)
    assert s["per_day"] == pytest.approx(3.6)
    assert s["days_to_200"] == 112
    # Mapa: solo cuentan las 5 visitas de ab_exp (desde el 28-10: 24 días).
    m = R.traffic("mapa", data["experiments"]["mapa"], end)
    assert (m["days"], m["tracked"]) == (24, 5)


def test_traffic_days_stop_at_the_60_day_window(data):
    # Mucho después del inicio, la decisión solo ve los últimos 60 días (since = hoy − 59): 59 días completos sin hoy.
    end = R.dt.date(2027, 3, 1)
    assert R.traffic("sitio", data["experiments"]["sitio"], end)["days"] == 59


def test_traffic_reachable_exactly_at_the_edge(data):
    # 10 visitas por día en 3 versiones es justo 200 por versión en 60 días: alcanza (≥), 9,9 no.
    end = R.snapshot_day(data)
    exp = copy.deepcopy(data["experiments"]["boletin"])
    for views, ok in ((110, True), (109, False)):  # 110/11 = 10,0; 109/11 = 9,909
        for r in exp["decision"]["rows"]:
            r["view"] = 0
        exp["decision"]["rows"][0]["view"] = views
        assert R.traffic("boletin", exp, end)["reachable"] is ok


def test_fisher_by_hand():
    # Días con visitas y merge 13, con visitas sin merge 3, sin visitas con merge 2, sin nada 12 (n = 30).
    # P(X ≥ 13), filas 16, columnas 15: [C(16,13)·C(14,2) + C(16,14)·C(14,1) + C(16,15)·C(14,0)]/C(30,15)
    #   = (560·91 + 120·14 + 16)/155 117 520 = 52 656/155 117 520 = 3,3946e-4.
    assert R.fisher_greater(13, 3, 2, 12) == pytest.approx(52_656 / 155_117_520, rel=1e-12)


def test_internal_share_against_merge_days(data):
    s = R.internal_share(R.daily_views(data), MERGE_DAYS, "2026-10-22", "2026-11-20")
    # Días sin merge con visitas: 23-10 (3), 24-10 (1), 25-10 (6) = 10 visitas → 149 − 10 = 139 en días con merge.
    assert (s["views"], s["on_merge"]) == (149, 139)
    assert (s["traffic_merge"], s["traffic_nomerge"], s["quiet_merge"], s["quiet_nomerge"]) == (13, 3, 2, 12)
    assert s["p_fisher"] == pytest.approx(52_656 / 155_117_520, rel=1e-12)


def test_daily_views_sum_to_the_totals(data):
    # Invariante: lo que trae «daily» suma lo mismo que «totals» de cada experimento.
    by_exp: dict[str, int] = {}
    for day in R.daily_views(data).values():
        for exp, n in day.items():
            by_exp[exp] = by_exp.get(exp, 0) + n
    for name, exp in data["experiments"].items():
        assert by_exp.get(name, 0) == sum(t["view"] for t in exp["totals"].values()), name


def test_rule_alpha_tiny_n_by_hand():
    # n = 5: Wilson(0,5) = [0; 0,4345] y Wilson(5,5) = [0,5655; 1] no se tocan; Wilson(4,5) empieza en 0,3755 y
    # Wilson(1,5) termina en 0,6245, así que solo 0 contra 5 decide. α = 2·(1−p)⁵·p⁵.
    assert R.rule_alpha(5, 2, 0.5) == pytest.approx(2 / 1024, rel=1e-12)
    assert R.rule_alpha(5, 2, 0.3) == pytest.approx(2 * 0.7**5 * 0.3**5, rel=1e-12)
    # Tres versiones: una con 5 y las otras dos con 0: 3·(½)⁵·(½)¹⁰ = 3/32768.
    assert R.rule_alpha(5, 3, 0.5) == pytest.approx(3 / 32768, rel=1e-12)
    # Potencia: P(la mejor saca 5)·P(la otra 0) = 0,9⁵·0,5⁵ = 0,590490/32.
    assert R.rule_power(5, 2, 0.5, 0.9) == pytest.approx(0.9**5 / 32, rel=1e-12)


def test_rule_alpha_at_200_matches_the_non_overlap_approximation():
    # Dos intervalos al 95 % que no se tocan con errores iguales ≈ |z| > 1,96·√2 = 2,772 (Schenker y Gentleman 2001):
    # α ≈ 2·(1 − Φ(2,772)) = 0,0056. Wilson y la binomial discreta la mueven un poco, no un orden de magnitud.
    a = R.rule_alpha(200, 2, 0.15)
    assert 0.004 < a < 0.007
    assert R.rule_alpha(200, 4, 0.15) < a / 10  # con más versiones hay que superar a todas: aún más conservadora


def test_rule_mde_at_200_matches_the_normal_approximation():
    # Normal: δ ≈ (2,772 + 0,8416)·√((0,15·0,85 + 0,30·0,70)/200) = 3,614·0,04108 = 0,148 (con p1 = 0,30).
    d = R.rule_mde(200, 2, 0.15)
    assert d == pytest.approx(0.148, abs=0.01)
    assert R.rule_power(200, 2, 0.15, 0.15 + d) >= 0.8 > R.rule_power(200, 2, 0.15, 0.15 + d - 0.0025)


def test_ztest_sample_size_by_hand():
    # Fleiss sin corrección, 15 % → 20 %: p̄ = 0,175; 1,959964·√(2·0,175·0,825) = 1,053197;
    # 0,841621·√(0,1275 + 0,16) = 0,451270; ((1,053197 + 0,451270)/0,05)² = 905,4 → 906.
    assert R.ztest_n(0.15, 0.20) == 906


def test_peeking_inflates_the_rule_false_positives():
    # Una mirada en n = 200 da α ≈ 0,005; mirar cada 10 visitas hasta 600 debe dar varias veces más (≈ 0,024).
    one = R.peeking_fpr(2, 0.15, [200], sims=3000)
    many = R.peeking_fpr(2, 0.15, list(range(200, 601, 10)), sims=3000)
    assert one == pytest.approx(R.rule_alpha(200, 2, 0.15), abs=3 * math.sqrt(0.0053 / 3000) + 1e-3)
    assert many > 2.5 * max(one, 0.004)
    # Y no más de lo que es: con 200 000 repeticiones (numpy, otra implementación) da 0,0275 ± 0,0004; con 3 000 el
    # error típico es 0,003. Contar más de una vez la misma repetición (sin «break») lo llevaría muy por encima.
    assert many < 0.045


def test_ztest_mde_by_hand():
    # Punto fijo con p0 = 0,15, n = 200: p1 = 0,2622 → 0,2622·0,7378 = 0,19345; + 0,1275 = 0,32095; /200 = 0,0016048;
    # √ = 0,040059; × (1,959964 + 0,841621) = 2,801585 → 0,11223.
    assert R.ztest_mde(200, 0.15) == pytest.approx(0.11223, abs=2e-5)


def test_rule_sample_size_reaches_the_power_and_matches_the_normal_approximation():
    # Normal con |z| > 2,772 (intervalos que no se tocan): ((2,772·√(2·0,175·0,825) + 0,8416·√0,2875)/0,05)² =
    # ((1,4895 + 0,4513)/0,05)² = 1507. Un barrido exacto de n da la primera potencia ≥ 0,8 en n = 1502; la
    # bisección tiene una precisión de 10 visitas.
    n2 = R.rule_n(2, 0.15, 0.20)
    assert R.rule_power(n2, 2, 0.15, 0.20) >= 0.8
    assert 1500 <= n2 <= 1515
    n4 = R.rule_n(4, 0.15, 0.20)
    assert R.rule_power(n4, 4, 0.15, 0.20) >= 0.8 and n4 > n2 + 300


def test_randomized_rate_per_day(data):
    # Sorteo: boletín 0 + 3 + 2 = 5 en 11 días; sitio 6 + 3 = 9 en 10 días. El mapa mezcla ab_daily: no se da.
    end = R.snapshot_day(data)
    assert R.traffic("boletin", data["experiments"]["boletin"], end)["randomized_per_day"] == pytest.approx(5 / 11)
    assert R.traffic("sitio", data["experiments"]["sitio"], end)["randomized_per_day"] == pytest.approx(0.9)
    assert R.traffic("mapa", data["experiments"]["mapa"], end)["randomized_per_day"] is None


def test_bound_issues_flag_impossible_counters(data):
    exp = copy.deepcopy(data["experiments"]["memoria"])
    exp["totals"]["resumen"]["chosen"] = 5  # 5 elegidas en 4 visitas
    exp["decision"]["rows"][1]["use"] = 5  # cuencas: 5 usos en 4 visitas de la decisión
    got = R.consistency("memoria", exp, True)
    assert "resumen: chosen=5 > view=4" in got
    assert "cuencas: use=5 > view=4 en la decisión" in got
    assert R.consistency("memoria", data["experiments"]["memoria"], True) == []


def test_srm_uses_the_winners_allocation(data):
    # Con ganadora «mapa» en el boletín, assign() da 0,8 a «mapa» y 0,1 a cada una de las otras dos.
    d = copy.deepcopy(data)
    d["experiments"]["boletin"]["decision"]["winner"] = "mapa"
    row = next(r for r in R.table_srm(d) if r.startswith("| boletin |"))
    assert "| 80 % / 10 % / 10 % |" in row
    assert "| 33 % / 33 % / 33 % |" in next(r for r in R.table_srm(data) if r.startswith("| boletin |"))


def test_report_attributes_legacy_rows_only_with_the_decision_window(data):
    assert "son de ab_daily" in R.report(data)
    assert "son de ab_daily" not in R.report({**data, "days": 120})


def test_parse_stats_rejects_a_missing_available_flag():
    with pytest.raises(R.Unavailable):
        R.parse_stats('{"experiments": {}}')


def test_report_prints_the_fixture_rows(data):
    out = R.report(data, MERGE_DAYS)
    assert "| A | 7 | 1 | 6 | 7 | 3 | 42,9 % | 15,8 % – 75,0 % |" in out  # sitio A: 3/7
    assert "| mapa | 24 | 24 | 0 | 24 | 6 | 25,0 % | 12,0 % – 44,9 % |" in out  # boletín mapa: 6/24
    assert "139 de 149 visitas (93,3 %)" in out


def test_exit_2_on_unreadable_inputs(tmp_path, capsys):
    page = tmp_path / "desafio.html"
    page.write_text("<!doctype html><title>One moment, please...</title>", encoding="utf-8")
    off = tmp_path / "off.json"
    off.write_text(json.dumps({**json.loads(FIX.read_text(encoding="utf-8")), "available": False}), encoding="utf-8")
    nokey = tmp_path / "nokey.json"
    nokey.write_text('{"error": "Error interno."}', encoding="utf-8")
    for path in (page, off, nokey, tmp_path / "no-existe.json"):
        assert R.main(["--file", str(path)]) == 2, path
    assert R.main(["--url", (tmp_path / "no-existe.json").as_uri()]) == 2
    assert "no se pudo leer" in capsys.readouterr().err
    assert R.main(["--file", str(FIX)]) == 0


def test_exit_2_when_the_api_answers_an_error(monkeypatch):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"error": "Error interno."}')

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    try:
        assert R.main(["--url", f"http://127.0.0.1:{srv.server_port}/api/ab/stats?days=60"]) == 2
    finally:
        srv.shutdown()


@pytest.mark.parametrize(("n", "k"), [(12, 2), (7, 3)])
def test_rule_alpha_and_power_agree_with_the_servers_decide(n, k):
    # Verdad independiente: decide() de functions/_lib/ab.js (JavaScript; decide con rview/ruse, la primera visita
    # sorteada) sobre cada combinación de éxitos con n
    # visitas por versión; la probabilidad de cada combinación con ganadora se suma aquí con la binomial.
    from test_geo_console import ROOT, _need_node

    node = _need_node()
    lib = (ROOT / "functions" / "_lib" / "ab.js").as_uri()
    js = (f"import {{ decide }} from '{lib}'; const n = {n}, k = {k}, vs = [...Array(k).keys()].map(String), out = [];"
          "const rec = (ys) => { if (ys.length === k) { const t = Object.fromEntries(ys.map((y, i) => [vs[i], { rview: n, ruse: y }]));"
          "const w = decide(vs, t, n).winner; if (w !== null) out.push([...ys, Number(w)]); return; }"
          "for (let y = 0; y <= n; y++) rec([...ys, y]); }; rec([]); console.log(JSON.stringify(out));")
    import subprocess

    wins = json.loads(subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert wins  # con n ≥ 7 hay combinaciones extremas que deciden
    for p0, p1 in ((0.3, 0.3), (0.2, 0.6)):
        f0, f1 = R.binom_pmf(n, p0), R.binom_pmf(n, p1)
        alpha = sum(math.prod(f0[y] for y in row[:k]) for row in wins)
        power = sum(f1[row[0]] * math.prod(f0[y] for y in row[1:k]) for row in wins if row[k] == 0)
        assert R.rule_alpha(n, k, p0) == pytest.approx(alpha, rel=1e-9, abs=1e-15)
        assert R.rule_power(n, k, p0, p1) == pytest.approx(power, rel=1e-9, abs=1e-15)
