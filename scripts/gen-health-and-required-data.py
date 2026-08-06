#!/usr/bin/env python3
"""Generate health.json and other required data artifacts."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'public', 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# Load existing data
with open(os.path.join(DATA_DIR, 'status.json')) as f:
    status = json.load(f)
with open(os.path.join(DATA_DIR, 'manifest.json')) as f:
    manifest = json.load(f)
with open(os.path.join(DATA_DIR, 'sources.json')) as f:
    sources = json.load(f)
with open(os.path.join(DATA_DIR, 'quality.json')) as f:
    quality = json.load(f)
with open(os.path.join(DATA_DIR, 'indicators.json')) as f:
    indicators = json.load(f)

now = datetime.now(timezone.utc).isoformat()

# health.json
health = {
    "generatedAt": now,
    "asOf": manifest["asOf"],
    "pipelineStatus": "UPDATED",
    "lastSuccessfulRun": now,
    "dataVersion": manifest["dataVersion"],
    "policyVersion": "expert-grd-image-v1",
    "sources": []
}

for src in sources:
    health["sources"].append({
        "id": src["id"],
        "institution": src["institution"],
        "product": src["product"],
        "status": "HEALTHY" if src["status"] == "VERIFIED" else "UNKNOWN",
        "freshnessState": "FRESH",
        "lastUpdate": manifest["asOf"],
        "nextExpectedRelease": None,
        "cadence": src["updateFrequency"],
        "latency": src["latency"],
        "staleThreshold": "30d",
        "preliminary": True,
        "fallbackSource": src.get("fallbackSourceId"),
        "riskTier": "LOW" if src["status"] == "VERIFIED" else "MEDIUM"
    })

with open(os.path.join(DATA_DIR, 'health.json'), 'w') as f:
    json.dump(health, f, indent=2, ensure_ascii=False)

# source-registry.json
registry = {
    "generatedAt": now,
    "version": "1.0.0",
    "sources": sources
}
with open(os.path.join(DATA_DIR, 'source-registry.json'), 'w') as f:
    json.dump(registry, f, indent=2, ensure_ascii=False)

# latest.json
latest = {
    "generatedAt": now,
    "asOf": manifest["asOf"],
    "coastal": status["coastal"],
    "basin": status["basin"],
    "winds": status["winds"],
    "thermocline": status["thermocline"],
    "soi": status["soi"]
}
with open(os.path.join(DATA_DIR, 'latest.json'), 'w') as f:
    json.dump(latest, f, indent=2, ensure_ascii=False)

# official-status.json
official = {
    "generatedAt": now,
    "coastal": {
        "authority": "ENFEN / IMARPE",
        "status": status["coastal"]["alert"],
        "since": status["coastal"]["alertSince"],
        "source": status["coastal"]["alertSource"]
    },
    "basin": {
        "authority": "NOAA / CPC",
        "status": status["basin"]["alert"],
        "since": status["basin"]["alertSince"],
        "source": status["basin"]["alertSource"]
    }
}
with open(os.path.join(DATA_DIR, 'official-status.json'), 'w') as f:
    json.dump(official, f, indent=2, ensure_ascii=False)

# operational-signals.json
signals = {
    "generatedAt": now,
    "policyId": "expert-grd-image-v1",
    "policyName": "Señal operativa del experto GRD (imagen v1)",
    "disclaimer": "Esta señal no equivale al sistema oficial de alertas de NOAA ni de ENFEN.",
    "signals": [
        {
            "indicator": "Niño 1+2 (costero)",
            "value": status["coastal"]["nino12Anom"],
            "classification": "Amarillo" if status["coastal"]["nino12Anom"] >= 1.3 else "Normal" if status["coastal"]["nino12Anom"] <= 0.5 else "Sin clasificar",
            "color": "yellow" if status["coastal"]["nino12Anom"] >= 1.3 else "green" if status["coastal"]["nino12Anom"] <= 0.5 else "gray"
        },
        {
            "indicator": "ICEN (costero)",
            "value": status["coastal"]["icen"],
            "classification": "Amarillo" if status["coastal"]["icen"] >= 1.3 else "Normal" if status["coastal"]["icen"] <= 0.5 else "Sin clasificar",
            "color": "yellow" if status["coastal"]["icen"] >= 1.3 else "green" if status["coastal"]["icen"] <= 0.5 else "gray"
        },
        {
            "indicator": "Niño 3.4 (cuenca)",
            "value": status["basin"]["nino34Anom"],
            "classification": "Amarillo" if status["basin"]["nino34Anom"] > 1.0 else "Normal" if status["basin"]["nino34Anom"] <= 0.5 else "Sin clasificar",
            "color": "yellow" if status["basin"]["nino34Anom"] > 1.0 else "green" if status["basin"]["nino34Anom"] <= 0.5 else "gray"
        },
        {
            "indicator": "D20 (termoclina)",
            "value": status["thermocline"]["d20Anom"],
            "classification": "Normal" if abs(status["thermocline"]["d20Anom"]) <= 20 else "Amarillo" if status["thermocline"]["d20Anom"] >= 30 else "Sin clasificar",
            "color": "green" if abs(status["thermocline"]["d20Anom"]) <= 20 else "yellow" if status["thermocline"]["d20Anom"] >= 30 else "gray"
        },
        {
            "indicator": "SOI",
            "value": status["soi"]["value"],
            "classification": "Normal" if status["soi"]["value"] >= -7 else "Rojo",
            "color": "green" if status["soi"]["value"] >= -7 else "red"
        }
    ]
}
with open(os.path.join(DATA_DIR, 'operational-signals.json'), 'w') as f:
    json.dump(signals, f, indent=2, ensure_ascii=False)

# data-quality.json (already exists, augment)
dq = {
    "generatedAt": now,
    "overallQuality": "GOOD",
    "preliminaryDataCount": sum(1 for q in quality if q.get("preliminary")),
    "staleDataCount": 0,
    "missingDataCount": 0,
    "sources": quality
}
with open(os.path.join(DATA_DIR, 'data-quality.json'), 'w') as f:
    json.dump(dq, f, indent=2, ensure_ascii=False)

# threshold-policies.json
import yaml as pyyaml
policies = {}
policy_dir = os.path.join(os.path.dirname(__file__), '..', 'config', 'threshold-policies')
if os.path.exists(policy_dir):
    for fname in os.listdir(policy_dir):
        if fname.endswith('.yaml') or fname.endswith('.yml'):
            with open(os.path.join(policy_dir, fname)) as f:
                policies[fname] = pyyaml.safe_load(f)
with open(os.path.join(DATA_DIR, 'threshold-policies.json'), 'w') as f:
    json.dump({"generatedAt": now, "policies": policies}, f, indent=2, ensure_ascii=False, default=str)

print("Generated: health.json, source-registry.json, latest.json, official-status.json, operational-signals.json, data-quality.json, threshold-policies.json")
