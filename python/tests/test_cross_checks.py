"""Contrastes entre fuentes en la corrida diaria: lo que una fuente copia de otra tiene que coincidir.

Un lector puede devolver números con la forma y el rango correctos y aun así leer la columna equivocada. El informe
técnico del ENFEN copia en su tabla de índices el ICEN del IGP y el ONI y RONI de NOAA: si no coinciden, o la tabla
cambió, o una de las fuentes tiene una errata.
"""

from __future__ import annotations

import gzip
import json
from datetime import date

from conftest import FIX
from enso import observatory as obs
from enso import reports as R

N20 = FIX.parent / "reports" / "informe-tecnico-enfen-ano-12-n20-al-11-noviembre-2026.pages.json.gz"


def _builder(icen_sep: float = 4.50, oni_sep: float = 2.46, roni_sep: float = 1.97) -> obs.Builder:
    b = obs.Builder({}, obs.EventLog(), date(2026, 11, 20))

    def ser(points):
        return {"points": points, "latest": {"period": points[-1]["period"], "value": points[-1]["value"]}}

    b.series["icen"] = ser([{"period": "2026-08", "value": 3.98}, {"period": "2026-09", "value": icen_sep}])
    b.series["oni"] = ser([{"period": "2026-08", "value": 2.16}, {"period": "2026-09", "value": oni_sep}])
    b.series["roni"] = ser([{"period": "2026-08", "value": 1.69}, {"period": "2026-09", "value": roni_sep}])
    return b


def _informe() -> dict:
    d = json.loads(gzip.open(N20, "rt", encoding="utf-8").read())
    return R.informe_summary(R.parse_informe(d["pages"], d["source"]))


def test_informe_20_icen_typo_is_diagnosed_against_its_own_provisional():
    b = _builder()
    inf = b.informe(_informe())
    ev = [e for e in b.log.events if e.code == "informe-icen-mismatch"]
    assert len(ev) == 1 and "+4.98" in ev[0].message and "+4.50" in ev[0].message
    assert "probable errata en la tabla del informe" in ev[0].message
    assert inf["icenMismatch"] == {"period": "2026-09", "informe": 4.98, "igp": 4.5, "provisional": 4.69,
                                   "consistentWith": "IGP"}
    # El ONI y el RONI del informe coinciden con NOAA: sin aviso.
    assert not [e for e in b.log.events if e.code in ("informe-oni-mismatch", "informe-roni-mismatch")]


def test_informe_oni_or_roni_that_do_not_match_noaa_are_flagged():
    b = _builder(icen_sep=4.98, oni_sep=1.97, roni_sep=2.46)  # columnas ONI y RONI cruzadas
    b.informe(_informe())
    codes = {e.code for e in b.log.events}
    assert {"informe-oni-mismatch", "informe-roni-mismatch"} <= codes
    assert "informe-icen-mismatch" not in codes


def test_ensodisc_values_basis_tells_relative_from_traditional():
    """La discusión de NOAA del 12 de noviembre de 2026 cita +2,5 (Niño 3.4), +3,6 (Niño 3) y +4,4 (Niño 1+2): son las
    anomalías relativas de octubre, no las tradicionales de la semana (+3,2, +4,3 y +5,4)."""
    b = obs.Builder({}, obs.EventLog(), date(2026, 11, 20))
    wk = {r: [{"date": "2026-11-04", "anom": a0}, {"date": "2026-11-11", "anom": a1}]
          for r, a0, a1 in (("nino12", 5.6, 5.4), ("nino3", 4.4, 4.3), ("nino34", 3.3, 3.2))}
    mo = {"anom": {r: [{"period": "2026-09", "value": v0}, {"period": "2026-10", "value": v1}]
                   for r, v0, v1 in (("nino12", 4.69, 5.25), ("nino3", 3.6, 4.16), ("nino34", 2.9, 3.3))}}
    b.data = lambda sid: {"cpc-wksst": wk, "cpc-sstoi": mo}.get(sid)
    assert b.ensodisc_basis({"nino34": 2.5, "nino3": 3.6, "nino12": 4.4}) == "other"
    assert b.ensodisc_basis({"nino34": 3.2, "nino3": 4.3, "nino12": 5.4}) == "traditional-weekly"
    assert b.ensodisc_basis({"nino12": 5.2, "nino3": 4.2}) == "traditional-monthly"
    assert b.ensodisc_basis({}) is None
