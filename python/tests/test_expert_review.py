"""Revisión experta: lo que un oceanógrafo del ENFEN/CPC y un auditor WCAG rechazarían de la publicación.

Cada prueba compara con una verdad independiente del código que prueba: la tabla de la Nota Técnica ENFEN 01-2024
transcrita en ``config/threshold-policies``, la página del RONI de NOAA/CPC, valores reales de las copias de
``tests/fixtures/sources`` y la fórmula de contraste de WCAG 2.2 (no los mismos umbrales copiados del código).
"""

from __future__ import annotations

import re
from datetime import date

import pytest
import yaml

from conftest import FIX, ROOT, read
from enso import observatory as obs
from enso import signals as sig
from enso.feeds import cpc

SRC = {s.id: s for s in obs.SOURCES}


# ---------------------------------------------------------------------------
# Tono de la anomalía costera (Niño 1+2): rango neutro del ENFEN, no el ±0,5 de la cuenca
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("v,tone", [
    (-0.71, "cool"), (-0.7, "neutral"), (-0.6, "neutral"), (0.0, "neutral"), (0.5, "neutral"), (0.51, "warm"),
    (-0.5, "neutral"), (None, "na"),
])
def test_coastal_tone_uses_the_enfen_neutral_range(v, tone):
    # −0,6 y −0,5 °C son «Neutra» para el ENFEN y «normal» para el equipo GRD; el ±0,5 simétrico los pintaba de frío.
    assert sig.coastal_tone(v) == tone


def test_coastal_tone_agrees_with_the_icen_policy_on_every_hundredth():
    """Invariante: en toda la recta de −3 a +5 °C, el color «neutro» de la costa coincide con la categoría «Neutra»
    de la tabla oficial (sus ejemplos de borde están en el YAML de la política, no en el código)."""
    doc = yaml.safe_load((ROOT.parent / "config" / "threshold-policies" / "enfen-icen-2024.yaml").read_text(encoding="utf-8"))
    neutral = next(c for c in doc["categories"] if c["label"] == "Neutra")
    lo, hi = min(neutral["examples"]), max(neutral["examples"])  # [−0,7; +0,5], cerrado en los dos extremos
    for i in range(-300, 501):
        v = i / 100
        expected = "neutral" if lo <= v <= hi else "warm" if v > hi else "cool"
        assert sig.coastal_tone(v) == expected, v


def _builder_with_sstoi_until(period: str, today: date) -> obs.Builder:
    data = cpc.parse_nino_monthly(read(FIX / "cpc-sstoi.indices"), name="sstoi").data
    cut = {"anom": {r: [p for p in pts if p["period"] <= period] for r, pts in data["anom"].items()},
           "sst": data.get("sst")}
    b = obs.Builder({"cpc-sstoi": obs.Acquired(source=SRC["cpc-sstoi"], data=cut, ok=True)}, obs.EventLog(), today)
    b.build_series()
    return b


def test_a_real_month_in_the_coastal_neutral_band_is_not_painted_cold():
    """Setiembre de 2024: Niño 1+2 OISST −0,68 °C (copia real de sstoi.indices). El ENFEN la llama neutra y la tabla
    GRD «normal»; la tarjeta no puede decir «frío» al lado de una señal GRD verde."""
    b = _builder_with_sstoi_until("2024-09", date(2024, 10, 20))
    s = b.series["nino12_oisst"]["latest"]
    assert (s["period"], s["value"]) == ("2024-09", -0.68)
    assert s["category"]["tone"] == "neutral"
    coastal = next(x for x in b.grd()["signals"] if x["id"] == "coastal_sst")
    assert coastal["level"] == "ok"  # la misma conclusión por la otra vía (política GRD transcrita)
    # La cuenca sigue con el umbral de NOAA: Niño 3.4 OISST de ese mes es −0,15 °C (copia real), neutro con ±0,5.
    n34 = b.series["nino34_oisst"]["latest"]
    assert (n34["value"], n34["category"]["tone"]) == (-0.15, "neutral")


def test_coastal_tone_rounds_like_the_icen_category():
    # Un valor derivado (p. ej. tras rebasar ERSSTv6) puede llegar como −0,7000000001: ``icen_category`` redondea a
    # 2 decimales y lo llama «Neutra»; el color de la costa no puede decir otra cosa.
    for v in (-0.7000000001, 0.5000000001, -0.70000004):
        assert sig.coastal_tone(v) == "neutral" == sig.icen_category(v)["tone"], v


def test_the_ersstv6_coastal_card_uses_the_coastal_range_too():
    """Niño 1+2 ERSSTv6 de setiembre de 2024 rebasado a 1991–2020: −0,56 °C (copia real de nina1.anom.data). Con el
    ±0,5 de la cuenca salía «frío»; con el rango del ENFEN es neutro. Niño 3.4 ERSSTv6 sigue con ±0,5."""
    acq = {}
    for sid, fname in (("psl-ersst6-nino12", "psl-nina1.anom.data"), ("psl-ersst6-nino34", "psl-nina34.anom.data")):
        pts = cpc.parse_psl_matrix(read(FIX / fname), name=sid).data
        acq[sid] = obs.Acquired(source=SRC[sid], data=[p for p in pts if p["period"] <= "2024-09"], ok=True)
    b = obs.Builder(acq, obs.EventLog(), date(2024, 10, 20))
    b.build_series()
    s = b.series["nino12"]["latest"]
    assert (s["period"], round(s["value"], 2), s["category"]["tone"]) == ("2024-09", -0.56, "neutral")


def _weekly_until(day: str) -> dict:
    data = cpc.parse_weekly(read(FIX / "cpc-wksst9120.for")).data
    cut = {r: [p for p in pts if p["date"] <= day] for r, pts in data.items()}
    b = obs.Builder({"cpc-wksst": obs.Acquired(source=SRC["cpc-wksst"], data=cut, ok=True)}, obs.EventLog(),
                    date.fromisoformat(day))
    return b.weekly()


def test_the_weekly_strip_colours_the_coast_and_the_basin_with_their_own_rule():
    """La franja «Lo más reciente» es lo primero que se ve. Semana del 7 de enero de 2026 (copia real de
    wksst9120.for): Niño 1+2 −0,6 °C, neutra para el ENFEN (antes la pintaba de frío app.js con ±0,5). Semana del
    15 de abril de 2026: Niño 3.4 +0,5 °C, que NOAA cuenta como umbral cálido (≥ +0,5; app.js usaba > 0,5)."""
    w = _weekly_until("2026-01-07")["nino12"]["latest"]
    assert (w["date"], w["anom"], w["tone"]) == ("2026-01-07", -0.6, "neutral")
    w = _weekly_until("2026-04-15")["nino34"]["latest"]
    assert (w["date"], w["anom"], w["tone"]) == ("2026-04-15", 0.5, "warm")
    js = (ROOT.parent / "public" / "assets" / "js" / "app.js").read_text(encoding="utf-8")
    strip = js[js.index("function freshestStrip"):js.index("function", js.index("function freshestStrip") + 10)]
    assert "l.tone" in strip and "0.5" not in strip, "app.js volvió a calcular el tono con su propio umbral"


# ---------------------------------------------------------------------------
# Base climática declarada de cada índice
# ---------------------------------------------------------------------------
def _seasonal(sid: str):
    return cpc.parse_seasonal(read(FIX / SRC[sid].fixture), name=sid.split("-")[1]).data


def test_each_index_declares_the_base_its_institution_uses():
    """NOAA/CPC: el RONI usa una base fija 1991–2020; el ONI, bases de 30 años centradas renovadas cada 5 años
    (por eso su valor de 1950 no es una anomalía frente a 1991–2020). El ICEN sigue el método del ONI
    (Nota Técnica ENFEN 01-2024). Decir «1991–2020» para toda la serie del ONI o del ICEN es falso."""
    acq = {sid: obs.Acquired(source=SRC[sid], data=_seasonal(sid), ok=True) for sid in ("cpc-roni", "cpc-oni")}
    from enso.feeds import peru
    acq["igp-icen"] = obs.Acquired(source=SRC["igp-icen"], data=peru.parse_icen_txt(read(FIX / "igp-icen.txt")).data, ok=True)
    b = obs.Builder(acq, obs.EventLog(), date(2026, 11, 20))
    b.build_series()
    assert b.series["roni"]["climatology"] == "1991–2020"
    # La base vigente de cada uno se deduce de sus datos en ``test_ready_science_ux.py``: el ONI ya usa 1996–2025 desde
    # 2011 (decía 1991–2020 copiado del ICEN); el ICEN del IGP sigue en 1991–2020.
    for k, vigente in (("oni", "1996–2025"), ("icen", "1991–2020")):
        c = b.series[k]["climatology"]
        assert "móvil" in c and "5 años" in c and vigente in c, (k, c)


# ---------------------------------------------------------------------------
# Contraste WCAG 2.2 (1.4.3, AA 4,5:1 para texto normal) de los tokens del sitio
# ---------------------------------------------------------------------------
CSS = (ROOT.parent / "public" / "assets" / "css" / "app.css").read_text(encoding="utf-8")


def _block(selector_re: str) -> dict:
    m = re.search(selector_re + r"\s*\{(.*?)\}", CSS, re.S)
    assert m, selector_re
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", m.group(1)))


def _rgb(v: str, under=(1.0, 1.0, 1.0)) -> tuple:
    v = v.strip()
    if v.startswith("#"):
        return tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5))
    r, g, b, a = (float(x) for x in re.findall(r"[\d.]+", v))
    return tuple(c / 255 * a + u * (1 - a) for c, u in zip((r, g, b), under))


def _contrast(a: tuple, b: tuple) -> float:
    def lum(c):
        lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_hand_computed_wcag_reference_values():
    # Valores de referencia de WCAG: negro sobre blanco 21:1; #767676 sobre blanco ≈ 4,54:1 (el gris AA clásico).
    assert _contrast((0, 0, 0), (1, 1, 1)) == pytest.approx(21.0)
    assert _contrast(_rgb("#767676"), (1, 1, 1)) == pytest.approx(4.54, abs=0.01)


LIGHT = _block(r":root")
DARK = _block(r":root\[data-theme='dark'\]")
DARK_AUTO = _block(r":root:not\(\[data-theme='light'\]\)")

# (texto, fondo del componente, fondo de la página debajo) — .muted, .tag, .chip-warm/.chip-cool y los avisos.
PAIRS = [("fg-3", None, "bg"), ("fg-3", None, "bg-elev"), ("fg-3", None, "bg-sunk"),
         ("warm", "warm-soft", "bg-elev"), ("warm", "warm-soft", "bg"), ("cool", "cool-soft", "bg-elev"),
         ("cool", "cool-soft", "bg"), ("watch", "watch-bg", "bg-elev"), ("na", "na-bg", "bg-elev"),
         ("ok", "ok-bg", "bg-elev"), ("alert", "alert-bg", "bg-elev")]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_tokens_meet_wcag_aa_on_every_background(theme):
    t = LIGHT if theme == "light" else DARK
    bad = []
    for fg, comp, page in PAIRS:
        under = _rgb(t[page])
        bg = _rgb(t[comp], under) if comp else under
        c = _contrast(_rgb(t[fg]), bg)
        if c < 4.5:
            bad.append(f"--{fg} sobre --{comp or page} (sobre --{page}): {c:.2f}:1")
    assert not bad, f"tema {theme}: " + "; ".join(bad)


def _rule(selector: str) -> dict:
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, selector
    return dict((k.strip(), v.strip()) for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+);", m.group(1)))


@pytest.mark.parametrize("selector,fg,bg", [
    (".chip-warm", "warm", "warm-soft"), (".chip-cool", "cool", "cool-soft"), (".tag", "fg-3", "bg-sunk"),
    (".muted", "fg-3", None),
])
def test_the_components_use_the_token_pairs_the_contrast_test_measures(selector, fg, bg):
    """La prueba de contraste mide pares de tokens; esta comprueba que los componentes de verdad usan esos pares
    (si .tag pasa a otro fondo o .chip-cool a otro color, el par medido ya no es el que se ve)."""
    r = _rule(selector)
    assert r.get("color") == f"var(--{fg})", (selector, r)
    if bg:
        assert r.get("background") == f"var(--{bg})", (selector, r)
    pairs = {(f, c or p) for f, c, p in PAIRS}
    assert (fg, bg or "bg") in pairs


def test_the_two_dark_theme_blocks_do_not_drift_apart():
    """El tema oscuro está escrito dos veces (elegido a mano y por preferencia del sistema). Si un token cambia en
    uno solo, quien usa el modo oscuro del sistema ve otros colores que quien lo elige en el botón."""
    shared = set(DARK) & set(DARK_AUTO)
    assert shared >= {"warm", "warm-soft", "cool", "cool-soft", "fg-3", "bg", "bg-elev"}
    assert {k: DARK[k] for k in shared} == {k: DARK_AUTO[k] for k in shared}
    assert set(DARK) - {"color-scheme"} <= set(DARK_AUTO) | {"color-scheme"}


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_warm_and_cool_tints_have_the_same_weight(theme):
    """Una escala divergente no debe pesar más de un lado (Brewer; Moreland 2009). El peso se mide frente al fondo,
    no con el alfa: por luminosidad (ΔL*) y por diferencia total (CIEDE2000). En claro el azul subió a 0,18 y las dos
    medidas mejoran; en oscuro se contradicen y se queda el alfa igual. La medición está en
    ``test_ready_science_ux.py``; aquí se exige que ningún lado pese más de 1,6 veces el otro por ninguna medida."""
    from test_ready_science_ux import _imbalance

    t = LIGHT if theme == "light" else DARK
    for page in ("bg", "bg-elev"):
        r_l, r_e = _imbalance(t, page)
        assert max(r_l, r_e) <= 1.6, (theme, page, round(r_l, 2), round(r_e, 2))
