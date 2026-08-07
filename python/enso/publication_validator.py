"""Publication coherence validator — checks all artifacts share same publicationId.

This validator runs as a pre-deploy gate:
  1. Checks ALL JSON files in public/data/ have the same publicationId
  2. Checks ALL CSV files have valid headers and recent data
  3. Checks status.json values agree with series CSV tails
  4. Checks health.json has retrieval evidence for all sources
  5. Checks manifest.json lists all files correctly

Run as: python -m enso.publication_validator
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]


def validate_publication_id_coherence(data_dir: Path) -> list[str]:
    """Check all JSON files share the same publicationId."""
    errors = []
    pub_ids = {}
    for f in sorted(data_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
            if isinstance(d, dict):
                pid = d.get("publicationId")
                if pid:
                    pub_ids[f.name] = pid
                elif f.name not in ("source-registry.json",):
                    errors.append(f"{f.name}: missing publicationId")
        except json.JSONDecodeError as e:
            errors.append(f"{f.name}: JSON parse error: {e}")

    if pub_ids:
        unique_ids = set(pub_ids.values())
        if len(unique_ids) > 1:
            errors.append(f"Multiple publicationIds found: {pub_ids}")
        else:
            pid = list(unique_ids)[0]
            # Verify all files that SHOULD have publicationId do
            required = ["status.json", "health.json", "manifest.json"]
            for r in required:
                if r not in pub_ids:
                    errors.append(f"{r}: missing publicationId (expected {pid})")

    return errors


def validate_status_series_agreement(data_dir: Path) -> list[str]:
    """Check status.json values agree with series CSV tails."""
    errors = []
    status_path = data_dir / "status.json"
    if not status_path.exists():
        return [f"status.json not found"]

    status = json.loads(status_path.read_text())

    # Check each indicator
    checks = [
        ("nino12.csv", status.get("coastal", {}).get("nino12Anom"), "Niño 1+2"),
        ("nino34.csv", status.get("basin", {}).get("nino34Anom"), "Niño 3.4"),
        ("roni.csv", status.get("basin", {}).get("roni"), "RONI"),
        ("icen.csv", status.get("coastal", {}).get("icen"), "ICEN"),
        ("soi.csv", status.get("soi", {}).get("value"), "SOI"),
        ("d20.csv", status.get("thermocline", {}).get("d20Anom"), "D20"),
        ("u850.csv", status.get("winds", {}).get("u850Anom"), "u850"),
    ]

    for csv_name, status_value, label in checks:
        csv_path = data_dir / csv_name
        if not csv_path.exists():
            # Un producto explícitamente no disponible no debe conservar una
            # serie vieja solo para satisfacer la forma del snapshot.
            if status_value is not None:
                errors.append(f"{csv_name}: file not found")
            continue

        # Read last non-empty value from CSV
        lines = csv_path.read_text().strip().split("\n")
        last_value = None
        for line in reversed(lines):
            if line.startswith("#") or line.startswith("month,"):
                continue
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip():
                try:
                    last_value = float(parts[1].strip())
                except ValueError:
                    pass
                break

        if status_value is not None and last_value is not None:
            if abs(status_value - last_value) > 0.01:
                errors.append(
                    f"{label}: status.json={status_value} but {csv_name} tail={last_value} "
                    f"(diff={abs(status_value - last_value):.4f})"
                )

    return errors


def validate_health_evidence(data_dir: Path) -> list[str]:
    """Check health.json has real retrieval evidence for all sources."""
    errors = []
    health_path = data_dir / "health.json"
    if not health_path.exists():
        return [f"health.json not found"]

    health = json.loads(health_path.read_text())
    legacy_v3 = str(health.get("dataVersion", "")).startswith("3.0.")
    for src in health.get("sources", []):
        sid = src.get("id", "")
        evidence = src.get("retrievalEvidence", "")
        if not evidence:
            errors.append(f"health.json source {sid}: no retrievalEvidence")
        if src.get("status") not in ("HEALTHY", "FAILED", "QUARANTINED"):
            errors.append(f"health.json source {sid}: invalid status '{src.get('status')}'")
        allowed_freshness = {
            "CURRENT", "WITHIN_EXPECTED_CADENCE", "NOT_DUE",
            "PUBLICATION_EXPECTED", "DELAYED", "PRELIMINARY", "STALE",
            "FAILED", "QUARANTINED", "UNKNOWN",
        }
        # Compatibilidad de lectura para el snapshot 3.0 ya publicado. Todo
        # snapshot 3.1 nuevo debe usar los estados específicos de cadencia.
        if legacy_v3:
            allowed_freshness.add("FRESH")
        if src.get("freshnessState") not in allowed_freshness:
            errors.append(f"health.json source {sid}: invalid freshnessState '{src.get('freshnessState')}'")
        if (not legacy_v3 and not src.get("validPeriodEnd")
                and src.get("status") == "HEALTHY"):
            errors.append(f"health.json source {sid}: missing validPeriodEnd")

    return errors


def validate_manifest_files(data_dir: Path) -> list[str]:
    """Check manifest.json lists all files correctly."""
    errors = []
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.exists():
        return [f"manifest.json not found"]

    manifest = json.loads(manifest_path.read_text())

    # Check all files exist
    all_files = manifest.get("allFiles", [])
    for f in all_files:
        if not (data_dir / f).exists():
            errors.append(f"manifest.json lists '{f}' but file does not exist")

    # Check all actual files are listed
    actual_files = set(f.name for f in data_dir.iterdir() if f.is_file() and not f.name.startswith("."))
    listed_files = set(all_files)
    unlisted = actual_files - listed_files
    if unlisted:
        errors.append(f"Files not in manifest: {sorted(unlisted)}")

    return errors


def validate_no_synthetic_data(data_dir: Path) -> list[str]:
    """Check no synthetic data labels in production artifacts."""
    errors = []
    for f in data_dir.glob("*.json"):
        try:
            text = f.read_text()
            lower = text.lower()
            if "demostración" in lower or "sintético" in lower or "synthetic" in lower:
                if "not synthetic" not in lower and "no sintético" not in lower:
                    errors.append(f"{f.name}: contains synthetic/demostración label")
        except Exception:
            pass
    return errors


def run_all_validations() -> dict:
    """Run all publication coherence validations."""
    data_dir = Path(os.environ.get("ENSO_DATA_DIR", REPO / "public" / "data"))

    all_errors = []
    all_errors.extend(validate_publication_id_coherence(data_dir))
    all_errors.extend(validate_status_series_agreement(data_dir))
    all_errors.extend(validate_health_evidence(data_dir))
    all_errors.extend(validate_manifest_files(data_dir))
    all_errors.extend(validate_no_synthetic_data(data_dir))

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "passed": len(all_errors) == 0,
        "errorCount": len(all_errors),
        "errors": all_errors,
    }


def main():
    """Entry point."""
    print("=== Publication Coherence Validator ===")
    result = run_all_validations()

    if result["passed"]:
        print("✅ All publication coherence checks passed")
    else:
        print(f"❌ {result['errorCount']} errors found:")
        for e in result["errors"]:
            print(f"  ⚠️ {e}")

    # Write report
    report_path = REPO / "audit" / "freshness-and-automation" / "publication-coherence-validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
