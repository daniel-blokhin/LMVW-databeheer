"""Plan polygons, coordinate systems and authoritative source relationships."""
from pathlib import Path

import pytest
from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform

from pipeline.geospatial import RD, WGS84, checked_geometry, query_scope, geojson_wgs84, match_sources
from pipeline.ingestion import read_delivery
from pipeline.quality import validate_delivery
from pipeline.settings import PipelineError, load_config
from pipeline.sources import fetch_sources

ROOT = Path(__file__).resolve().parents[1]


def test_rd_and_wgs84_conversion():
    polygon = box(150000, 450000, 150100, 450100)
    lnglat = transform(Transformer.from_crs(RD, WGS84, always_xy=True).transform, polygon)
    restored = checked_geometry(lnglat, crs=WGS84)
    assert restored.hausdorff_distance(polygon) < 0.002
    assert '"Polygon"' in geojson_wgs84(polygon)


def test_invalid_polygon_rejected():
    with pytest.raises(PipelineError):
        checked_geometry("POINT (150000 450000)")


def test_geo_queries_are_bounded():
    polygon = box(150000, 450000, 150100, 450100)
    scope, tiles = query_scope([polygon], buffer_m=50, tile_size_m=500,
                              max_tiles=20, max_scope_km2=1)
    assert scope.covers(polygon)
    assert tiles


def test_spatial_relations_are_reproducible_offline(tmp_path):
    config = load_config(ROOT / "config.yaml")
    delivery = read_delivery(config)
    quality = validate_delivery(delivery, config.values["mapping"], config.values["quality"])
    plans = [r for r in quality.plans if r["processing_status"] != "REJECTED" and r["record_id"] in quality.geometries]
    geoms = {p["record_id"]: quality.geometries[p["record_id"]] for p in plans}
    sources = fetch_sources(config, plans, geoms, tmp_path, "2026-10-16T09:00:00Z")
    relations, issues = match_sources(plans, geoms, sources, 0.01)
    assert len(relations["plan_bag_vbo"]) == 8
    assert len(relations["plan_bag_pand"]) == 11
    assert len(relations["plan_brk_perceel"]) == 7
    assert len(relations["plan_dso"]) == 8
    assert all(r["substantively_confirmed"] is False for r in relations["plan_dso"])
