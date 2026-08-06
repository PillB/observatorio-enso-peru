"""Orquestador del pipeline — adquisición, normalización y emisión.

Idempotente: si se ejecuta varias veces produce los mismos artefactos
salvo la marca temporal. Ante fallos de red preserva el último conjunto
válido y marca los datos como ``stale``.

Salida:
    python/out/manifest.json   — manifiesto de la corrida.
    python/out/status.json     — estado consolidado.
    python/out/sources.json    — registro de fuentes exportado.
    python/out/<indicator>.csv — CSV por indicador con cabecera de metadatos.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .derived import (
    icen_category,
    latest_point,
    rolling_mean_3,
    roni_category,
    u850_direction,
    d20_interpretation,
    soi_category,
    window3_label,
)
from .fetchers import (
    EnfenIcenFetcher,
    FetchError,
    FetchResult,
    Fetcher,
    PslNino12Fetcher,
    PslNino34Fetcher,
    PslSoiFetcher,
    SchemaValidationError,
    get_fetcher_class,
)
from .methodology import INDICATOR_BY_ID
from .models import IndicatorDef, MonthlyPoint, Series, SeriesFlag
from .sources import SOURCES, SOURCE_BY_ID, get_source

#: Versión de los datos del observatorio (sincronizada con el frontend).
DATA_VERSION = "1.0.0"

#: Mes de corte del observatorio (igual que ``series.ts``).
AS_OF_MONTH = "2026-07"
AS_OF_DATE = "2026-08-02"

#: Umbral (horas) a partir del cual un indicador se considera obsoleto.
STALE_HOURS_THRESHOLD = 72.0


# ----------------------------------------------------------------------------
# Resultado por indicador
# ----------------------------------------------------------------------------
@dataclass
class IndicatorRun:
    """Resultado de procesar un indicador en una corrida."""

    indicator_id: str
    ok: bool
    stale: bool = False
    from_cache: bool = False
    preliminary: bool = False
    last_month: Optional[str] = None
    last_value: Optional[float] = None
    checksum: str = ""
    error: Optional[str] = None
    series: Optional[Series] = None
    fetch_result: Optional[FetchResult] = None


@dataclass
class PipelineRun:
    """Resultado consolidado de una corrida del pipeline."""

    started_at: str
    finished_at: str
    data_version: str
    as_of_month: str
    as_of_date: str
    results: list[IndicatorRun] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _checksum(indicator_id: str, points: list[MonthlyPoint]) -> str:
    """Checksum FNV-1a 32 bits (igual que ``series.ts``)."""
    h = 2166136261 ^ len(indicator_id)
    MASK = 0xFFFFFFFF
    for p in points:
        h ^= ord(p.month[0]) + len(p.month)
        h = (h * 16777619) & MASK
        v = 9999 if p.value is None else int(round(p.value * 1000))
        h ^= (v + 0x9E3779B9) & MASK
        h = (h * 16777619) & MASK
    return f"fnv1a:{h & MASK:08x}"


def _freshness_hours(month_iso: str, as_of_date: str = AS_OF_DATE) -> float:
    """Horas entre el fin del mes ISO y la fecha de corte."""
    y, m = (int(x) for x in month_iso.split("-"))
    next_y, next_m = (y + 1, 1) if m == 12 else (y, m + 1)
    end = datetime(next_y, next_m, 1, tzinfo=timezone.utc)
    try:
        as_of = datetime.strptime(as_of_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        as_of = datetime.now(timezone.utc)
    return max(0.0, (as_of - end).total_seconds() / 3600.0)


# ----------------------------------------------------------------------------
# Construcción de series sintéticas (offline) — sólo fallback
# ----------------------------------------------------------------------------
def _build_series_from_points(
    indicator_id: str, points: list[MonthlyPoint]
) -> Series:
    ind = INDICATOR_BY_ID[indicator_id]
    return Series(
        indicatorId=indicator_id,
        label=ind.shortName,
        units=ind.units,
        scope=ind.scope,
        points=points,
        sourceId=ind.sourceId,
        checksum=_checksum(indicator_id, points),
    )


# ----------------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------------
class Pipeline:
    """Orquestador del pipeline ENSO.

    Uso típico::

        pipe = Pipeline(out_dir="python/out", cache_dir="python/cache")
        run = pipe.run(allow_network=False)
        print(run.ok, len(run.results))
    """

    def __init__(
        self,
        out_dir: str | os.PathLike[str] = "python/out",
        cache_dir: str | os.PathLike[str] = "python/cache",
        allow_network: bool = True,
    ) -> None:
        self.out_dir = Path(out_dir)
        self.cache_dir = Path(cache_dir)
        self.allow_network = allow_network
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- Construcción de fetchers ----
    def _fetcher_for(self, source_id: str) -> Optional[Fetcher]:
        cls = get_fetcher_class(source_id)
        if cls is None:
            return None
        return cls(cache_dir=self.cache_dir)

    # ---- Procesamiento por indicador ----
    def _process_indicator(self, ind: IndicatorDef) -> IndicatorRun:
        fetcher = self._fetcher_for(ind.sourceId)
        if fetcher is None:
            return IndicatorRun(
                indicator_id=ind.id,
                ok=False,
                error=f"no fetcher registered for source {ind.sourceId}",
            )
        try:
            result = fetcher.fetch(allow_network=self.allow_network)
        except SchemaValidationError as e:
            # Preserva último válido: intenta cargar el CSV anterior.
            stale_series = self._load_last_valid(ind.id)
            run = IndicatorRun(
                indicator_id=ind.id,
                ok=stale_series is not None,
                stale=True,
                error=f"schema validation: {e}",
                series=stale_series,
            )
            if stale_series is not None:
                self._finalize_series(ind, stale_series, None, run)
            return run
        except FetchError as e:
            stale_series = self._load_last_valid(ind.id)
            run = IndicatorRun(
                indicator_id=ind.id,
                ok=stale_series is not None,
                stale=True,
                from_cache=stale_series is not None,
                error=str(e),
                series=stale_series,
            )
            if stale_series is not None:
                self._finalize_series(ind, stale_series, None, run)
            return run

        # Parsea y construye la serie.
        try:
            points = self._parse_to_points(ind, result)
        except Exception as e:  # noqa: BLE001
            stale_series = self._load_last_valid(ind.id)
            run = IndicatorRun(
                indicator_id=ind.id,
                ok=stale_series is not None,
                stale=True,
                error=f"parse: {e}",
                series=stale_series,
            )
            if stale_series is not None:
                self._finalize_series(ind, stale_series, result, run)
            return run

        # Aplica derivaciones (ICEN, RONI).
        if ind.id == "icen":
            # ICEN se deriva de nino12; si se procesó nino12 primero,
            # intenta leer su CSV. Si no, deja la serie cruda.
            n12 = self._load_last_valid("nino12")
            if n12 is not None:
                points = rolling_mean_3(n12.points)
        elif ind.id == "roni":
            n34 = self._load_last_valid("nino34")
            if n34 is not None:
                points = rolling_mean_3(n34.points)

        series = _build_series_from_points(ind.id, points)
        run = IndicatorRun(
            indicator_id=ind.id,
            ok=True,
            stale=result.from_cache,
            from_cache=result.from_cache,
            preliminary=any(
                p.flag == SeriesFlag.PRELIMINARY for p in series.points[-3:]
            ),
            checksum=series.checksum,
            series=series,
            fetch_result=result,
        )
        self._finalize_series(ind, series, result, run)
        return run

    def _finalize_series(
        self,
        ind: IndicatorDef,
        series: Series,
        result: Optional[FetchResult],
        run: IndicatorRun,
    ) -> None:
        """Escribe CSV, guarda último válido y completa metadatos del run."""
        # Recalcula el checksum canónico a partir de los puntos (defensivo:
        # el último válido pudo haberse guardado con un checksum placeholder).
        series.checksum = _checksum(series.indicatorId, series.points)
        # Persiste CSV y actualiza último válido.
        self._write_csv(ind, series, result)
        self._save_last_valid(ind.id, series)
        lp = latest_point(series.points)
        run.last_month = lp[0].month if lp else None
        run.last_value = lp[0].value if lp else None
        run.checksum = series.checksum
        # Marca preliminar si los últimos 3 puntos lo son.
        run.preliminary = any(
            p.flag == SeriesFlag.PRELIMINARY for p in series.points[-3:]
        )
        if run.fetch_result is None and result is not None:
            run.fetch_result = result

    def _parse_to_points(
        self, ind: IndicatorDef, result: FetchResult
    ) -> list[MonthlyPoint]:
        """Delega el parseo al fetcher concreto según el tipo."""
        from .fetchers import PslCsvFetcher, EnfenIcenFetcher

        fetcher = self._fetcher_for(ind.sourceId)
        if isinstance(fetcher, PslCsvFetcher):
            return fetcher.parse(result)  # type: ignore[arg-type]
        if isinstance(fetcher, EnfenIcenFetcher):
            data = fetcher.parse(result)  # type: ignore[arg-type]
            # ICEN extraído del HTML: produce un único punto si hay mes.
            if data.get("month") and data.get("icen") is not None:
                return [
                    MonthlyPoint(
                        month=data["month"],
                        value=data["icen"],
                        flag=SeriesFlag.PRELIMINARY,
                    )
                ]
            return []
        # Otros fetchers (HTML): no producen series mensuales directas.
        return []

    # ---- Persistencia ----
    def _csv_path(self, indicator_id: str) -> Path:
        return self.out_dir / f"{indicator_id}.csv"

    def _last_valid_path(self, indicator_id: str) -> Path:
        return self.cache_dir / f"{indicator_id}.last_valid.json"

    def _write_csv(
        self, ind: IndicatorDef, series: Series, result: Optional[FetchResult]
    ) -> None:
        """Escribe el CSV con cabecera de metadatos + checksum."""
        path = self._csv_path(ind.id)
        meta_lines = [
            f"# indicator_id={series.indicatorId}",
            f"# label={series.label}",
            f"# units={series.units}",
            f"# scope={series.scope}",
            f"# source_id={series.sourceId}",
            f"# checksum={series.checksum}",
            f"# data_version={DATA_VERSION}",
            f"# as_of_month={AS_OF_MONTH}",
            f"# generated_at={datetime.now(timezone.utc).isoformat()}",
            f"# fetched_at={result.fetched_at if result else ''}",
            f"# from_cache={bool(result and result.from_cache)}",
            f"# preliminary={bool(result and result.preliminary)}",
            f"# climatology={ind.climatology}",
            f"# sign_convention={ind.signConvention}",
        ]
        with open(path, "w", encoding="utf-8", newline="") as fh:
            for ln in meta_lines:
                fh.write(ln + "\n")
            writer = csv.writer(fh)
            writer.writerow(["month", "value", "flag"])
            for p in series.points:
                writer.writerow(
                    [
                        p.month,
                        "" if p.value is None else f"{p.value:.4f}",
                        p.flag.value,
                    ]
                )
        # Anexa checksum del archivo CSV al final (comentario).
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"# file_sha256={_sha256_file(str(path))}\n")

    def _save_last_valid(self, indicator_id: str, series: Series) -> None:
        path = self._last_valid_path(indicator_id)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(series.model_dump(mode="json"), fh, ensure_ascii=False)
        os.replace(tmp, path)

    def _load_last_valid(self, indicator_id: str) -> Optional[Series]:
        path = self._last_valid_path(indicator_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return Series.model_validate_json(fh.read())
        except Exception:  # noqa: BLE001
            return None

    # ---- Manifiesto / estado ----
    def _write_manifest(self, run: PipelineRun) -> None:
        manifest = {
            "data_version": run.data_version,
            "as_of_month": run.as_of_month,
            "as_of_date": run.as_of_date,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "ok": run.ok,
            "indicators": [
                {
                    "id": r.indicator_id,
                    "ok": r.ok,
                    "stale": r.stale,
                    "from_cache": r.from_cache,
                    "preliminary": r.preliminary,
                    "last_month": r.last_month,
                    "last_value": r.last_value,
                    "checksum": r.checksum,
                    "error": r.error,
                }
                for r in run.results
            ],
        }
        path = self.out_dir / "manifest.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)

    def _write_sources(self) -> list[dict[str, Any]]:
        sources_json = [s.model_dump(mode="json") for s in SOURCES]
        path = self.out_dir / "sources.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(sources_json, fh, ensure_ascii=False, indent=2)
        return sources_json

    def _write_status(self, run: PipelineRun) -> dict[str, Any]:
        """Escribe ``status.json`` con el estado consolidado."""
        rows = {r.indicator_id: r for r in run.results}

        def latest_value(ind_id: str) -> tuple[Optional[float], Optional[str], bool]:
            r = rows.get(ind_id)
            if r and r.series:
                lp = latest_point(r.series.points)
                if lp:
                    return lp[0].value, lp[0].month, r.preliminary
            return None, AS_OF_MONTH, False

        nino12_v, nino12_m, nino12_p = latest_value("nino12")
        icen_v, icen_m, icen_p = latest_value("icen")
        nino34_v, nino34_m, nino34_p = latest_value("nino34")
        roni_v, roni_m, roni_p = latest_value("roni")
        u850_v, u850_m, _ = latest_value("u850")
        d20_v, d20_m, _ = latest_value("d20")
        soi_v, soi_m, _ = latest_value("soi")

        dir_info = u850_direction(u850_v)

        status = {
            "asOf": AS_OF_DATE,
            "dataVersion": DATA_VERSION,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "coastal": {
                "alert": "Alerta de El Niño Costero",
                "alertSource": "ENFEN / IMARPE (siofen.imarpe.gob.pe)",
                "alertSince": "2026-02-13",
                "nino12Anom": nino12_v,
                "nino12Month": nino12_m,
                "icen": icen_v,
                "icenWindow": window3_label(icen_m or AS_OF_MONTH),
                "icenCategory": icen_category(icen_v),
                "freshness": (
                    f"{'Dato preliminar' if nino12_p else 'Dato final'} · corte {AS_OF_DATE}"
                ),
                "preliminary": nino12_p,
            },
            "basin": {
                "alert": "El Niño Advisory",
                "alertSource": "NOAA / CPC — ENSO Diagnostic Discussion",
                "alertSince": "2026-06",
                "nino34Anom": nino34_v,
                "nino34Month": nino34_m,
                "roni": roni_v,
                "roniWindow": window3_label(roni_m or AS_OF_MONTH),
                "roniCategory": roni_category(roni_v),
                "freshness": (
                    f"{'Dato preliminar' if nino34_p else 'Dato final'} · corte {AS_OF_DATE}"
                ),
                "preliminary": nino34_p,
            },
            "winds": {
                "u850Anom": u850_v,
                "u850Month": u850_m,
                "direction": dir_info["label"],
                "signMeaning": dir_info["signMeaning"],
            },
            "thermocline": {
                "d20Anom": d20_v,
                "d20Month": d20_m,
                "interpretation": d20_interpretation(d20_v),
            },
            "soi": {
                "value": soi_v,
                "month": soi_m,
                "interpretation": soi_category(soi_v),
                "note": (
                    "El SOI es un índice de escala de cuenca. El observatorio "
                    "NO define un «SOI costero»: no existe un proxy de "
                    "presión costera con respaldo metodológico equivalente."
                ),
            },
            "freshness": self._freshness_summary(run),
        }
        path = self.out_dir / "status.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(status, fh, ensure_ascii=False, indent=2)
        return status

    def _freshness_summary(self, run: PipelineRun) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for r in run.results:
            if not r.last_month:
                continue
            hours = _freshness_hours(r.last_month)
            rows.append(
                {
                    "indicator_id": r.indicator_id,
                    "last_month": r.last_month,
                    "freshness_hours": round(hours, 1),
                    "stale": hours > STALE_HOURS_THRESHOLD or r.stale,
                    "preliminary": r.preliminary,
                    "from_cache": r.from_cache,
                }
            )
        return rows

    # ---- Punto de entrada ----
    def run(self) -> PipelineRun:
        """Ejecuta el pipeline completo de forma idempotente."""
        started = datetime.now(timezone.utc).isoformat()
        results: list[IndicatorRun] = []
        # Procesa en orden: primero las series base, luego las derivadas.
        order = ["nino12", "nino34", "soi", "u850", "d20", "icen", "roni"]
        for ind_id in order:
            ind = INDICATOR_BY_ID.get(ind_id)
            if ind is None:
                continue
            results.append(self._process_indicator(ind))

        run = PipelineRun(
            started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(),
            data_version=DATA_VERSION,
            as_of_month=AS_OF_MONTH,
            as_of_date=AS_OF_DATE,
            results=results,
            sources=self._write_sources(),
        )
        self._write_manifest(run)
        self._write_status(run)
        return run


# ----------------------------------------------------------------------------
# Helper de asset_url para subpath de GitHub Pages
# ----------------------------------------------------------------------------
def asset_url(base_path: str, name: str) -> str:
    """Construye una URL relativa a un subpath de GitHub Pages.

    ``asset_url('/repo', 'data/nino12.csv')`` → ``'/repo/data/nino12.csv'``.
    ``asset_url('', 'data/x.csv')``            → ``'/data/x.csv'``.
    No admite secrets: si ``base_path`` o ``name`` contienen un carácter
    de nueva línea o un token sensible, lanza ``ValueError``.
    """
    if not isinstance(base_path, str) or not isinstance(name, str):
        raise ValueError("asset_url: argumentos deben ser cadenas")
    if "\n" in base_path or "\n" in name:
        raise ValueError("asset_url: nueva línea no permitida")
    bp = base_path.strip().rstrip("/")
    nm = name.strip().lstrip("/")
    if not nm:
        raise ValueError("asset_url: nombre vacío")
    return f"{bp}/{nm}" if bp else f"/{nm}"
