"""Segunda ronda de la memoria de desastres: lectores del COEN, decretos, prensa, GLOF, llamamientos e inventarios
(``enso.historico.cosecha``), la unión con el catálogo y los indicadores de prevención (``enso.historico.enlace``)."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from conftest import FIX
from enso.historico import cosecha as C, enlace
from enso.historico.enso import EnsoCalendar
from enso.historico.registro import make
from enso.historico.territorio import territory
from tools import build_historico as B

HF = Path(__file__).parent / "fixtures" / "historico"


@pytest.fixture(scope="module")
def cal() -> EnsoCalendar:
    return EnsoCalendar.from_files(FIX / "igp-icen.txt", FIX / "cpc-oni.txt")


@pytest.fixture(scope="module")
def T():
    return territory()


# ---------------------------------------------------------------------------
# COEN
# ---------------------------------------------------------------------------
YAULI_URL = ("https://portal.indeci.gob.pe/emergencias/reporte-complementario-n-10158-2-8-2026-coen-indeci-1700-horas-"
             "reporte-n-1-helada-en-el-distrito-de-yauli-huancavelica/")
YAULI_TITLE = ("REPORTE COMPLEMENTARIO N° 10619 - 17/8/2026 / COEN - INDECI / 17:00 HORAS (Reporte N° 5) HELADA EN EL "
               "DISTRITO DE YAULI - HUANCAVELICA")


def test_coen_title_and_first_report():
    assert C.coen_title(YAULI_TITLE) == {"peligro": "HELADA", "nivel": "distrito", "lugares": ["YAULI"],
                                         "provincia": "", "departamento": "HUANCAVELICA"}
    t = C.coen_title("REPORTE PRELIMINAR N° 1084 - 27/1/2026 / COEN - INDECI / 19:50 HORAS (Reporte N° 1) VIENTOS "
                     "FUERTES EN LOS DISTRITOS DE CONSTITUCIÓN Y PUERTO BERMÚDEZ - PASCO")
    assert (t["peligro"], t["lugares"], t["departamento"]) == ("VIENTOS FUERTES", ["CONSTITUCIÓN", "PUERTO BERMÚDEZ"], "PASCO")
    assert C.coen_first_report(YAULI_URL, YAULI_TITLE) == {"numero": "10158", "tipo": "complementario",
                                                           "fecha": "2026-08-02", "primero": True}
    # Un año mal escrito en la dirección («20025») no se lee como 2002: vale la fecha del título.
    typo = ("https://portal.indeci.gob.pe/emergencias/reporte-complementario-n-1661-8-2-20025-coen-indeci-1220-horas-"
            "reporte-n-1-vientos-fuertes-en-el-distrito-de-el-alto-piura/")
    got = C.coen_first_report(typo, "REPORTE COMPLEMENTARIO N° 1720 - 10/2/2025 / COEN - INDECI / 10:00 HORAS")
    assert (got["fecha"], got["primero"]) == ("2025-02-10", False)
    future = typo.replace("8-2-20025", "8-7-2099")
    assert C.coen_first_report(future, "") is None
    assert C.coen_first_report(future, "REPORTE N° 5789 - 8/7/2022 / COEN")["fecha"] == "2022-07-08"


def test_coen_pdf_sections():
    d = C.coen_pdf((HF / "coen-helada-yauli-2026.txt").read_text(encoding="utf-8"))
    assert d["fecha"] == "2026-07-01" and d["sinpad"] == "266584"
    assert d["descripcion"].startswith("Se registró helada que ocasionó afectación a la salud")
    assert d["ubicacion"] == [("HUANCAVELICA", "HUANCAVELICA", "YAULI")]
    assert d["danos"] == {"total": {"Afectados": 190.0}, "yauli": {"Afectados": 190.0}}
    # Cuadro con vivienda (inhabitable + afectada) y la mención del decreto de emergencia vigente.
    d = C.coen_pdf((HF / "coen-inundacion-yurimaguas-2026.txt").read_text(encoding="utf-8"))
    assert d["danos"]["total"] == {"Damnificados": 8.0, "Afectados": 1102.0, "ViviendasAfectadas": 424.0}
    assert d["decretos"] == [{"numero": "087-2026-PCM", "inminente": False}]
    # Un cuadro con dos distritos: las cifras de cada uno.
    d = C.coen_pdf((HF / "coen-incendio-huancavelica-2026.txt").read_text(encoding="utf-8"))
    assert d["danos"]["izcuchaca"] == {"HectareasCultivo": 14.5} and d["danos"]["conayca"] == {"HectareasCultivo": 10.0}


def test_coen_candidates_use_the_pdf_when_there_is_one(T, cal):
    text = (HF / "coen-helada-yauli-2026.txt").read_text(encoding="utf-8")
    doc = {"entradas": [
        {"url": YAULI_URL, "titulo": YAULI_TITLE, "pdf": "https://portal.indeci.gob.pe/x.pdf", "texto": text},
        {"url": YAULI_URL.replace("10158", "10160").replace("yauli", "acoria"), "pdf": "",
         "titulo": YAULI_TITLE.replace("YAULI", "ACORIA"), "texto": None},
        {"url": "https://portal.indeci.gob.pe/emergencias/reporte-preliminar-n-1-1-1-2026-coen-indeci-incendio-urbano/",
         "titulo": "REPORTE PRELIMINAR N° 1 - 1/1/2026 / COEN - INDECI / 10:00 HORAS (Reporte N° 1) INCENDIO URBANO EN "
                   "EL DISTRITO DE BREÑA - LIMA", "pdf": "", "texto": None},
    ]}
    sk = Counter()
    rows = list(C.coen(doc, T, cal, skipped=sk))
    assert sk == {"no climático": 1}
    a, b = rows
    assert (a["Ubigeo"], a["Date"], a["FechaTipo"], a["DangerType"]) == (T.resolve("Huancavelica", "Huancavelica", "Yauli"),
                                                                         "2026-07-01", "evento", "Helada/Friaje")
    assert (a["Afectados"], a["_sinpad"], a["_relato"], a["Origen"], a["IdFuente"]) == (190.0, "266584", True, "coen", "c10158-2026")
    assert (b["Date"], b["FechaTipo"], b["_relato"], b["_sinpad"]) == ("2026-08-02", "informe", False, None)
    assert b["Descripción"] == "Emergencia por helada en Acoria, Huancavelica, Huancavelica, reportada por el COEN."


def test_coen_assemble_builds_from_parts(tmp_path):
    parts = tmp_path / "coen-partes"
    (parts / "textos").mkdir(parents=True)
    pdf = "https://portal.indeci.gob.pe/x.pdf"
    (parts / "lista-00001.json").write_text(json.dumps([{"url": "u1", "titulo": "t1", "pdf": pdf},
                                                        {"url": "u2", "titulo": "t2", "pdf": ""}]), encoding="utf-8")
    name = hashlib.sha256(pdf.encode()).hexdigest()[:20] + ".txt.gz"
    (parts / "textos" / name).write_bytes(gzip.compress("1. HECHOS\nalgo\n4. ACCIONES\nno va".encode()))
    doc = json.loads(B.coen_assemble(parts, "https://portal.indeci.gob.pe/informe"))
    assert [(e["url"], e["texto"]) for e in doc["entradas"]] == [("u1", "1. HECHOS\nalgo"), ("u2", None)]


def test_partial_snapshot_is_marked_in_the_manifest(tmp_path):
    src = {"id": "coen-reportes", "descarga": "indeci-coen", "url": "https://portal.indeci.gob.pe/informe/",
           "archivo": "coen-reportes.json"}
    assert B.snapshot(src, [tmp_path]) is None  # nada bajado aún
    (tmp_path / "coen-reportes-partes").mkdir()
    (tmp_path / "coen-reportes-partes" / "lista-00001.json").write_text("[]", encoding="utf-8")
    out = B.snapshot(src, [tmp_path])
    assert out.name == "coen-reportes.parcial.json" and src["parcial"] is True and len(src["sha256"]) == 64


# ---------------------------------------------------------------------------
# Decretos de estado de emergencia
# ---------------------------------------------------------------------------
def test_decree_kind_and_places(T):
    assert C.decree_kind("Declaran el Estado de Emergencia en distritos de Piura, por peligro inminente ante intensas "
                         "precipitaciones pluviales") == ("inminente", "Lluvias intensas")
    assert C.decree_kind("Prorrogan el Estado de Emergencia por peligro inminente ante deslizamientos")[0] == "prorroga"
    assert C.decree_kind("Declaran Estado de Emergencia por impacto de daños ocasionados por huaicos") == ("impacto", "Deslizamiento")
    s = ("Declaran el Estado de Emergencia en las provincias de Nazca y Palpa del departamento de Ica, y en los distritos "
         "de San Buenaventura y Cholón de la provincia de Marañón del departamento de Huánuco")
    assert C.decree_places("", T, s) == [T.resolve("Huanuco", "Marañon", "San Buenaventura"),
                                         T.resolve("Huanuco", "Marañon", "Cholon"), "1103", "1104"]
    # Con anexo en columnas, los distritos del anexo.
    annex = "Nº  DEPARTAMENTO   PROVINCIA   DISTRITO\n1   PIURA    PIURA    CASTILLA\n2   PIURA    PIURA    CATACAOS\n"
    assert C.decree_places(annex, T) == ["200104", "200105"]
    assert C.decree_places("", T, "Prorrogan el Estado de Emergencia en el departamento de Puno") == ["21"]


def test_decrees_keep_only_climate_emergencies(T):
    doc = {"normas": [
        {"sumilla": "Declaran el Estado de Emergencia en los distritos de Castilla y Catacaos de la provincia de Piura "
                    "del departamento de Piura, por peligro inminente ante intensas precipitaciones pluviales",
         "fechaPublicacion": "20230310", "numeroDispositivo": "N° 029-2023-PCM", "urlPDF": "/api/archivo/file/x/1.pdf"},
        {"sumilla": "Prorrogan el Estado de Emergencia en el Corredor Vial Sur Andino (orden interno)",
         "fechaPublicacion": "20230311", "numeroDispositivo": "N° 030-2023-PCM"},
        {"sumilla": "Declaran el Estado de Emergencia en el departamento de Tumbes", "texto":
         "CONSIDERANDO: ... por impacto de daños a consecuencia de intensas precipitaciones pluviales ...",
         "fechaPublicacion": "20230312", "numeroDispositivo": "N° 031-2023-PCM"},
    ]}
    got = C.decrees(doc, T)
    assert [(d["fecha"], d["numero"], d["tipo"], d["peligro"], d["ubigeos"]) for d in got] == [
        ("2023-03-10", "029-2023-PCM", "inminente", "Lluvias intensas", ["200104", "200105"]),
        ("2023-03-12", "031-2023-PCM", "impacto", "Lluvias intensas", ["24"])]
    assert got[0]["url"] == "https://busquedas.elperuano.pe/api/archivo/file/x/1.pdf"


# ---------------------------------------------------------------------------
# Prensa
# ---------------------------------------------------------------------------
def test_text_date():
    assert C.text_date("damnificados del huaico registrado los días 4 y 5 de febrero de 2023", "2023-03-03") == "2023-02-04"
    assert C.text_date("aislados desde el 10 de abril por el desborde", "2017-04-17") == "2017-04-10"
    assert C.text_date("el 25 de diciembre cayó", "2024-01-05") == "2023-12-25"
    assert C.text_date("el 20 de mayo", "2024-01-05") is None  # más de 60 días antes
    assert C.text_date("el 30 de febrero", "2024-03-05") is None


def _note(title, body="", url=None, fecha="2024-03-12T10:00:00"):
    return {"titulo": title, "extracto": body, "fecha": fecha,
            "url": url or "https://diario.example/" + hashlib.sha1(title.encode()).hexdigest()[:8]}


def test_press_keeps_events_and_drops_the_rest(T, cal):
    doc = {"notas": [
        _note("Huaico deja 30 familias damnificadas en el distrito de Quivilla", "Unas 30 familias resultaron afectadas."),
        _note("Senamhi pronostica lluvias intensas para esta semana en Huánuco"),
        _note("Paita: desborde de aguas servidas inunda viviendas en el sector San Martín"),
        _note("Lluvia de promesas: candidato ofrece viviendas en Chongos Bajo"),
        _note("Fallece empresario acribillado en el barrio Huayco de Jaén"),
        _note("Lluvias en Huamachuco: calles amanecen con agua"),  # lluvia sin daño
        _note("Paratía: viviendas afectadas por desborde de relaves mineros"),
        _note("Dos mineros mueren sepultados por derrumbe en socavón en Huari"),
        _note("Albañil de 80 años muere aplastado en Retes", "Murió por el derrumbe de una pared que le cayó encima."),
        _note("Marzo: dos adolescentes perdieron la vida arrastradas por huaicos en Ayabaca", fecha="2022-12-30"),
        _note("Vecinos de Alto Selva Alegre temen colapso de torrenteras por las lluvias"),
        _note("El Porvenir: repararon avenidas afectadas por el huaico de 2017"),
        _note("Contraloría identifica deficiencias en apoyo a damnificados del huaico en Secocha",
              "La Contraloría revisó la entrega de ayuda a los damnificados del huaico registrado los días 4 y 5 de "
              "febrero de 2024 en el distrito de Mariano Nicolás Valcárcel, provincia de Camaná.", fecha="2024-03-03"),
        _note("Paro en Jauja por desborde de laguna Tragadero afecta carretera hacia Tarma",
              "Pobladores del Valle de Yanamarca, en el distrito de Marco, provincia de Jauja, bloquearon la vía."),
    ]}
    sk = Counter()
    rows = list(C.press(doc, T, cal, outlet="Diario de prueba", skipped=sk))
    got = {r["Descripción"].split("»")[0][1:]: r for r in rows}
    assert set(got) == {"Huaico deja 30 familias damnificadas en el distrito de Quivilla",
                        "Contraloría identifica deficiencias en apoyo a damnificados del huaico en Secocha",
                        "Paro en Jauja por desborde de laguna Tragadero afecta carretera hacia Tarma"}
    assert sk["otro tema"] == 4 and sk["no dice que algo pasó"] == 3 and sk["recuerda un evento de otro año"] == 1
    assert sk["sin causa climática a la vista"] == 2 and sk["resumen del año"] == 1
    q = got["Huaico deja 30 familias damnificadas en el distrito de Quivilla"]
    assert (q["DangerType"], q["Origen"], q["FechaTipo"], q["Date"]) == ("Huayco/Alud", "prensa", "publicacion", "2024-03-12")
    assert q["Ubigeo"] == T.resolve("Huanuco", "Dos de Mayo", "Quivilla")
    # La nota cita la fecha del huaico: esa es la fecha de la fila.
    s = got["Contraloría identifica deficiencias en apoyo a damnificados del huaico en Secocha"]
    assert (s["Date"], s["FechaTipo"], s["_publicado"]) == ("2024-02-04", "texto", "2024-03-03")
    # El lugar más seguro, no el primero que aparece.
    assert got["Paro en Jauja por desborde de laguna Tragadero afecta carretera hacia Tarma"]["Ubigeo"] == \
        T.resolve("Junin", "Jauja", "Marco")


def _page(text, fecha="1962-03-01", n=None):
    n = n or hashlib.sha1(text.encode()).hexdigest()[:8]
    return {"url": f"https://www.loc.gov/resource/sn{n}/{fecha}/ed-1/?sp=1", "fecha": fecha,
            "periodico": "evening star (washington, d.c.) 1854-1972", "lugar": "washington, district of columbia",
            "consulta": "floods in peru", "fragmento": text}


def test_hemeroteca_keeps_peru_disasters_and_drops_the_rest(T, cal):
    doc = {"paginas": [
        _page("... to 100 Die In Peruvian [[tag]]Avalanche[[/tag]] LIMA, [[tag]]Peru[[/tag]], March 1 (AP). —Rescue and "
              "relief teams hurried to the remote Andean town of Conchucos today where from 60 to 100 persons were "
              "reported killed by an [[tag]]avalanche[[/tag]], said Acting Prefect Oscar Barrios from the town of "
              "Huaras, far south of Conchucos."),
        _page("Washington, June 22.—The Cousul at Lambayeque writes to the Department of State that the extraordinary "
              "[[tag]]rains[[/tag]] in [[tag]]Peru[[/tag]] of the past quarter have been destructive to agriculture. "
              "The country around Lambayeque has been almost entirely inundated, railroads being washed away.",
              fecha="1878-06-24"),
        _page("... damage was done by the [[tag]]Floods[[/tag]] In [[tag]]Peru[[/tag]], Ind., nearby. With the Wabash "
              "river three feet over the danger line, 2,000 persons were driven from their homes.", fecha="1913-03-28"),
        _page("No [[tag]]Rain[[/tag]] in [[tag]]Peru[[/tag]]! It never [[tag]]rains[[/tag]] in Peru. All agriculture "
              "is the result of artificial irrigation.", fecha="1854-02-22"),
        _page("LIMA, Peru, May 31.—An earthquake shook northern [[tag]]Peru[[/tag]] and an [[tag]]avalanche[[/tag]] "
              "from Huascaran buried the town of Yungay, killing thousands.", fecha="1970-06-01"),
        _page("Serious [[tag]]Floods[[/tag]] in [[tag]]Peru[[/tag]]. LIMA. Peru. March 20.—Heavy rains have resulted in "
              "serious floods in various parts of the republic, entailing considerable damage.", fecha="1909-03-21"),
        _page("However, there are no disastrous [[tag]]rains[[/tag]] in [[tag]]Peru[[/tag]] and adobe buildings "
              "stand there today.", fecha="1931-03-21"),
        _page("Fire at Santiago, Chile, caused a loss of $1,000,000.", fecha="1909-04-10"),
        {**_page("x", fecha="1925-03-23"), "fragmento": None},
    ]}
    sk = Counter()
    rows = list(C.hemeroteca(doc, T, cal, archive="Chronicling America", skipped=sk))
    assert sk == {"Perú o Lima de EE. UU.": 1, "descripción general del país": 1, "sismo, maremoto o volcán": 1,
                  "sin lugar": 1, "no dice que algo pasó": 1, "no nombra el Perú": 1, "fragmento aún no leído": 1}
    a, b = rows
    # El primer lugar que nombra la nota (Conchucos), no el del prefecto (Huaraz) ni el del cable (Lima).
    assert (a["Ubigeo"], a["DangerType"], a["Date"]) == (T.resolve("Ancash", "Pallasca", "Conchucos"), "Huayco/Alud",
                                                        "1962-03-01")
    assert (a["Origen"], a["FechaTipo"], a["Confianza"], a["_publicado"]) == ("hemeroteca", "publicacion", "baja",
                                                                              "1962-03-01")
    assert a["Fuente"].startswith("https://www.loc.gov/resource/") and a["_medio"] == "Evening Star"
    assert a["FuenteCita"] == "Evening Star (Washington, District Of Columbia), 1962-03-01, vía Chronicling America"
    excerpt = a["Descripción"].split("»")[0][1:]
    assert len(excerpt) <= C.PRESS_EXCERPT + 1 and "[[tag]]" not in a["Descripción"]
    assert (b["Ubigeo"], b["NivelUbigeo"], b["Date"]) == ("14", "departamento", "1878-06-24")


# ---------------------------------------------------------------------------
# GLOF, llamamientos e inventarios
# ---------------------------------------------------------------------------
def _ods(rows: list[list[str]], sheet: str = "RGI60_16_LowLatitudes") -> bytes:
    t = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    p = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    o = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    body = "".join("<table:table-row>" + "".join(f"<table:table-cell><text:p>{v}</text:p></table:table-cell>" for v in r)
                   + "</table:table-row>" for r in rows)
    xml = (f'<office:document-content xmlns:office="{o}" xmlns:table="{t}" xmlns:text="{p}"><office:body>'
           f'<office:spreadsheet><table:table table:name="{sheet}">{body}</table:table></office:spreadsheet>'
           f"</office:body></office:document-content>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.xml", xml)
    return buf.getvalue()


def test_glof_reader(T, cal):
    head = ["Country", "Glacier", "Lake", "Longitude", "Latitude", "Date", "Date_Min", "Date_Max", "Mechanism",
            "Impact_and_destruction", "reported_fatalities", "Further_comments", "First_reference_found"]
    rows = [head,
            ["Peru", "Salkantay", "Humantay", "-72,5691", "-13,3424", "2020-02-23", "", "", "overtopping",
             "At least 13 fatalities", "13", "landslide triggered", "Petley (2020)"],
            ["Peru", "Pucajirca", "Safuna Alta", "-77,6186", "-8,8425", "1970-05-31", "", "", "piping", "", "",
             "partial drainage; earthquake triggered", ""],
            ["Peru", "", "Unnamed (Q. Ulta)", "-77,5125", "-9,1228", "1939-04", "", "", "breach", "", "",
             "partial drainage", ""],
            ["Peru", "", "", "-72,7941", "-13,2434", "", "2018-12-23", "2019-03-23", "breach", "", "",
             "partial drainage; triggers: landslides, rockfalls and debris flows", ""],
            ["Peru", "", "", "-77,7158", "-8,8425", "", "1948", "1970", "", "", "", "", ""],
            ["Peru", "\ufeffRGI60-16.01292", "", "-77,3780", "-9,3944", "2015-03-10", "", "", "", "", "", "", ""],
            ["Peru", "Palcaraju", "Broggi, J. A. (1942). Informe preliminar sobre la exploración de las lagunas.",
             "-77,3780", "-9,3944", "1941-12-13", "", "", "breach", "", "x", "partial drainage", "1942"],
            ["Nepal", "", "Dig Tsho", "86,58", "27,87", "1985-08-04", "", "", "breach", "", "", "", ""]]
    sk = Counter()
    got = list(C.glof(C.ods_rows(_ods(rows)), T, cal, url="https://doi.org/10.5281/zenodo.23370149", skipped=sk))
    assert sk == {"detonado por un sismo": 1, "sin fecha (ventana de varios años o década)": 1}
    assert [(r["Date"], r["PrecisionFecha"], r["Departamento"], r["DangerType"]) for r in got] == [
        ("2020-02-23", "dia", "Cusco", "Huayco/Alud"), ("1939-04-01", "mes", "Áncash", "Huayco/Alud"),
        ("2019-01-01", "anio", "Cusco", "Huayco/Alud"), ("2015-03-10", "dia", "Áncash", "Huayco/Alud"),
        ("1941-12-13", "dia", "Áncash", "Huayco/Alud")]
    h, u, w, rgi, hz = got
    assert rgi["Ubicacion"] == "laguna glaciar" and "RGI" not in rgi["Descripción"] + rgi["Ubicacion"]
    assert hz["Ubicacion"] == "laguna del glaciar Palcaraju" and "Broggi" in hz["FuenteCita"]
    assert "Broggi" not in hz["Descripción"] and "fallecidos, sin cifra" in hz["Descripción"]
    assert h["Fallecidos"] == 13 and h["PrecisionGeo"] == "coordenada-fuente" and "Humantay" in h["Descripción"]
    assert "laguna sin nombre de la quebrada Ulta" in u["Descripción"]
    assert "deslizamiento, caída de rocas o flujo de detritos" in w["Descripción"] and "entre 2018-12-23" in w["Descripción"]


def test_appeals_keep_metadata_only():
    doc = {"results": [
        {"code": "MDRPE012", "start_date": "2017-02-22T00:00:00Z", "name": "Peru - Floods", "dtype": {"name": "Flood"},
         "atype_display": "Emergency Appeal", "amount_requested": 2204017.0, "num_beneficiaries": 35000, "event": 44,
         "contacts": [{"name": "no se guarda"}]},
        {"code": "MDRPE013", "start_date": "2021-12-05T00:00:00Z", "name": "Peru - Earthquake",
         "dtype": {"name": "Earthquake"}, "atype_display": "DREF", "amount_requested": 253540.0, "event": 5710}]}
    got = C.appeals(doc)
    assert [(a["fecha"], a["codigo"], a["clima"]) for a in got] == [("2017-02-22", "MDRPE012", True),
                                                                   ("2021-12-05", "MDRPE013", False)]
    assert got[0]["url"] == "https://go.ifrc.org/emergencies/44" and "contacts" not in json.dumps(got)


def test_inventory_dated(T):
    ms = lambda y: int(__import__("datetime").datetime(y, 6, 1).timestamp() * 1000)  # noqa: E731
    doc = {"features": [{"attributes": {"UBIGEO": "200104", "TIP_PELIGRO": "3000|3100", "FECHA": ms(2003), "REGISTRO": "Publicable"}},
                        {"attributes": {"UBIGEO": "200104", "TIP_PELIGRO": "3000|3200", "FECHA": ms(2003), "REGISTRO": "Revision"}},
                        {"attributes": {"UBIGEO": "200104", "TIP_PELIGRO": "1000|1300", "FECHA": ms(2007), "REGISTRO": "Publicable"}},
                        {"attributes": {"UBIGEO": "200105", "TIP_PELIGRO": "1000|1300", "FECHA": ms(2007), "REGISTRO": "NoMostrarWEB"}},
                        {"attributes": {"UBIGEO": "200105", "TIP_PELIGRO": "1000|1300", "FECHA": None}}]}
    got = C.inventory_dated(doc, T, "https://geocatmin.example/MapServer/1")
    assert [(e["anio"], e["ubigeos"], e["grupo"], e["puntos"], e["tipo"]) for e in got] == [
        (2003, ["200104"], "hidrometeorologico", 2, "inventario"), (2007, ["200104"], "geologico-hidro", 1, "inventario")]


# ---------------------------------------------------------------------------
# Unión y prevención
# ---------------------------------------------------------------------------
def _row(T, cal, origin, sid, day, danger, code, **kw):
    r = make(T, cal, code=code, day=day, precision=kw.pop("precision", "dia"), danger=danger, origin=origin,
             source_id=sid, url=f"https://{origin}.example/{sid}", cite=origin, license="x", icen=False)
    r.update(kw)
    return r


def test_link_corroborates_or_adds(T, cal):
    records = [_row(T, cal, "sinpad", "164403", "2024-02-21", "Granizada", "030206"),
               _row(T, cal, "sinpad", "164500", "2024-02-21", "Huayco/Alud", "200104")]
    cands = [
        _row(T, cal, "coen", "c1-2024", "2024-02-22", "Granizada", "030206", _sinpad="164403", _relato=True,
             Afectados=40, ImpactoReportado="si", Descripción="Granizada dañó cultivos."),
        _row(T, cal, "prensa", "p1", "2024-02-25", "Lluvias intensas", "2001", FechaTipo="publicacion"),  # provincia
        _row(T, cal, "prensa", "p2", "2024-04-01", "Huayco/Alud", "200104", FechaTipo="publicacion"),  # muy tarde
        _row(T, cal, "prensa", "p3", "2024-04-03", "Deslizamiento", "200104", FechaTipo="publicacion"),
        _row(T, cal, "glof", "g1", "2024-02-20", "Huayco/Alud", "200104"),
    ]
    stats = Counter()
    added = enlace.link(records, cands, stats)
    assert [r["Id"] for r in added] == ["prensa-p2"]
    g, h = records
    assert (g["Corroboracion"], g["OrigenesCorroboran"], g["Afectados"]) == (1, "coen", 40)
    assert "Según el COEN: «Granizada dañó cultivos.»" in g["Descripción"]
    assert (h["Corroboracion"], h["OrigenesCorroboran"]) == (2, "glof,prensa")
    assert h["FuentesAdicionales"] == "https://prensa.example/p1 | https://glof.example/g1"
    assert added[0]["Corroboracion"] == 1  # la segunda nota del mismo huaico se suma a la primera
    assert stats == {"coen: corrobora (código SINPAD)": 1, "prensa: corrobora (lugar y fecha)": 2,
                     "glof: corrobora (lugar y fecha)": 1, "prensa: fila propia": 1}
    assert not enlace.compatible("Granizada", "Huayco/Alud") and enlace.compatible("Lluvias intensas", "Huayco/Alud")


def test_link_joins_reprints_of_an_old_cable(T, cal):
    records = [_row(T, cal, "curado", "egu1891-paita", "1891-01-01", "Lluvias intensas", "200501", precision="anio"),
               _row(T, cal, "sinpad", "x", "1891-03-10", "Granizada", "1301")]
    h = lambda sid, day, danger, code: _row(T, cal, "hemeroteca", sid, day, danger, code,  # noqa: E731
                                            FechaTipo="publicacion")
    cands = [h("a", "1891-03-20", "Inundacion", "200501"),  # la fila del año de Eguiguren
             h("b", "1925-03-23", "Lluvias intensas", "1301"),
             h("c", "1925-04-30", "Huayco/Alud", "1301"),  # 38 días después: el mismo cable en un semanario
             h("d", "1925-06-01", "Lluvias intensas", "1301"),  # 70 días: otro evento
             h("e", "1878-06-24", "Inundacion", "14"),
             h("f", "1878-07-10", "Lluvias intensas", "1401")]  # una provincia de ese departamento
    stats = Counter()
    added = enlace.link(records, cands, stats)
    assert [r["Id"] for r in added] == ["hemeroteca-b", "hemeroteca-d", "hemeroteca-e", "hemeroteca-f"]
    assert records[0]["OrigenesCorroboran"] == "hemeroteca" and added[0]["Corroboracion"] == 1
    assert stats == {"hemeroteca: corrobora (lugar y año)": 1, "hemeroteca: corrobora (lugar y fecha)": 1,
                     "hemeroteca: fila propia": 4}
    # La página del departamento corrobora la de su provincia que vino después, no al revés.
    late = h("g", "1878-07-20", "Inundacion", "14")
    assert enlace.link(records + added, [late], Counter()) == [] and added[3]["Corroboracion"] == 1


def test_prevention_indicators(T, cal):
    records = [_row(T, cal, "sinpad", "1", "2023-03-15", "Huayco/Alud", "200104"),
               _row(T, cal, "sinpad", "2", "2024-07-01", "Inundacion", "200105"),
               _row(T, cal, "prensa", "3", "2023-03-16", "Huayco/Alud", "200104", FechaTipo="publicacion")]
    decrees = [{"fecha": "2023-03-01", "numero": "029-2023-PCM", "tipo": "inminente", "peligro": "Lluvias intensas",
                "grupo": "hidrometeorologico", "ubigeos": ["20"]}]
    evals = [{"anio": 2010, "titulo": "Informe", "url": "", "institucion": "INGEMMET", "ubigeos": ["200104"],
              "grupo": "geologico-hidro"},
             {"anio": 2003, "titulo": "Inventario", "url": "", "institucion": "INGEMMET", "ubigeos": ["200105"],
              "grupo": "hidrometeorologico", "tipo": "inventario", "puntos": 3}]
    appeals = [{"fecha": "2023-03-20", "clima": True}, {"fecha": "2023-05-01", "clima": False}]
    p = enlace.prevention(records, decrees, evals, appeals)
    d = {code: dict(zip(p["columnas"], v)) for code, v in p["distritos"].items()}
    assert "20" not in d  # la declaratoria del departamento cuenta en cada distrito
    a, b = d["200104"], d["200105"]
    assert (a["decretosInminente"], a["evaluaciones"], a["primeraEvaluacion"], a["eventos"]) == (1, 1, 2010, 1)
    assert (a["eventosTrasEvaluacion"], a["eventosTrasInminente"], a["eventosConAviso"]) == (1, 1, 1)
    assert (b["puntosInventario"], b["inventarioDesde"], b["eventosTrasInventario"], b["eventosTrasInminente"]) == (3, 2003, 1, 0)
    y = {row[0]: dict(zip(p["columnasAnual"], row)) for row in p["anual"]}
    assert (y[2023]["decretosInminente"], y[2023]["llamamientosClima"], y[2023]["eventos"]) == (1, 1, 1)
    assert y[2003]["puntosInventario"] == 3 and y[2010]["evaluaciones"] == 1
