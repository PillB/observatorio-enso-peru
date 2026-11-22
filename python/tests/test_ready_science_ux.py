"""Antes del despliegue: revisión científica y de accesibilidad de las decisiones del PR #133.

Cada prueba compara con una verdad que no sale del código que prueba:

- la base vigente de cada índice se **deduce de sus propios datos** (la columna TOTAL del ONI de CPC y la TSM total de
  Niño 1+2 de ERSSTv5 frente al ICEN del IGP), no del texto que el código publica;
- la sinopsis de NOAA se compara con el texto transcrito a mano de la copia real;
- los bordes de 0,05 y 0,15 se calculan a mano (en decimal exacto) y se prueban justo debajo, en el borde y encima;
- el daltonismo se simula con las matrices publicadas de Machado, Oliveira y Fernandes (2009, severidad 1,0) y la
  luminosidad con CIELAB (CIE 15:2004), con valores de referencia conocidos (#777777 → L* ≈ 50).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from conftest import FIX, ROOT, read
from enso import observatory as obs
from enso.feeds import cpc, peru

SRC = {s.id: s for s in obs.SOURCES}


# ---------------------------------------------------------------------------
# Bases de climatología: deducidas de los datos de cada institución
# ---------------------------------------------------------------------------
def _oni_rows() -> list[tuple[str, int, float, float]]:
    out = []
    for line in read(FIX / "cpc-oni.txt").splitlines()[1:]:
        p = line.split()
        if len(p) == 4:
            out.append((p[0], int(p[1]), float(p[2]), float(p[3])))
    return out


def _oni_current_base(rows) -> tuple[int, int]:
    """La ventana de 30 años (terminada en año múltiplo de 5) cuya media de TOTAL es la climatología implícita
    (TOTAL − ANOM) de los años recientes. Método de CPC (página «ONI change»): anomalía = total − media de la base."""
    tot = {(s, y): t for s, y, t, _ in rows}
    implied = {(s, y): round(t - a, 2) for s, y, t, a in rows}
    last_full = max(y for s, y, *_ in rows if s == "NDJ")
    candidates = [(e - 29, e) for e in range(1990, last_full + 1, 5)]

    def err(base):
        seasons = {s for s, *_ in rows}
        clim = {s: sum(tot[(s, y)] for y in range(base[0], base[1] + 1)) / 30 for s in seasons}
        recent = [(s, y) for (s, y) in implied if y >= last_full - 4]
        return max(abs(implied[k] - clim[k[0]]) for k in recent)

    return min(candidates, key=err)


def test_the_oni_rotated_to_1996_2025_and_the_site_says_so():
    """CPC agregó la base 1996–2025 en 2026: la climatología implícita del JFM de 2011 a 2026 es 26,78 °C (la media
    1996–2025 de TOTAL es 26,77; la de 1991–2020, 26,90). El sitio decía «la vigente, 1991–2020», copiado del ICEN."""
    rows = _oni_rows()
    jfm = {y: round(t - a, 2) for s, y, t, a in rows if s == "JFM"}
    assert jfm[2010] == 26.90 and jfm[2011] == jfm[2026] == 26.78  # cambio de base entre 2010 y 2011 (copia real)
    base = _oni_current_base(rows)
    assert base == (1996, 2025)
    acq = {"cpc-oni": obs.Acquired(source=SRC["cpc-oni"], data=cpc.parse_seasonal(read(FIX / "cpc-oni.txt"), name="oni").data,
                                   ok=True)}
    b = obs.Builder(acq, obs.EventLog(), date(2026, 11, 20))
    b.build_series()
    clim = b.series["oni"]["climatology"]
    assert f"{base[0]}–{base[1]}" in clim and "móvil" in clim, clim
    assert "1991–2020" not in clim


def _ersst5_nino12_totals() -> dict:
    lines = (line.split() for line in read(FIX / "cpc-ersst5.nino.mth.91-20.ascii").splitlines())
    return {(int(p[0]), int(p[1])): float(p[2]) for p in lines if p and p[0].isdigit()}


def _trio(y: int, m: int) -> list[tuple[int, int]]:
    """Los meses anterior, propio y siguiente (año, mes)."""
    return [(k // 12, k % 12 + 1) for k in (y * 12 + m - 2, y * 12 + m - 1, y * 12 + m)]


def _recent_icen(tot: dict) -> list[tuple[tuple[int, int], float]]:
    """ICEN oficial del IGP de 2021 en adelante, en los meses con los tres totales de ERSSTv5."""
    icen = {(int(p["period"][:4]), int(p["period"][5:7])): p["value"]
            for p in peru.parse_icen_txt(read(FIX / "igp-icen.txt")).data if p["value"] is not None}
    return [(k, v) for k, v in icen.items() if k[0] >= 2021 and all(t in tot for t in _trio(*k))]


def _icen_fit(base: tuple[int, int]) -> float:
    """Error máximo 2021–2026 al rehacer el ICEN (media de 3 meses centrada de Niño 1+2 ERSSTv5) con esa base."""
    tot = _ersst5_nino12_totals()
    clim = {m: sum(tot[(y, m)] for y in range(base[0], base[1] + 1)) / 30 for m in range(1, 13)}
    errs = [abs(round(sum(tot[t] - clim[t[1]] for t in _trio(*k)) / 3, 2) - v) for k, v in _recent_icen(tot)]
    assert len(errs) >= 60
    return max(errs)


def test_the_icen_still_uses_1991_2020_and_the_site_says_so():
    """El ICEN del IGP cuadra con ERSSTv5 y 1991–2020 (error ≤ 0,08 °C en 2021–2026) y no con 1996–2025 (hasta
    0,12): el ENFEN aún no rotó. Si rota, esta prueba falla con la copia nueva del archivo del IGP."""
    fit91, fit96 = _icen_fit((1991, 2020)), _icen_fit((1996, 2025))
    assert fit91 <= 0.08 < fit96, (fit91, fit96)
    acq = {"igp-icen": obs.Acquired(source=SRC["igp-icen"], data=peru.parse_icen_txt(read(FIX / "igp-icen.txt")).data,
                                    ok=True)}
    b = obs.Builder(acq, obs.EventLog(), date(2026, 11, 20))
    b.build_series()
    assert "1991–2020" in b.series["icen"]["climatology"]


# ---------------------------------------------------------------------------
# Sinopsis de NOAA: todas las copias reales, y lo que pasa si CPC cambia la negrita
# ---------------------------------------------------------------------------
NOV26 = ("El Niño continues to strengthen, with a strong-to-very strong El Niño likely through January-March 2027 "
         "(remaining greater than an 83% chance).")  # transcrita a mano de cpc-ensodisc.html


def _copies() -> list[Path]:
    return [FIX / "cpc-ensodisc.html", *sorted((FIX / "history").glob("cpc-ensodisc-*.html"))]


@pytest.mark.parametrize("path", _copies(), ids=lambda p: p.name)
def test_every_archived_discussion_has_a_bold_synopsis_that_stops_at_its_paragraph(path):
    """Las 9 copias (2016–2026) traen la sinopsis en negrita: se lee sin aviso, y la oración que abre el párrafo
    siguiente no entra en ella (era el defecto: «Síntesis de NOAA» seguía con la discusión)."""
    doc = read(path)
    p = cpc.parse_enso_discussion(doc)
    syn = p.data["synopsis"]
    assert 60 <= len(syn) <= 300 and syn.rstrip().endswith((".", ")")), syn
    assert not [w for w in p.warnings if "sinopsis" in w]
    after = re.sub(r"\s+", " ", cpc.html_to_text(doc.split("Synopsis", 1)[1].split("</p>", 1)[1]))[:200]
    first = next(s for s in re.split(r"(?<=[.!?]) ", after.strip()) if len(s) > 20)
    assert first[:40] not in syn


def test_the_synopsis_survives_cpc_switching_strong_to_b():
    """``<b>`` es el mismo énfasis. Con la expresión que solo aceptaba ``<strong>``, la copia de noviembre con ``<b>``
    devolvía 286 caracteres: la sinopsis y el primer párrafo de la discusión."""
    doc = read(FIX / "cpc-ensodisc.html").replace("<strong>", "<b>").replace("</strong>", "</b>")
    p = cpc.parse_enso_discussion(doc)
    assert p.data["synopsis"] == NOV26
    assert not [w for w in p.warnings if "sinopsis" in w]


def test_without_bold_the_synopsis_stops_at_its_paragraph_and_says_so():
    """Sin negrita, el límite es el fin del párrafo (``</p>``) y la corrida avisa: el cambio no queda callado."""
    doc = re.sub(r"</?strong>", "", read(FIX / "cpc-ensodisc.html"))
    p = cpc.parse_enso_discussion(doc)
    assert p.data["synopsis"] == NOV26
    assert any("ya no viene en negrita" in w for w in p.warnings), p.warnings


@pytest.mark.parametrize("path", _copies(), ids=lambda p: p.name)
def test_both_markup_changes_keep_the_same_synopsis_in_every_layout(path):
    """Las dos pruebas de arriba usan solo la copia de noviembre; aquí, las 9 maquetas (2016–2026). Con ``<b>`` y sin
    negrita sale la misma sinopsis que con ``<strong>`` (que la prueba del archivo ya acota a su párrafo)."""
    doc = read(path)
    want = cpc.parse_enso_discussion(doc).data["synopsis"]
    as_b = cpc.parse_enso_discussion(doc.replace("<strong>", "<b>").replace("</strong>", "</b>"))
    plain = cpc.parse_enso_discussion(re.sub(r"</?strong>", "", doc))
    assert as_b.data["synopsis"] == want and plain.data["synopsis"] == want
    assert any("ya no viene en negrita" in w for w in plain.warnings)


# ---------------------------------------------------------------------------
# Bordes calculados a mano (AGENT.md §3: se compara después de redondear)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("igp,expected", [
    (4.44, "undetermined"),  # |0,25 − 0,29| = 0,04 < 0,05
    (4.45, "IGP"),           # |0,24 − 0,29| = 0,05: no es «< 0,05»; el IGP queda más cerca (en flotante 0,0499999…)
    (4.46, "IGP"),           # |0,23 − 0,29| = 0,06
])
def test_icen_mismatch_equidistance_edge(igp, expected):
    from test_cross_checks import _builder, _informe

    inf = _informe()  # informe N° 20: tabla +4,98, temporal de Oct-26 +4,69 (copia real)
    assert (inf["lastOfficial"]["icen"], inf["icenProvisional"]["icen"]) == (4.98, 4.69)
    out = _builder(icen_sep=igp).informe(inf)
    assert out["icenMismatch"]["consistentWith"] == expected


@pytest.mark.parametrize("ref,expected", [
    (0.64, "traditional-monthly"),  # 0,14
    (0.65, "traditional-monthly"),  # 0,15 exacto: cuenta como cerca (≤ 0,15); en flotante 0,15000000000000002
    (0.66, "other"),                # 0,16
])
def test_values_basis_tolerance_edge(ref, expected):
    b = obs.Builder({}, obs.EventLog(), date(2026, 11, 20))
    sstoi = {"anom": {"nino34": [{"period": "2026-10", "value": ref}]}}
    b.data = lambda sid: {"cpc-wksst": {}, "cpc-sstoi": sstoi}.get(sid)
    assert b.ensodisc_basis({"nino34": 0.5}, "2026-11-12") == expected


# ---------------------------------------------------------------------------
# El gráfico semanal muestra el mismo rango neutro que colorea la tarjeta
# ---------------------------------------------------------------------------
def test_the_weekly_coastal_chart_draws_the_enfen_neutral_band():
    """La tarjeta semanal de Niño 1+2 se colorea con el rango neutro del ENFEN; el gráfico de la misma página
    rellenaba por signo sin mostrar ese rango, y una semana a −0,6 °C se veía azul junto a un valor gris. Los límites
    se toman de la tabla transcrita de la Nota Técnica (YAML), no del código."""
    doc = yaml.safe_load((ROOT.parent / "config" / "threshold-policies" / "enfen-icen-2024.yaml").read_text(encoding="utf-8"))
    neutral = next(c for c in doc["categories"] if c["label"] == "Neutra")
    lo, hi = min(neutral["examples"]), max(neutral["examples"])
    js = (ROOT.parent / "public" / "assets" / "js" / "app.js").read_text(encoding="utf-8")
    call = next(line for line in js.splitlines() if "mountChart($('#ch-n12w')" in line)
    m = re.search(r"refLines:\s*(\w+)", call)
    assert m, call
    decl = re.search(r"const " + m.group(1) + r" = \[(.*?)\];", js, re.S).group(1)
    values = sorted(float(v) for v in re.findall(r"v:\s*(-?[\d.]+)", decl))
    assert values == [lo, hi]


# ---------------------------------------------------------------------------
# Color: luminosidad CIELAB y simulación de daltonismo de los tokens reales
# ---------------------------------------------------------------------------
CSS = (ROOT.parent / "public" / "assets" / "css" / "app.css").read_text(encoding="utf-8")
MACHADO = {  # Machado, Oliveira y Fernandes (2009), tabla de severidad 1,0, sobre RGB lineal
    "deutan": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "protan": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "tritan": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _enc(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _rgb(v: str, under=(1.0, 1.0, 1.0)) -> tuple:
    v = v.strip()
    if v.startswith("#"):
        return tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5))
    r, g, b, a = (float(x) for x in re.findall(r"[\d.]+", v))
    return tuple(c / 255 * a + u * (1 - a) for c, u in zip((r, g, b), under))


def _lab(rgb: tuple) -> tuple:
    r, g, b = (_lin(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _de(a: tuple, b: tuple) -> float:
    return sum((p - q) ** 2 for p, q in zip(_lab(a), _lab(b))) ** 0.5


def _sim(rgb: tuple, kind: str) -> tuple:
    lin = [_lin(c) for c in rgb]
    return tuple(_enc(min(1.0, max(0.0, sum(m * c for m, c in zip(row, lin))))) for row in MACHADO[kind])


def delta_lstar(tint: str, page: str) -> float:
    """ΔL* (CIELAB) de un tinte rgba compuesto sobre el fondo de la página: el «peso» visual de un relleno."""
    under = _rgb(page)
    return abs(_lab(_rgb(tint, under))[0] - _lab(under)[0])


def _block(selector_re: str) -> dict:
    m = re.search(selector_re + r"\s*\{(.*?)\}", CSS, re.S)
    assert m, selector_re
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", m.group(1)))


THEMES = {"light": _block(r":root"), "dark": _block(r":root\[data-theme='dark'\]"),
          "dark-auto": _block(r":root:not\(\[data-theme='light'\]\)")}


def test_colour_reference_values():
    # #777777: L* = 50,03 (valor de tabla CIELAB); blanco 100; negro 0. Machado deutan de rojo puro = primera
    # columna de la matriz (0,367; 0,280; −0,012 → 0), codificada en sRGB.
    assert _lab(_rgb("#777777"))[0] == pytest.approx(50.03, abs=0.05)
    assert _lab((1, 1, 1))[0] == pytest.approx(100, abs=0.01) and _lab((0, 0, 0))[0] == pytest.approx(0, abs=0.01)
    assert _sim((1, 0, 0), "deutan") == pytest.approx((_enc(0.367322), _enc(0.280085), 0.0))


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("kind", ["normal", *sorted(MACHADO)])
def test_warm_and_cool_stay_distinct_for_colour_blind_readers(theme, kind):
    """Rojo y azul (RdBu de Brewer) son la escala divergente segura para daltonismo: tras simular deuteranopía,
    protanopía y tritanopía, el texto cálido y el frío siguen a ΔE ≥ 40 (medido: ≥ 59) y los tintes a ΔE ≥ 5
    (medido: ≥ 7,6; ~2,3 es apenas perceptible), sobre la tarjeta (bg-elev) y la página (bg)."""
    t = THEMES[theme]
    sim = (lambda c: c) if kind == "normal" else (lambda c: _sim(c, kind))
    for page in ("bg", "bg-elev"):
        under = _rgb(t[page])
        assert _de(sim(_rgb(t["warm"])), sim(_rgb(t["cool"]))) >= 40, (theme, kind)
        assert _de(sim(_rgb(t["warm-soft"], under)), sim(_rgb(t["cool-soft"], under))) >= 5, (theme, kind, page)


def _de00(lab1: tuple, lab2: tuple) -> float:
    """CIEDE2000 (CIE 142-2001; fórmula y datos de prueba de Sharma, Wu y Dalal, 2005)."""
    import math

    (l1, a1, b1), (l2, a2, b2) = lab1, lab2
    cb = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(cb ** 7 / (cb ** 7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1, c2 = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1, h2 = (math.degrees(math.atan2(b, a)) % 360 for a, b in ((a1p, b1), (a2p, b2)))
    dh = 0.0 if c1 * c2 == 0 else (h2 - h1) - 360 * ((h2 - h1) > 180) + 360 * ((h2 - h1) < -180)
    big_dh = 2 * math.sqrt(c1 * c2) * math.sin(math.radians(dh / 2))
    lb, cbp = (l1 + l2) / 2, (c1 + c2) / 2
    hb = h1 + h2 if c1 * c2 == 0 else ((h1 + h2) / 2 if abs(h1 - h2) <= 180 else (h1 + h2 + 360) / 2)
    tt = (1 - 0.17 * math.cos(math.radians(hb - 30)) + 0.24 * math.cos(math.radians(2 * hb))
          + 0.32 * math.cos(math.radians(3 * hb + 6)) - 0.20 * math.cos(math.radians(4 * hb - 63)))
    sl = 1 + 0.015 * (lb - 50) ** 2 / math.sqrt(20 + (lb - 50) ** 2)
    sc, sh = 1 + 0.045 * cbp, 1 + 0.015 * cbp * tt
    rt = -2 * math.sqrt(cbp ** 7 / (cbp ** 7 + 25 ** 7)) * math.sin(math.radians(60 * math.exp(-((hb - 275) / 25) ** 2)))
    x, y = (c2 - c1) / sc, big_dh / sh
    return math.sqrt(((l2 - l1) / sl) ** 2 + x ** 2 + y ** 2 + rt * x * y)


@pytest.mark.parametrize("lab1,lab2,expected", [  # pares 1, 7 y 17 de la tabla de Sharma et al. (2005)
    ((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
    ((50, 0, 0), (50, -1, 2), 2.3669),
    ((50, 2.5, 0), (73, 25, -18), 27.1492),
])
def test_ciede2000_reference_pairs(lab1, lab2, expected):
    assert _de00(lab1, lab2) == pytest.approx(expected, abs=1e-4)


def _imbalance(t: dict, page: str) -> tuple[float, float]:
    """Cuánto pesa más un tinte que el otro (cociente mayor/menor), según ΔL* y según ΔE00 frente al fondo."""
    under = _rgb(t[page])
    lw, lc = delta_lstar(t["warm-soft"], t[page]), delta_lstar(t["cool-soft"], t[page])
    ew, ec = (_de00(_lab(under), _lab(_rgb(t[k], under))) for k in ("warm-soft", "cool-soft"))
    return max(lw, lc) / min(lw, lc), max(ew, ec) / min(ew, ec)


def test_light_tints_weigh_the_same_on_both_sides():
    """Tema claro: con el mismo alfa (0,16) el rojo pesaba más por las dos medidas (ΔL* 7,0 frente a 6,2; ΔE00 9,4
    frente a 6,5); con el azul en 0,18 la paridad de ΔL* queda en ≤ 0,5 y ΔE00 también mejora."""
    t = THEMES["light"]
    for page in ("bg", "bg-elev"):
        w, c = delta_lstar(t["warm-soft"], t[page]), delta_lstar(t["cool-soft"], t[page])
        assert abs(w - c) <= 0.5, (page, round(w, 2), round(c, 2))


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_no_tint_is_much_heavier_by_either_measure(theme):
    """En oscuro las dos medidas se contradicen: por ΔL* pesa más el azul (13,3 frente a 11,1) y por ΔE00 el rojo
    (14,4 frente a 9,5), porque el salmón oscuro tiene mucho más croma. Bajar el azul a 0,15 igualaba ΔL* pero llevaba
    el desequilibrio de ΔE00 de 1,59 a 1,91: ningún alfa arregla los dos, así que se exige que el peor de los dos
    cocientes no pase del que da el alfa igual (1,59). Equilibrar de verdad pide cambiar el croma de los tonos base."""
    t = THEMES[theme]
    for page in ("bg", "bg-elev"):
        r_l, r_e = _imbalance(t, page)
        assert max(r_l, r_e) <= 1.6, (theme, page, round(r_l, 2), round(r_e, 2))
