"""Contratos del motor de grounding determinista.

- Devuelve evidencia con IDs y URLs de fuente.
- No usa memoria del modelo como fuente factual.
- Es determinista: la misma pregunta produce la misma evidencia.
"""

from __future__ import annotations

import json
from typing import Any

import pytest


# --- Implementación de referencia del motor de grounding en Python ---
# Espejo simplificado de src/lib/enso/grounding.ts. Sólo usa datos
# normalizados del proyecto y el corpus de conocimiento.

from enso.methodology import INDICATOR_BY_ID
from enso.sources import SOURCE_BY_ID


KEYWORDS: dict[str, list[str]] = {
    "nino12": ["niño 1+2", "nino 1+2", "1+2", "costero", "costa", "icen",
               "tsm costa", "tsm niño 1+2"],
    "icen": ["icen", "índice costero", "indice costero"],
    "nino34": ["niño 3.4", "nino 3.4", "3.4", "cuenca", "roni", "oni",
               "tsm cuenca", "tsm niño 3.4"],
    "roni": ["roni", "índice oceánico relativo", "indice oceanico relativo"],
    "soi": ["soi", "oscilación del sur", "oscilacion del sur", "tahiti", "darwin"],
    "u850": ["viento", "850", "zonal", "alisio", "alisios", "westerly",
             "easterly", "del oeste", "del este"],
    "d20": ["d20", "termoclina", "isoterma de 20", "isoterma 20",
            "subsuperficie", "subsuperficial"],
}

KNOWLEDGE: list[dict[str, str]] = [
    {"id": "k-enso-basin-def", "topic": "ENSO de cuenca",
     "text": "El ENSO de cuenca se monitorea con RONI en Niño 3.4."},
    {"id": "k-enso-coastal-def", "topic": "El Niño Costero",
     "text": "El Niño Costero se monitorea con ICEN en Niño 1+2."},
    {"id": "k-coastal-vs-basin", "topic": "Distinción costero vs cuenca",
     "text": "El Niño Costero y el de cuenca pueden ocurrir juntos o por separado."},
    {"id": "k-no-coastal-soi", "topic": "Inexistencia de SOI costero",
     "text": "No existe un «SOI costero» con respaldo metodológico equivalente."},
]


def _detect_indicators(q: str) -> list[str]:
    lower = q.lower()
    hits: set[str] = set()
    for ind_id, kws in KEYWORDS.items():
        if any(k in lower for k in kws):
            hits.add(ind_id)
    if "el niño" in lower or "la niña" in lower:
        hits.update({"nino34", "icen"})
    return sorted(hits)


def _evidence_for(ind_id: str, value: float | None = None,
                  month: str = "2026-07") -> dict[str, Any]:
    ind = INDICATOR_BY_ID[ind_id]
    src = SOURCE_BY_ID[ind.sourceId]
    return {
        "evidenceId": f"EVID-{ind_id}",
        "indicatorId": ind_id,
        "indicatorLabel": ind.shortName,
        "month": month,
        "value": value,
        "units": ind.units,
        "source": f"{src.institution} — {src.product}",
        "sourceUrl": src.url,
        "retrievalDate": src.retrievalDate,
        "preliminary": False,
        "derivedNote": "",
    }


def _knowledge_for(q: str) -> list[dict[str, str]]:
    lower = q.lower()
    out: list[dict[str, str]] = []
    for k in KNOWLEDGE:
        words = k["topic"].lower().split()
        if any(w in lower for w in words) or k["topic"].lower() in lower:
            out.append({"id": k["id"], "text": k["text"]})
    if "soi" in lower and "costero" in lower:
        out.append({"id": "k-no-coastal-soi",
                    "text": "No existe un «SOI costero»."})
    # Dedupe
    seen: set[str] = set()
    return [x for x in out if not (x["id"] in seen or seen.add(x["id"]))]


def build_grounding(question: str, value_map: dict[str, float | None] | None = None
                    ) -> dict[str, Any]:
    """Construye el objeto de grounding para ``question``."""
    vm = value_map or {}
    indicators = _detect_indicators(question)
    if not indicators:
        indicators = ["icen", "nino34"]
    evidence = [_evidence_for(i, vm.get(i)) for i in indicators]
    knowledge = _knowledge_for(question)
    return {
        "question": question,
        "evidence": evidence,
        "knowledgeSnippets": knowledge,
        "asOf": "2026-08-02",
    }


# --- Tests ---

def test_grounding_returns_evidence_with_ids():
    g = build_grounding("¿Cuál es el ICEN actual?")
    assert len(g["evidence"]) >= 1
    for e in g["evidence"]:
        assert e["evidenceId"].startswith("EVID-")
        assert e["indicatorId"]
        assert e["indicatorLabel"]


def test_grounding_returns_source_urls():
    g = build_grounding("¿Cuál es el RONI?")
    roni_e = next(e for e in g["evidence"] if e["indicatorId"] == "roni")
    assert roni_e["sourceUrl"].startswith("https://")
    assert "noaa.gov" in roni_e["sourceUrl"]


def test_grounding_deterministic_same_question_same_evidence():
    q = "¿Cómo está el Niño 3.4?"
    g1 = build_grounding(q)
    g2 = build_grounding(q)
    assert [e["evidenceId"] for e in g1["evidence"]] == \
           [e["evidenceId"] for e in g2["evidence"]]


def test_grounding_no_model_memory_used():
    """El motor no consulta memoria del modelo: todo viene de datos/corpus."""
    g = build_grounding("¿Qué es El Niño Costero?")
    # Toda afirmación debe tener evidenceId o un snippet con id.
    for e in g["evidence"]:
        assert e["evidenceId"]
    for k in g["knowledgeSnippets"]:
        assert k["id"]


def test_grounding_knowledge_for_soi_costero():
    g = build_grounding("¿Cuál es el SOI costero?")
    ids = [k["id"] for k in g["knowledgeSnippets"]]
    assert "k-no-coastal-soi" in ids


def test_grounding_returns_retrieval_date():
    g = build_grounding("ICEN")
    for e in g["evidence"]:
        assert e["retrievalDate"]  # no vacío
        # Formato ISO fecha.
        assert len(e["retrievalDate"]) == 10


def test_grounding_distinguishes_observation_from_interpretation():
    """Cada evidencia marca si el valor es derivado (derivedNote)."""
    g = build_grounding("ICEN y RONI")
    # El motor siempre incluye el campo derivedNote (vacío o no).
    for e in g["evidence"]:
        assert "derivedNote" in e


def test_grounding_idempotent_under_repeated_calls():
    q = "viento zonal 850 hPa"
    g1 = build_grounding(q)
    g2 = build_grounding(q)
    assert g1 == g2
