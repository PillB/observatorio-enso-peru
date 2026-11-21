"""El día de la corrida es el de Lima (``observatory.run_date``), no el UTC.

La hora de la corrida sale del cron real de ``.github/workflows/observatory.yml``: si se mueve la corrida, la prueba
sigue probando la hora en que de verdad corre.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import pytest
from conftest import ROOT

from enso import cenepred_escenario as CE
from enso import observatory as obs


def _cron_utc(day: date) -> datetime:
    wf = (ROOT.parent / ".github" / "workflows" / "observatory.yml").read_text(encoding="utf-8")
    m = re.search(r"cron:\s*'(\d+) (\d+) \* \* \*'", wf)
    assert m, "la corrida diaria del observatorio ya no es un cron diario simple"
    return datetime(day.year, day.month, day.day, int(m.group(2)), int(m.group(1)), tzinfo=timezone.utc)


@pytest.mark.parametrize("started, lima", [
    (datetime(2026, 12, 1, 4, 37, tzinfo=timezone.utc), date(2026, 11, 30)),   # 23:37 del 30 en Lima
    (datetime(2026, 12, 1, 4, 59, 59, tzinfo=timezone.utc), date(2026, 11, 30)),
    (datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc), date(2026, 12, 1)),     # medianoche en Lima
    (datetime(2027, 1, 1, 3, 0, tzinfo=timezone.utc), date(2026, 12, 31)),     # cambio de año
    (datetime(2026, 11, 21, 7, 24, tzinfo=timezone(timedelta(hours=-5))), date(2026, 11, 21)),
])
def test_run_date_is_the_civil_date_in_lima(started, lima):
    assert obs.run_date(started) == lima


def test_the_daily_run_does_not_expire_the_cenepred_scenario_on_its_last_day():
    """Escenario N° 102 (copia incluida en el sitio): vigente de 2026-11 a 2027-01. La corrida del 31 de enero en Lima
    empieza el 1 de febrero en UTC; con la fecha UTC, el sitio lo mostraba «vencido» esa noche."""
    seed = CE.load_seed()
    assert seed["scenario"]["until"] == "2027-01"
    started = _cron_utc(date(2027, 2, 1))
    assert started.astimezone(obs.LIMA).date() == date(2027, 1, 31), "la corrida es de noche en Lima"
    assert CE.freshness_item(seed, obs.run_date(started))["state"] != "vencido"
    assert CE.freshness_item(seed, started.date())["state"] == "vencido"  # lo que pasaba con la fecha UTC
    # Y al día siguiente en Lima sí vence.
    assert CE.freshness_item(seed, obs.run_date(_cron_utc(date(2027, 2, 2))))["state"] == "vencido"


def test_the_published_day_of_an_offline_run_at_cron_time_is_lima(tmp_path, monkeypatch):
    """La corrida completa (sin red) a la hora del cron del 1 de febrero UTC publica el 31 de enero y el escenario
    vigente."""
    import json

    started = _cron_utc(date(2027, 2, 1))

    class _At(datetime):
        @classmethod
        def now(cls, tz=None):
            return started if tz else started.replace(tzinfo=None)

    monkeypatch.setattr(obs, "datetime", _At)
    obs.run(tmp_path / "out", None, offline=True, only=["igp-icen"])
    dash = json.loads((tmp_path / "out" / "dashboard.json").read_text(encoding="utf-8"))
    assert dash["freshness"]["today"] == "2027-01-31"
    assert dash["freshness"]["items"]["escenario"]["state"] != "vencido"


def test_the_raw_archive_keeps_the_utc_day_of_the_run(tmp_path, monkeypatch):
    """El archivo crudo de ``data-archive`` sigue nombrado por el día UTC (como las copias que ya tiene y como las
    ventanas de la auditoría de deriva), aunque el día publicado sea el de Lima."""
    started = _cron_utc(date(2027, 2, 1))

    class _At(datetime):
        @classmethod
        def now(cls, tz=None):
            return started if tz else started.replace(tzinfo=None)

    days = []
    monkeypatch.setattr(obs, "datetime", _At)
    monkeypatch.setattr(obs, "archive_raw", lambda raw_dir, acquired, day: days.append(day) or 0)
    obs.run(tmp_path / "out", None, offline=True, only=["igp-icen"], raw_dir=tmp_path / "raw")
    assert days == [date(2027, 2, 1)]
