"""Contratos RED para fuentes rápidas y documentos institucionales.

Las pruebas usan muestras pequeñas y deterministas: ningún test depende de la
red. Los canarios de red se ejecutan por separado y con presupuesto acotado.
"""

from __future__ import annotations

import json

import pytest

from enso.document_sources import (
    DocumentQuarantined,
    discover_latest_enfen_communique,
    parse_enfen_communique_html,
    parse_imarpe_bulletin_pages,
    parse_siofen_bulletin_index,
    parse_enfen_wordpress_posts,
    parse_official_enfen_pages,
    validate_pdf_payload,
)
from enso.rapid_sources import (
    RapidSourceSchemaError,
    build_pmel_tabledap_url,
    build_oisst_griddap_url,
    parse_erddap_grid_csv,
    parse_pmel_table_csv,
)
from enso.publication_validator import validate_status_series_agreement


OISST_SAMPLE = """time,depth,latitude,longitude,anom
UTC,m,degrees_north,degrees_east,Celsius
2026-08-06T12:00:00Z,0.0,-5.0,190.0,1.0
2026-08-06T12:00:00Z,0.0,0.0,190.0,2.0
2026-08-06T12:00:00Z,0.0,5.0,190.0,3.0
"""


def test_oisst_query_is_bounded_and_metadata_explicit():
    url = build_oisst_griddap_url(
        dataset="ncdc_oisst_v2_avhrr_prelim_by_time_zlev_lat_lon",
        variable="anom",
        lat_min=-5,
        lat_max=5,
        lon_min=190,
        lon_max=240,
    )
    assert "[last]" in url
    assert "[(last)]" not in url
    assert "anom" in url
    assert "(-5):(5)" in url
    assert "(190):(240)" in url
    assert "ncdc_oisst_v2_avhrr_prelim" in url


def test_oisst_parser_preserves_period_units_and_area_weighted_mean():
    result = parse_erddap_grid_csv(
        OISST_SAMPLE,
        variable="anom",
        expected_units="Celsius",
        now="2026-08-07T00:00:00Z",
    )
    assert result["valid_period"] == "2026-08-06"
    assert result["units"] == "Celsius"
    assert result["point_count"] == 3
    assert result["value"] == pytest.approx(2.0)
    assert result["schema_fingerprint"].startswith("sha256:")


def test_oisst_parser_quarantines_changed_units_and_duplicate_cells():
    changed_units = OISST_SAMPLE.replace("Celsius", "kelvin")
    with pytest.raises(RapidSourceSchemaError, match="unit"):
        parse_erddap_grid_csv(changed_units, "anom", "Celsius", now="2026-08-07T00:00:00Z")
    duplicate = OISST_SAMPLE + "2026-08-06T12:00:00Z,0.0,0.0,190.0,4.0\n"
    with pytest.raises(RapidSourceSchemaError, match="duplicate"):
        parse_erddap_grid_csv(duplicate, "anom", "Celsius", now="2026-08-07T00:00:00Z")


def test_pmel_parser_requires_identity_units_quality_and_station_coverage():
    sample = """station,longitude,latitude,time,ISO_6,QI_5006
,degrees_east,degrees_north,UTC,m,
0n140w,220.0,0.0,2026-07-02T12:00:00Z,141.9,2.0
2n140w,220.0,2.0,2026-07-02T12:00:00Z,132.4,2.0
"""
    result = parse_pmel_table_csv(
        sample,
        value_column="ISO_6",
        expected_units="m",
        quality_column="QI_5006",
        accepted_quality={1, 2},
        now="2026-08-07T00:00:00Z",
    )
    assert result["valid_period"] == "2026-07-02"
    assert result["station_count"] == 2
    assert result["value"] == pytest.approx(137.15)
    assert result["recommended_role"] == "CORROBORATION_ONLY"


def test_pmel_query_is_time_space_and_result_bounded():
    url = build_pmel_tabledap_url(
        dataset="pmelTaoDyIso",
        columns=["station", "longitude", "latitude", "time", "ISO_6", "QI_5006"],
        start_date="2026-05-01",
    )
    assert "time%3E%3D2026-05-01" in url
    assert "latitude%3E%3D-5" in url
    assert "longitude%3C%3D240" in url
    assert "orderByMax%28%22station,time%22%29" in url


def test_pdf_validator_rejects_html_substitution_even_with_pdf_mime():
    with pytest.raises(DocumentQuarantined, match="PDF magic"):
        validate_pdf_payload(b"<html><title>502 Bad Gateway</title></html>", "application/pdf")


def test_wordpress_discovery_returns_official_post_and_document_assets():
    payload = [{
        "id": 2130,
        "date": "2026-07-17T22:50:35",
        "modified": "2026-07-20T08:15:25",
        "link": "https://enfen.imarpe.gob.pe/2026/07/17/comunicado/",
        "title": {"rendered": "COMUNICADO OFICIAL ENFEN N° 13-2026 — Alerta de El Niño Costero"},
        "content": {"rendered": (
            '<p>ENFEN mantiene el estado de “Alerta de El Niño Costero”.</p>'
            '<a href="https://enfen.imarpe.gob.pe/download/comunicado/?wpdmdl=2128">PDF</a>'
        )},
    }]
    result = parse_enfen_wordpress_posts(json.dumps(payload))
    assert result["publication_date"] == "2026-07-17"
    assert result["alert"] == "Alerta de El Niño Costero"
    assert result["post_id"] == 2130
    assert result["document_urls"] == [
        "https://enfen.imarpe.gob.pe/download/comunicado/?wpdmdl=2128"
    ]
    assert result["evidence_text"]


def test_enfen_html_fallback_discovers_and_parses_official_communique():
    index = '''
    <a href="https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-12-2026/">
      Comunicado Oficial ENFEN N° 12-2026
    </a>
    <a href="https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-13-2026/">
      Comunicado Oficial ENFEN N° 13-2026
    </a>
    '''
    detail_url = discover_latest_enfen_communique(index)
    assert detail_url.endswith("comunicado-oficial-enfen-n-13-2026/")

    detail = '''
    <article>
      <h1>17 Jul Comunicado Oficial ENFEN N° 13-2026</h1>
      <p>Estado de sistema de alerta: Alerta de El Niño Costero.</p>
      <a href="https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-13-2026/?wpdmdl=2128">
        Descargar PDF
      </a>
    </article>
    '''
    result = parse_enfen_communique_html(detail, source_url=detail_url)
    assert result["publication_date"] == "2026-07-17"
    assert result["alert"] == "Alerta de El Niño Costero"
    assert result["source_method"] == "official_html_document_page"
    assert result["document_urls"] == [
        "https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-13-2026/?wpdmdl=2128"
    ]


def test_official_document_parser_requires_page_period_and_unambiguous_icen():
    pages = [
        "COMUNICADO OFICIAL ENFEN N° 13-2026. Estado: Alerta de El Niño Costero.",
        "El ICEN correspondiente a junio de 2026 fue +1,24 °C.",
    ]
    result = parse_official_enfen_pages(pages, source_url="https://enfen.imarpe.gob.pe/doc.pdf")
    assert result["alert"] == "Alerta de El Niño Costero"
    assert result["icen"] == pytest.approx(1.24)
    assert result["icen_period"] == "2026-06"
    assert result["evidence"]["icen"]["page"] == 2

    ambiguous = pages + ["El ICEN correspondiente a mayo de 2026 fue +0,81 °C."]
    with pytest.raises(DocumentQuarantined, match="ambiguous"):
        parse_official_enfen_pages(ambiguous, source_url="https://enfen.imarpe.gob.pe/doc.pdf")


def test_unavailable_icen_does_not_require_or_retain_a_fabricated_csv(tmp_path):
    (tmp_path / "status.json").write_text(json.dumps({
        "coastal": {"nino12Anom": None, "icen": None},
        "basin": {"nino34Anom": None, "roni": None},
        "soi": {"value": None}, "winds": {"u850Anom": None},
        "thermocline": {"d20Anom": None},
    }))
    assert not any("icen.csv" in error for error in validate_status_series_agreement(tmp_path))


def test_siofen_index_discovers_only_official_expected_pdf_assets():
    html = '''<a href="https://siofen-admin.imarpe.gob.pe/img/productoArchivo/BDO/2026/BOL_IMARPE_BDO_2026-07-08.pdf">BDO</a>
    <a href="https://evil.example/BDO/2026/fake.pdf">fake</a>'''
    assets = parse_siofen_bulletin_index(html, bulletin_type="BDO")
    assert len(assets) == 1
    assert assets[0]["publication_date"] == "2026-07-08"
    assert assets[0]["url"].startswith("https://siofen-admin.imarpe.gob.pe/")


def test_bdo_parser_extracts_dated_range_with_page_evidence():
    pages = [
        "BOLETÍN DIARIO OCEANOGRÁFICO. IMARPE para el 07 de julio de 2026. "
        "Se registraron valores de TSM entre 16,7 °C (Atico), y 23,4 °C (San José)."
    ]
    result = parse_imarpe_bulletin_pages(
        pages, bulletin_type="BDO",
        source_url="https://siofen-admin.imarpe.gob.pe/img/productoArchivo/BDO/2026/BOL_IMARPE_BDO_2026-07-08.pdf",
    )
    assert result["valid_period"] == "2026-07-07"
    assert result["sst_min"] == pytest.approx(16.7)
    assert result["sst_max"] == pytest.approx(23.4)
    assert result["evidence"]["sst_range"]["page"] == 1


def test_bulletin_parser_quarantines_missing_period_or_reversed_range():
    with pytest.raises(DocumentQuarantined, match="period"):
        parse_imarpe_bulletin_pages(
            ["BOLETÍN DIARIO OCEANOGRÁFICO. TSM entre 16,7 °C y 23,4 °C."],
            bulletin_type="BDO", source_url="https://siofen-admin.imarpe.gob.pe/a.pdf",
        )
    with pytest.raises(DocumentQuarantined, match="range"):
        parse_imarpe_bulletin_pages(
            ["BOLETÍN DIARIO OCEANOGRÁFICO para el 07 de julio de 2026. "
             "valores de TSM entre 29,0 °C (A), y 12,0 °C (B)."],
            bulletin_type="BDO", source_url="https://siofen-admin.imarpe.gob.pe/a.pdf",
        )
