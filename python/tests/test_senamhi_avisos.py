"""Nivel de los avisos meteorológicos del SENAMHI desde su tabla (enso.senamhi_avisos).

La tabla es un extracto real de ``?p=aviso-meteorologico`` (copia del recolector del Perú del 21 de
octubre de 2026); los mensajes, los del canal de Telegram y del COEN de los mismos días.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from enso import senamhi_avisos as SA
from enso import severity as SV
from enso import sourcefeed
from enso.fetch import Relay, Response
from enso.hazardparse import parse_coen, parse_telegram

FIX = Path(__file__).parent / "fixtures" / "sources"
NOW = datetime(2026, 10, 21, 20, 40, tzinfo=timezone.utc)
TABLE = (FIX / "senamhi-aviso-meteorologico.html").read_bytes()


@pytest.fixture(scope="module")
def table() -> SA.Table:
    return SA.Table(SA.parse(TABLE))


@pytest.fixture(scope="module")
def telegram() -> list[dict]:
    return parse_telegram((FIX / "news-senamhi-telegram.html").read_bytes()).items


def test_table_rows_carry_number_dates_and_level(table):
    assert len(table) == 24
    a = table.by_id[29296]
    assert (a.year, a.num, a.level, a.issued, a.start, a.end) == (2026, 429, "rojo", date(2026, 10, 20),
                                                                  date(2026, 10, 22), date(2026, 10, 24))
    assert a.title == "PRECIPITACIONES EN LA COSTA CENTRO Y SUR" and not a.cancelled
    assert a.url.endswith("a=2026&b=29296&c=00&d=SENA")
    assert table.by_id[29290].cancelled  # «(AVISO CANCELADO)»: lo reemplazó la actualización N° 426
    assert table.by_num[(2021, 3)][0].level == "amarillo"  # «003»: el número vuelve a 1 cada año
    assert {a.level for a in table.avisos} <= {"amarillo", "naranja", "rojo"}


def test_every_telegram_warning_gets_the_level_of_its_row(table, telegram):
    avisos = [i for i in telegram if i["title"].startswith("Aviso del SENAMHI")]
    assessed = [SV.assess("senamhi-telegram", i["title"], i["summary"], i["published"], NOW, table) for i in avisos]
    got = {a["aviso"]["num"]: a["severity"]["label"] for a in assessed}
    assert len(got) == len(avisos)
    assert got[429] == "Rojo" and got[428] == "Naranja" and got[427] == "Rojo" and got[422] == "Amarillo"
    a = SV.assess("senamhi-telegram", avisos[0]["title"], avisos[0]["summary"], avisos[0]["published"], NOW, table)
    assert a["severity"]["scale"] == "senamhi-colores" and a["severity"]["rank"] == 3
    assert a["severity"]["basis"] == "nivel del aviso N° 429 en la tabla de avisos del SENAMHI"
    # Las fechas del texto («del 22 al 24 de octubre») se conservan: coinciden con la tabla.
    assert a["valid"]["from"] == "2026-10-22T05:00:00Z" and "source" not in a["valid"] and a["phaseAtPublication"] == "proxima"


def test_without_the_table_or_an_unknown_aviso_nothing_is_invented(table, telegram):
    i = next(i for i in telegram if "29296" in i["summary"])
    assert SV.assess("senamhi-telegram", i["title"], i["summary"], i["published"], NOW)["severity"] is None
    newer = i["summary"].replace("29296", "29399")  # emitido después de la última copia de la tabla
    a = SV.assess("senamhi-telegram", i["title"], newer, i["published"], NOW, table)
    assert a["severity"] is None and "aviso" not in a


def test_a_message_without_link_matches_on_dates_and_words(table, telegram):
    i = next(i for i in telegram if "29295" in i["summary"])  # nevadas en la sierra sur, del 22 al 24
    plain = i["summary"].split(" Detalle en el sitio")[0]
    a = SV.assess("senamhi-telegram", i["title"], plain, i["published"], NOW, table)
    assert a["aviso"]["num"] == 428 and a["severity"]["label"] == "Naranja"
    # Las mismas palabras con otras fechas no son ese aviso.
    other = i["title"].replace("del 22 al 24", "del 23 al 25")
    assert SV.assess("senamhi-telegram", other, plain, i["published"], NOW, table)["severity"] is None


def test_a_current_report_takes_the_level_of_the_aviso_it_cites(table, telegram):
    i = next(i for i in telegram if i["title"].startswith("SENAMHI, en este momento") and "29257" in i["summary"])
    a = SV.assess("senamhi-telegram", i["title"], i["summary"], i["published"], NOW, table)
    assert a["kind"] == "en-curso" and a["severity"]["label"] == "Naranja" and "que cita" in a["severity"]["basis"]
    assert a["valid"] is None  # la vigencia del aviso no es la del mensaje


def test_coen_repost_matches_number_and_year(table):
    coen = parse_coen((FIX / "news-indeci-coen.xml").read_bytes(), "https://portal.indeci.gob.pe/emergencias/feed/")
    i = next(i for i in coen.items if i["title"].startswith("Aviso meteorológico N° 429"))
    a = SV.assess("indeci-coen", i["title"], i["summary"], i["published"], NOW, table)
    assert a["severity"]["label"] == "Rojo" and a["aviso"] == {
        "num": 429, "year": 2026, "url": SA.DETAIL.format(year=2026, id=29296), "cancelled": False}
    # Es un pronóstico, no un reporte de daños, y su texto da las fechas («desde el jueves 22 al domingo 24»).
    assert a["kind"] == "pronostico" and a["phaseAtPublication"] == "proxima"
    assert a["valid"] == {"from": "2026-10-22T05:00:00Z", "until": "2026-10-25T04:59:00Z",
                          "basis": "fechas que indica el aviso"}
    # Sin fechas en el texto, la vigencia sale de la tabla, marcada como tal.
    bare = i["title"].split(" (vigencia")[0]
    a = SV.assess("indeci-coen", bare, "Difundido por el COEN del INDECI.", i["published"], NOW, table)
    assert a["valid"] == {"from": "2026-10-22T05:00:00Z", "until": "2026-10-25T04:59:00Z", "source": "tabla",
                          "basis": "inicio y fin del aviso N° 429 en la tabla de avisos del SENAMHI"}
    assert SV.kind_of("indeci-coen", "Aviso hidrológico N° 1655 del SENAMHI: río Nanay") == "en-curso"
    # Un N° 429 de otro año no es este aviso.
    assert SV.assess("indeci-coen", i["title"], i["summary"], "2027-10-21T01:39:50Z", NOW, table)["severity"] is None


def _relay(tmp_path: Path, body: bytes) -> Relay:
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "76ad3aed9d48ed62.html").write_bytes(body)
    at = NOW.isoformat(timespec="seconds")
    (tmp_path / "index.json").write_text(json.dumps({
        "schema": "enso-relay/1", "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entries": [{"url": SA.URL, "status": 200, "file": "files/76ad3aed9d48ed62.html", "content_type": "text/html",
                     "sha256": hashlib.sha256(body).hexdigest(), "fetched_at": datetime.now(timezone.utc).isoformat(),
                     "group": "senamhi", "at": at}]}), encoding="utf-8")
    return Relay(tmp_path)


def test_feed_alerts_read_the_table_from_the_peru_relay(tmp_path, telegram):
    t = SA.from_relay(_relay(tmp_path, TABLE))
    assert t is not None and len(t) == 24
    items = [dict(i, id=f"tg{n}", feed="senamhi-telegram", first_seen=i["published"], hazards=["lluvias"])
             for n, i in enumerate(telegram)]
    out = sourcefeed.alerts(items, NOW, t)
    warnings = [a for a in out if a["title"].startswith("Aviso del SENAMHI")]
    assert warnings and all(a["severity"] and a["severity"]["scale"] == "senamhi-colores" for a in warnings)


def test_no_relay_or_a_broken_copy_leaves_texts_as_they_are(tmp_path):
    assert SA.from_relay(None) is None
    assert SA.from_relay(_relay(tmp_path, b"<html><body>Mantenimiento</body></html>")) is None

    class Broken:
        def get(self, url, accept=()):
            raise OSError("disco")

    assert SA.from_relay(Broken()) is None
    ok = type("R", (), {"get": lambda self, url, accept=(): Response(url, TABLE, "relay-peru", 200)})()
    assert len(SA.from_relay(ok)) == 24
