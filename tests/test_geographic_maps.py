"""Tests for real plan polygons, CRS handling, layers and exclusions.

Run from repository root: python -m pytest tests/test_geographic_maps.py -q
"""
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon, box

from analytics.data import DEMO, load_bundle, eligible
from analytics.geographic_maps import _geometry, geo_map, MAP_STYLES


def test_rd_polygon_reprojects_to_geographic_coordinates_and_preserves_hole():
    shape = Polygon(
        [(150000, 450000), (150100, 450000), (150100, 450100), (150000, 450100)],
        [[(150020, 450020), (150030, 450020), (150030, 450030), (150020, 450030)]],
    )
    transformed = _geometry(pd.Series({"geometry_wkt": shape.wkt, "crs": "EPSG:28992"}))
    assert len(transformed.interiors) == 1
    assert 4 <= transformed.centroid.x <= 7
    assert 51 <= transformed.centroid.y <= 53


def test_unknown_crs_not_guessed():
    with pytest.raises(ValueError):
        _geometry(pd.Series({"geometry_wkt": Point(150000, 450000).wkt, "crs": "unknown"}))


def test_overview_has_true_map_polygons_not_xy_traces():
    bundle = load_bundle(DEMO)
    fig, omitted = geo_map(bundle, bundle["plans"])
    assert omitted >= 0
    assert fig.layout.map.style == "carto-positron"
    assert fig.data
    assert all(trace.type in ("choroplethmap", "scattermap") for trace in fig.data)
    # No rejected record can appear in overview; geometry can be omitted if bad.
    assert sum(len(trace.locations) for trace in fig.data if trace.type == "choroplethmap") <= len(eligible(bundle["plans"]))


def test_detail_has_source_layers_and_zoom_is_based_on_plan_only():
    bundle = load_bundle(DEMO)
    selected = eligible(bundle["plans"]).iloc[0]["record_id"]
    fig, omitted = geo_map(bundle, bundle["plans"], str(selected))
    assert omitted >= 0
    assert any(trace.name == "Plancontour" for trace in fig.data)
    assert fig.layout.map.zoom >= 2


def test_empty_scope_produces_explanatory_figure():
    bundle = load_bundle(DEMO)
    fig, skipped = geo_map(bundle, bundle["plans"].iloc[:0])
    assert skipped == 0
    assert "Geen geldige geometrie" in fig.layout.annotations[0].text


def test_map_style_explicitly_restricted():
    bundle = load_bundle(DEMO)
    with pytest.raises(ValueError):
        geo_map(bundle, bundle["plans"], map_style="https://unknown.example/tiles")
    assert "Zonder achtergrondtegels (offline)" in MAP_STYLES
