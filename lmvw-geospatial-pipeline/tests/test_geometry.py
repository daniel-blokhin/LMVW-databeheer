import json

import pytest
from pyproj import Transformer
from shapely.geometry import Point, box
from shapely.ops import transform

from lmvw_pipeline.adapters.collect import fetch_sources
from lmvw_pipeline.common import PipelineError
from lmvw_pipeline.geometry import RD, WGS84, checked_geometry, geojson_wgs84, query_scope
from lmvw_pipeline.matching import match_sources


@pytest.mark.parametrize("value", ["not wkt", "POLYGON EMPTY", "POINT (150000 450000)",
                                  "POLYGON ((0 0,1 0,1 1,0 0))",
                                  "POLYGON M ((150000 450000 1,150100 450000 1,150100 450100 1,150000 450000 1))",
                                  "POLYGON Z ((150000 450000 1,150100 450000 1,150100 450100 1,150000 450000 1))"])
def test_invalid_plan_geometry_rejected(value):
    with pytest.raises(PipelineError):
        checked_geometry(value)


def test_crs_transform_roundtrip():
    original = box(150000, 450000, 150100, 450100)
    wgs = transform(Transformer.from_crs(RD, WGS84, always_xy=True).transform, original)
    restored = checked_geometry(wgs, crs=WGS84)
    assert restored.hausdorff_distance(original) < 0.002
    document = json.loads(geojson_wgs84(original))
    assert document["type"] == "Polygon"
    assert 3 < document["coordinates"][0][0][0] < 8
    assert 50 < document["coordinates"][0][0][1] < 54


def test_query_scope_is_buffered_and_bounded():
    geom = box(150000, 450000, 150100, 450100)
    scope, tiles = query_scope([geom], buffer_m=50, tile_size_m=500, max_tiles=50, max_scope_km2=1)
    assert scope.covers(geom)
    assert len(tiles) <= 4
    with pytest.raises(PipelineError):
        query_scope([box(100000, 400000, 200000, 500000)], buffer_m=0, tile_size_m=500, max_tiles=2, max_scope_km2=1)


def test_spatial_and_authoritative_matching(demo_config, quality, tmp_path):
    plans = [p for p in quality.plans if p["processing_status"] != "REJECTED"]
    geoms = {p["record_id"]: quality.geometries[p["record_id"]] for p in plans}
    sources = fetch_sources(demo_config, plans, geoms, tmp_path, "2026-10-16T09:00:00Z")
    links, issues = match_sources(plans, geoms, sources, 0.01)
    assert len(sources.tables["bag_verblijfsobjecten"]) == 4  # excludes office use and outside scope
    assert len(sources.tables["bag_panden"]) == 5  # includes official parent far outside query scope
    first = plans[0]["record_id"]
    vbo = next(r for r in links["plan_bag_vbo"] if r["record_id"] == first and r["bag_verblijfsobject_id"].endswith("0003"))
    assert vbo["spatial_relation"] == "BOUNDARY_INCLUDED"
    pand = next(r for r in links["plan_bag_pand"] if r["record_id"] == first and r["bag_pand_id"].endswith("0002"))
    assert pand["match_method"] == "OFFICIAL_BAG_VBO_PAND"
    assert pand["overlap_area_m2"] is None
    assert pand["via_vbo_count"] == 1
    assert not any(r["brk_local_id"] == "SYN-PARCEL-3" and r["record_id"] == first for r in links["plan_brk_perceel"])
    parcel = next(r for r in links["plan_brk_perceel"] if r["record_id"] == first and r["brk_local_id"] == "SYN-PARCEL-2")
    assert float(parcel["intersection_area_m2"]) == 2000
    assert float(parcel["overlap_pct_plan"]) == 20
    assert all(r["substantively_confirmed"] is False for r in links["plan_dso"])
    assert len(issues) == 2
    assert {r["relation_status"] for r in links["plan_dso"]} >= {"SPATIAL_MATCH", "API_CANDIDATE_UNVERIFIED", "API_CANDIDATE_OUTSIDE"}
    assert len(links["plan_bag_pand"]) == len({(r["record_id"], r["bag_pand_id"]) for r in links["plan_bag_pand"]})
