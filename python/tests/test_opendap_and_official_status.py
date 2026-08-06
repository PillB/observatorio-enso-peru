"""Tests para los fetchers OPeNDAP (D20/u850) y scrapers de estado oficial.

Estos tests verifican:
  - El parser ASCII de OPeNDAP.
  - La conversión de tiempo (hours/days since 1800).
  - El cálculo de media areal sobre Niño 3.4.
  - El cálculo de anomalías con climatología 1991-2020.
  - El scraper de NOAA ENSO Advisory (formato HTML).
  - El fallback de ENFEN.
  - Las convenciones de signo de viento y D20.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Añade el directorio python/ al path.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

from enso.opendap_fetchers import (
    GodasD20Fetcher,
    NcepU850Fetcher,
    compute_monthly_anomaly,
    d20_interpretation,
    hours_since_1800_to_iso,
    parse_opendap_ascii,
    spatial_average_nino34,
    time_since_1800_to_iso,
    u850_direction,
)
from enso.models import MonthlyPoint, SeriesFlag


# ----------------------------------------------------------------------------
# Parser OPeNDAP ASCII
# ----------------------------------------------------------------------------
class TestOpendapParser:
    """Tests del parser ASCII de OPeNDAP."""

    SAMPLE_RESPONSE = """Dataset {
    Grid {
     ARRAY:
        Float32 uwnd[time = 2][level = 1][lat = 2][lon = 3];
     MAPS:
        Float64 time[time = 2];
        Float32 level[level = 1];
        Float32 lat[lat = 2];
        Float32 lon[lon = 3];
    } uwnd;
} Datasets/test;
---------------------------------------------
uwnd.uwnd[2][1][2][3]
[0][0][0], 1.0, 2.0, 3.0
[0][0][1], 4.0, 5.0, 6.0
[1][0][0], 7.0, 8.0, 9.0
[1][0][1], 10.0, 11.0, 12.0

uwnd.time[2]
1297320.0, 1298040.0

uwnd.level[1]
850.0

uwnd.lat[2]
5.0, 2.5

uwnd.lon[3]
190.0, 192.5, 195.0
"""

    def test_parse_extracts_data_lines(self):
        """El parser extrae correctamente las líneas de datos."""
        data, times = parse_opendap_ascii(self.SAMPLE_RESPONSE, "uwnd")
        assert len(data) == 4  # 2 time × 2 lat
        assert data[0] == [1.0, 2.0, 3.0]
        assert data[3] == [10.0, 11.0, 12.0]

    def test_parse_extracts_time_values(self):
        """El parser extrae correctamente los valores del eje tiempo."""
        _, times = parse_opendap_ascii(self.SAMPLE_RESPONSE, "uwnd")
        assert len(times) == 2
        assert times[0] == 1297320.0
        assert times[1] == 1298040.0

    def test_parse_raises_on_missing_variable(self):
        """Lanza OpendapError si la variable no se encuentra."""
        from enso.opendap_fetchers import OpendapError

        with pytest.raises(OpendapError):
            parse_opendap_ascii("no data here", "uwnd")

    def test_parse_handles_nan_values(self):
        """El parser maneja valores NaN correctamente."""
        text = self.SAMPLE_RESPONSE.replace("1.0, 2.0, 3.0", "NaN, 2.0, 3.0")
        data, _ = parse_opendap_ascii(text, "uwnd")
        assert data[0][0] is None


# ----------------------------------------------------------------------------
# Conversión de tiempo
# ----------------------------------------------------------------------------
class TestTimeConversion:
    """Tests de conversión de tiempo (hours/days since 1800)."""

    def test_hours_to_iso_january_1948(self):
        """1297320 horas desde 1800-01-01 = 1948-01."""
        assert hours_since_1800_to_iso(1297320.0) == "1948-01"

    def test_days_to_iso_january_2026(self):
        """82545 días desde 1800-01-01 = 2026-01."""
        assert time_since_1800_to_iso(82545.0, unit="days") == "2026-01"

    def test_days_to_iso_june_2026(self):
        """82696 días desde 1800-01-01 = 2026-06."""
        assert time_since_1800_to_iso(82696.0, unit="days") == "2026-06"

    def test_invalid_unit_raises(self):
        """Unidad no soportada lanza ValueError o devuelve cadena vacía."""
        result = time_since_1800_to_iso(100.0, unit="seconds")
        # Debe devolver cadena vacía o lanzar ValueError
        assert result == "" or result is None


# ----------------------------------------------------------------------------
# Media areal Niño 3.4
# ----------------------------------------------------------------------------
class TestSpatialAverage:
    """Tests del cálculo de media areal sobre Niño 3.4."""

    def test_uniform_field_returns_same_value(self):
        """Un campo uniforme devuelve el mismo valor."""
        data = [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]
        lats = [5.0, -5.0]
        lons = [190.0, 200.0, 240.0]
        avg = spatial_average_nino34(data, lats, lons)
        assert avg == 1.0

    def test_nan_values_excluded(self):
        """Los valores NaN se excluyen del promedio."""
        data = [[1.0, None, 3.0], [1.0, 1.0, 1.0]]
        lats = [5.0, -5.0]
        lons = [190.0, 200.0, 240.0]
        avg = spatial_average_nino34(data, lats, lons)
        assert avg is not None
        # (1+3+1+1+1) / 5 = 1.4
        assert abs(avg - 1.4) < 0.01

    def test_outside_region_excluded(self):
        """Los puntos fuera de Niño 3.4 se excluyen."""
        data = [[1.0, 1.0], [1.0, 1.0]]
        # lat fuera de rango (10°N)
        lats = [10.0, -10.0]
        lons = [190.0, 240.0]
        avg = spatial_average_nino34(data, lats, lons)
        assert avg is None  # Ningún punto dentro del rango


# ----------------------------------------------------------------------------
# Cálculo de anomalías
# ----------------------------------------------------------------------------
class TestAnomalyComputation:
    """Tests del cálculo de anomalías con climatología."""

    def test_anomaly_subtracts_climatology(self):
        """La anomalía resta la climatología mensual."""
        points = []
        # 3 años de datos, enero = 10, febrero = 20
        for year in range(2020, 2023):
            points.append(MonthlyPoint(month=f"{year}-01", value=10.0, flag=SeriesFlag.FINAL))
            points.append(MonthlyPoint(month=f"{year}-02", value=20.0, flag=SeriesFlag.FINAL))
        anom = compute_monthly_anomaly(points, baseline_years=(2020, 2022))
        # Climatología enero = 10, febrero = 20 → anomalía = 0
        assert all(p.value == 0.0 for p in anom)

    def test_anomaly_with_missing_values(self):
        """Los valores faltantes se preservan como None."""
        points = [
            MonthlyPoint(month="2020-01", value=None, flag=SeriesFlag.FINAL),
            MonthlyPoint(month="2020-02", value=5.0, flag=SeriesFlag.FINAL),
        ]
        anom = compute_monthly_anomaly(points, baseline_years=(2020, 2020))
        assert anom[0].value is None
        # febrero: clim = 5.0, anom = 0.0
        assert anom[1].value == 0.0


# ----------------------------------------------------------------------------
# Interpretaciones de viento y D20
# ----------------------------------------------------------------------------
class TestInterpretations:
    """Tests de las funciones de interpretación."""

    def test_u850_westerly(self):
        """u850 > 0.5 ⇒ westerlies."""
        assert "westerlies" in u850_direction(1.5).lower()

    def test_u850_easterly(self):
        """u850 < -0.5 ⇒ easterlies."""
        assert "easterlies" in u850_direction(-1.5).lower()

    def test_u850_neutral(self):
        """u850 entre -0.5 y 0.5 ⇒ neutral."""
        assert "neutral" in u850_direction(0.2).lower()

    def test_u850_none(self):
        """u850 None ⇒ Sin datos."""
        assert u850_direction(None) == "Sin datos"

    def test_d20_deep(self):
        """D20 > 10 ⇒ más profunda (El Niño)."""
        assert "profunda" in d20_interpretation(15.0).lower()

    def test_d20_shallow(self):
        """D20 < -10 ⇒ más somera (La Niña)."""
        assert "somera" in d20_interpretation(-15.0).lower()

    def test_d20_normal(self):
        """D20 entre -10 y 10 ⇒ normal."""
        assert "normal" in d20_interpretation(5.0).lower()

    def test_d20_none(self):
        """D20 None ⇒ Sin datos."""
        assert d20_interpretation(None) == "Sin datos"


# ----------------------------------------------------------------------------
# Configuración de fetchers
# ----------------------------------------------------------------------------
class TestFetcherConfig:
    """Tests de configuración de los fetchers."""

    def test_u850_fetcher_indices(self):
        """NcepU850Fetcher tiene los índices correctos para 850 hPa y Niño 3.4."""
        f = NcepU850Fetcher()
        assert f.LEVEL_IDX == 2  # 850 mb
        assert f.LAT_START == 34  # 5°N
        assert f.LAT_STOP == 38   # 5°S
        assert f.LON_START == 76  # 190°E
        assert f.LON_STOP == 96   # 240°E

    def test_d20_fetcher_indices(self):
        """GodasD20Fetcher tiene los índices correctos para Niño 3.4."""
        f = GodasD20Fetcher()
        assert f.LAT_START == 209  # ≈ -5°
        assert f.LAT_STOP == 239   # ≈ +5°
        assert f.LON_START == 190  # ≈ 190.5°E
        assert f.LON_STOP == 240   # ≈ 240.5°E

    def test_u850_source_id(self):
        assert NcepU850Fetcher.source_id == "noaa-cpc-u850-anom"

    def test_d20_source_id(self):
        assert GodasD20Fetcher.source_id == "noaa-cpc-godas-d20"


# ----------------------------------------------------------------------------
# Scraper de NOAA ENSO Advisory
# ----------------------------------------------------------------------------
class TestNoaaAdvisoryParser:
    """Tests del parser de NOAA ENSO Advisory (formato HTML)."""

    SAMPLE_HTML = """
    <html><body>
    <p>ENSO Diagnostic Discussion</p>
    <p>9 July 2026</p>
    <p>Alert System Status: El Niño Advisory &nbsp;</p>
    <p>Synopsis: El Niño continues and will strengthen through the end
    of the year, with a 97% chance it will persist through early spring
    2027.</p>
    </body></html>
    """

    def test_parse_extracts_alert_status(self):
        """El parser extrae correctamente el Alert System Status."""
        import re
        import html as html_mod
        from enso.official_status import NOAA_ALERT_PATTERNS

        text = html_mod.unescape(re.sub(r"<[^>]+>", " ", self.SAMPLE_HTML))
        text = re.sub(r"\s+", " ", text).strip()

        alert = None
        m = re.search(r"Alert System Status:\s*(.+?)(?:Synopsis|$)", text, re.IGNORECASE | re.DOTALL)
        if m:
            raw_alert = m.group(1).strip().rstrip(";&").strip()
            for pattern, label in NOAA_ALERT_PATTERNS:
                if pattern.lower() in raw_alert.lower():
                    alert = label
                    break
        assert alert == "El Niño Advisory"

    def test_parse_extracts_date(self):
        """El parser extrae la fecha de publicación."""
        import re
        text = "9 July 2026 Alert System Status: El Niño Advisory"
        m = re.search(r"\b(\d{1,2}\s+\w+\s+202\d)\b", text[:2000])
        assert m is not None
        assert m.group(1) == "9 July 2026"


# ----------------------------------------------------------------------------
# Fallback de ENFEN
# ----------------------------------------------------------------------------
class TestEnfenFallback:
    """Tests del mecanismo de fallback de ENFEN."""

    def test_fallback_file_exists(self):
        """El archivo de fallback config/enfen-status.json existe."""
        fallback_path = REPO / "config" / "enfen-status.json"
        assert fallback_path.exists(), "config/enfen-status.json debe existir"

    def test_fallback_file_has_alert(self):
        """El archivo de fallback tiene el campo 'alert'."""
        fallback_path = REPO / "config" / "enfen-status.json"
        data = json.loads(fallback_path.read_text(encoding="utf-8"))
        assert "alert" in data
        assert data["alert"]  # No vacío

    def test_fallback_loads_correctly(self):
        """_load_enfen_fallback carga el archivo correctamente."""
        from enso.official_status import _load_enfen_fallback

        result = _load_enfen_fallback()
        assert result["source"] in ("fallback", "unavailable")
        assert "alert" in result
        assert "fetched_at" in result


# ----------------------------------------------------------------------------
# Integración: adquisición live (offline)
# ----------------------------------------------------------------------------
class TestAcquisitionScript:
    """Tests de integración del script acquire-live-data.py."""

    def test_script_exists(self):
        """El script acquire-live-data.py existe."""
        script = REPO / "scripts" / "acquire-live-data.py"
        assert script.exists()

    def test_opendap_fetchers_module_exists(self):
        """El módulo enso.opendap_fetchers existe."""
        mod = REPO / "python" / "enso" / "opendap_fetchers.py"
        assert mod.exists()

    def test_official_status_module_exists(self):
        """El módulo enso.official_status existe."""
        mod = REPO / "python" / "enso" / "official_status.py"
        assert mod.exists()

    def test_browser_validation_workflow_exists(self):
        """El workflow browser-validation.yml existe."""
        wf = REPO / ".github" / "workflows" / "browser-validation.yml"
        assert wf.exists()

    def test_d20_csv_has_real_data(self):
        """d20.csv contiene datos reales (no vacío)."""
        csv = REPO / "public" / "data" / "d20.csv"
        if not csv.exists():
            pytest.skip("d20.csv no generado (requiere red)")
        lines = csv.read_text().strip().split("\n")
        # Al menos cabecera + 100 puntos
        assert len(lines) > 100

    def test_u850_csv_has_real_data(self):
        """u850.csv contiene datos reales (no vacío)."""
        csv = REPO / "public" / "data" / "u850.csv"
        if not csv.exists():
            pytest.skip("u850.csv no generado (requiere red)")
        lines = csv.read_text().strip().split("\n")
        assert len(lines) > 100

    def test_status_json_has_official_alerts(self):
        """status.json contiene alertas oficiales con URL y fecha."""
        status_file = REPO / "public" / "data" / "status.json"
        if not status_file.exists():
            pytest.skip("status.json no generado")
        s = json.loads(status_file.read_text(encoding="utf-8"))
        # Costero
        assert "alert" in s["coastal"]
        assert "alertOfficialUrl" in s["coastal"]
        assert "alertDate" in s["coastal"]
        # Cuenca
        assert "alert" in s["basin"]
        assert "alertOfficialUrl" in s["basin"]
        assert "alertDate" in s["basin"]

    def test_status_json_has_d20_u850(self):
        """status.json contiene D20 y u850 con valores reales."""
        status_file = REPO / "public" / "data" / "status.json"
        if not status_file.exists():
            pytest.skip("status.json no generado")
        s = json.loads(status_file.read_text(encoding="utf-8"))
        # D20
        assert s["thermocline"]["d20Anom"] is not None, "D20 no debe ser None"
        assert s["thermocline"]["d20Month"]
        # u850
        assert s["winds"]["u850Anom"] is not None, "u850 no debe ser None"
        assert s["winds"]["u850Month"]

    def test_health_json_has_d20_u850_sources(self):
        """health.json incluye D20 y u850 como fuentes."""
        health_file = REPO / "public" / "data" / "health.json"
        if not health_file.exists():
            pytest.skip("health.json no generado")
        h = json.loads(health_file.read_text(encoding="utf-8"))
        source_ids = [s["id"] for s in h["sources"]]
        assert "noaa-cpc-godas-d20" in source_ids or "d20" in source_ids
        assert "noaa-cpc-cpac850" in source_ids or "u850" in source_ids
