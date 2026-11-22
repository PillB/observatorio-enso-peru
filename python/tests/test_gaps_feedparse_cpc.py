"""Huecos de cobertura en ``feedparse.truncated`` (CSV de FIRMS) y en los parsers de CPC.

Cada prueba cierra una mutación que sobrevivía a toda la suite:

- ``test_firms_csv_without_final_newline_is_not_truncated``: en ``_csv_unfinished`` la comparación de comas
  ``<`` pasa a ``<=``. La copia real de FIRMS sin el salto de línea final tiene una última fila completa (12 comas,
  igual que la cabecera): no está cortada, pero con ``<=`` se declaraba cortada.
- ``test_firms_csv_short_last_row_ending_in_newline_is_not_truncated``: se quita la guarda
  ``not text.endswith("\\n")``. Una fila corta que sí termina en salto de línea llegó entera (la regla documentada
  exige las dos condiciones); sin la guarda se declaraba cortada.
- ``test_firms_csv_cut_mid_row_is_truncated``: el caso positivo de la misma regla, para que las dos pruebas
  anteriores no pasen con una función que siempre devuelve "".
- ``test_nino_anom_column_before_any_region_is_ignored``: en ``_nino_row`` se quita ``and region`` de la rama
  ANOM. Una columna ANOM sin región a su izquierda creaba la serie ``None`` en las anomalías.
- ``test_nino_short_row_is_skipped``: se quita el retorno temprano ``len(parts) != len(cols)``. Una fila final
  incompleta (solo Niño 1+2) añadía un mes a Niño 1+2 y no a las demás regiones.
- ``test_ensodisc_long_synopsis_is_cut_to_first_sentence``: el tope de 400 caracteres de ``_synopsis`` pasa a 4000.
  La discusión archivada de septiembre de 2016 tiene una sinopsis de 3255 caracteres; debe quedar su primera oración.
- ``test_firms_csv_cut_row_is_compared_with_header_not_previous_row`` (verificación): en ``_csv_unfinished`` la
  referencia ``lines[0]`` (cabecera) pasa a ``lines[-2]`` (fila anterior). Con dos filas cortas seguidas, la última
  (sin salto final) tiene tantas comas como la anterior pero menos que la cabecera: está cortada.
- ``test_synopsis_cap_is_exactly_400_characters`` (verificación): el tope de ``_synopsis`` pasa de 400 a 100 (o a
  ``>=``). Una sinopsis de exactamente 400 caracteres se conserva entera; con 401 queda solo la primera oración.
"""

from pathlib import Path

import pytest

from enso import feedparse as F
from enso.feeds import cpc

FIX = Path(__file__).parent / "fixtures" / "sources"
FIRMS = (FIX / "news-firms-focos.csv").read_bytes()
ERSST5 = (FIX / "cpc-ersst5.nino.mth.91-20.ascii").read_text()
CUT_MSG = "la última fila del CSV está incompleta: llegó cortado"


def test_firms_csv_without_final_newline_is_not_truncated():
    # La copia real termina en "...,291.28,7.34,D\n": la última fila tiene 12 comas, igual que la cabecera
    # (13 columnas: latitude ... daynight). Sin el "\n" final sigue completa: 12 < 12 es falso → "".
    body = FIRMS.rstrip(b"\n")
    last = body.split(b"\n")[-1]
    assert last.count(b",") == body.split(b"\n")[0].count(b",") == 12
    assert F.truncated(body, "firms") == ""


def test_firms_csv_short_last_row_ending_in_newline_is_not_truncated():
    # Última fila con 3 comas (< 12) pero que termina en "\n": el texto llegó hasta el final, no está cortado.
    body = FIRMS + b"-5.1,-78.2,330.1,0.5\n"
    assert F.truncated(body, "firms") == ""


def test_firms_csv_cut_mid_row_is_truncated():
    # La misma fila corta (3 comas < 12) sin salto de línea final: es un corte a mitad de fila.
    body = FIRMS + b"-5.1,-78.2,330.1,0.5"
    assert F.truncated(body, "firms") == CUT_MSG


def test_nino_anom_column_before_any_region_is_ignored():
    # Se antepone a cada fila una columna «ANOM» (valor 9.99) sin región a su izquierda: no pertenece a ninguna.
    lines = ERSST5.splitlines()
    text = "\n".join(
        l.replace("MON", "MON  ANOM", 1) if l.split()[:1] == ["YR"] else
        " ".join(l.split()[:2] + ["9.99"] + l.split()[2:]) for l in lines if l.strip())
    parsed = cpc.parse_nino_monthly(text, name="ersst5")
    assert set(parsed.data["anom"]) == {"nino12", "nino3", "nino4", "nino34"}
    # Primera fila real: 1950-01 Niño 1+2 ANOM -1.55 (no 9.99).
    assert parsed.data["anom"]["nino12"][0] == {"period": "1950-01", "value": -1.55}


def test_nino_short_row_is_skipped():
    # Última fila real: 2026 6 (Niño 1+2 ANOM 2.82). Se añade «2026 7 26.10 2.50» (solo Niño 1+2): fila incompleta,
    # 4 de 10 columnas. Debe ignorarse: la serie Niño 1+2 sigue terminando en 2026-06 con 2.82, como las demás.
    text = ERSST5.rstrip("\n") + "\n2026   7   26.10    2.50\n"
    anom = cpc.parse_nino_monthly(text, name="ersst5").data["anom"]
    assert anom["nino12"][-1] == {"period": "2026-06", "value": 2.82}
    # 1950-01 .. 2026-06 = 76 años × 12 + 6 = 918 meses en cada región.
    assert {k: len(v) for k, v in anom.items()} == {"nino12": 918, "nino3": 918, "nino4": 918, "nino34": 918}


def test_ensodisc_long_synopsis_is_cut_to_first_sentence():
    # Valor publicado (CPC, 8 sep 2016): la sinopsis completa pasa de 400 caracteres (3255); se conserva la
    # primera oración tal como la publica el boletín.
    doc = (FIX / "history" / "cpc-ensodisc-20160910135517.html").read_text(encoding="utf-8", errors="replace")
    syn = cpc.parse_enso_discussion(doc).data["synopsis"]
    assert syn == ("ENSO-Neutral conditions are slightly favored (between 55-60%) during the upcoming Northern "
                   "Hemisphere fall and winter 2016-17.")


def test_firms_csv_cut_row_is_compared_with_header_not_previous_row():
    # Cabecera real: 12 comas. Se añaden dos filas de 3 comas; la segunda sin "\n" final. Regla documentada: la
    # última fila tiene menos columnas (3 < 12, contra la cabecera) y no acaba en salto de línea → cortada.
    # Comparar con la fila anterior daría 3 < 3 → falso y se publicaría el CSV cortado.
    body = FIRMS + b"-5.1,-78.2,330.1,0.5\n-5.2,-78.3,331.0,0.6"
    assert F.truncated(body, "firms") == CUT_MSG


def test_synopsis_cap_is_exactly_400_characters():
    # Sinopsis sintética de dos oraciones: «A»×99 + «.» = 100 caracteres, un espacio, y «B»×n + «.».
    # Con n = 298: 100 + 1 + 299 = 400 caracteres → no pasa de 400 → se conserva entera.
    # Con n = 299: 100 + 1 + 300 = 401 → pasa de 400 → queda solo la primera oración (100 caracteres).
    first = "A" * 99 + "."
    whole_400 = first + " " + "B" * 298 + "."
    whole_401 = first + " " + "B" * 299 + "."
    assert (len(whole_400), len(whole_401)) == (400, 401)
    assert cpc._synopsis(f"Status: El Niño Advisory Synopsis: {whole_400} [Fig. 1]") == whole_400
    assert cpc._synopsis(f"Status: El Niño Advisory Synopsis: {whole_401} [Fig. 1]") == first


@pytest.mark.parametrize("name, published", [
    # La oración en negrita tras «Synopsis:» de cada discusión, copiada de la página publicada.
    ("history/cpc-ensodisc-20220601152511.html",
     "Though La Niña is favored to continue, the odds for La Niña decrease into the late Northern Hemisphere summer "
     "(58% chance in August-October 2022) before slightly increasing through the Northern Hemisphere fall and early "
     "winter 2022 (61% chance)."),
    ("cpc-ensodisc.html",
     "El Niño continues to strengthen, with a strong-to-very strong El Niño likely through January-March 2027 "
     "(remaining greater than an 83% chance)."),
])
def test_short_synopsis_stops_at_its_bold_block_not_at_the_first_figure(name, published):
    """Brecha: una sinopsis corta (menos de 400 caracteres) seguía con el primer párrafo de la discusión hasta «[Fig»
    y el sitio lo mostraba como «Síntesis de NOAA». Falla si la sinopsis se vuelve a leer del texto plano."""
    doc = (FIX / name).read_text(encoding="utf-8", errors="replace")
    assert cpc.parse_enso_discussion(doc).data["synopsis"] == published
