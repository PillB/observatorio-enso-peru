"""Mapa de alertas de Noticias: el mapa del Perú, la analítica de versiones (``node --test``)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from enso.geo import department_names
from test_geo_console import JS, _need_node

ROOT = Path(__file__).resolve().parents[2]


def test_map_asset_has_every_department_and_place_point():
    m = json.loads((ROOT / "public" / "assets" / "peru-map.json").read_text(encoding="utf-8"))
    assert {d["code"] for d in m["departments"]} == set(department_names())
    for d in m["departments"]:
        assert d["d"].startswith("M") and d["d"].endswith("Z")
        x, y = d["label"]
        assert 0 <= x <= m["width"] and 0 <= y <= m["height"]
    # Un punto por provincia y por distrito de los límites del IGN, dentro del mapa.
    assert sum(len(k) == 4 for k in m["points"]) > 190 and sum(len(k) == 6 for k in m["points"]) > 1800
    assert all(0 <= x <= m["width"] and 0 <= y <= m["height"] for x, y in m["points"].values())
    assert "IGN" in m["source"]
    assert (ROOT / "public" / "assets" / "peru-map.json").stat().st_size < 150_000


def test_ab_analytics_api_with_node():
    node = _need_node()
    r = subprocess.run([node, "--test", str(JS / "ab.test.mjs")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert re.search(r"# fail 0", r.stdout) and not re.search(r"# skipped [1-9]", r.stdout), r.stdout[-2000:]
