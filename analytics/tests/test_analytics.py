"""Tests for metrics, filtering, export integrity, geometries and CRS preparation."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest
from shapely.geometry import Polygon, MultiPolygon, box

from analytics.data import (DEMO, DataError, load_bundle, filter_plans, eligible, kpis, total,
                            phasing, source_metrics, source_objects, scoped_issues, breakdown)
from analytics.charts import _segments, _trace, vector_map, dashboard_charts, quality_charts
from analytics.report import make_html
from analytics.prepare_input import prepare_csv


@pytest.fixture(scope="module")
def demo():
    return load_bundle(DEMO)


def rewrite(path, name, transform):
    f = path / (name + ".csv")
    frame = pd.read_csv(f, dtype=str, keep_default_na=False)
    transform(frame).to_csv(f, index=False)
    manifest = json.loads((path / "manifest.json").read_text())
    manifest["files"][f.name]["sha256"] = hashlib.sha256(f.read_bytes()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest))


def input_file(tmp_path, extra=None):
    path = tmp_path / "raw.csv"
    row = {"Gemeente": "Fictief", "Koppelcode": "000123", "Polygon_WKT": box(150000,450000,150010,450010).wkt,
           "Opmerking": 'regel een; "waarde"\nregel twee', "Aantal": "0", "Onbekend": ""}
    row.update(extra or {})
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row), delimiter=";")
        writer.writeheader(); writer.writerow(row)
    return path, row


def test_expected_demo_kpis(demo):
    result = kpis(demo["plans"])
    assert (result["input"], result["accepted"], result["rejected"]) == (36, 30, 6)
    assert result["gross"] == 1590
    assert result["net"] == 1493


def test_shared_area_key_does_not_collapse_records(demo):
    shared = demo["plans"][demo["plans"]["koppelcode"].eq("DEMO_000")]
    assert len(shared) == 2
    assert kpis(shared)["gross"] == 24 + 38


def test_leading_zero_source_identifiers(demo):
    ids = demo["bag_panden"]["bag_pand_id"]
    assert ids.str.len().eq(16).all() and ids.str.startswith("0000").all()


def test_empty_scope_is_not_zero_capacity(demo):
    result = kpis(filter_plans(demo, []))
    assert result["input"] == 0 and result["gross"] is None and result["acceptance_rate"] is None


def test_rejected_records_never_contribute(demo):
    plans = demo["plans"].copy()
    expected = kpis(plans)["gross"]
    plans.loc[plans.processing_status.eq("REJECTED"), "gross_capacity"] = 999999
    assert kpis(plans)["gross"] == expected


def test_all_rejected_has_no_population(demo):
    modified = copy.deepcopy(demo)
    modified["plans"]["processing_status"] = "REJECTED"
    modified["source_status"]["status"] = "NOT_QUERIED"
    assert kpis(modified["plans"])["gross"] is None
    assert source_metrics(modified, modified["plans"])["coverage_pct"].isna().all()
    fig, _ = vector_map(modified, modified["plans"])
    assert "Geen geldige geometrie" in fig.layout.annotations[0].text
    html = make_html(modified, modified["plans"])
    assert "Geen records toegelaten" in html and "n.v.t." in html


def test_municipality_filter_applies_to_children(demo):
    plans = filter_plans(demo, ["Demo Waterdam"])
    assert len(plans) == 12
    assert scoped_issues(demo, plans).municipality.eq("Demo Waterdam").all()
    objects = source_objects(demo, plans, "BAG panden")
    assert objects.record_id.isin(plans.record_id).all()


def test_hardness_filter_is_exact(demo):
    plans = filter_plans(demo, hardness=["HARD"])
    assert plans.hard_soft.eq("HARD").all()
    assert len(plans) < len(demo["plans"])


def test_negative_net_is_preserved(demo):
    negative = eligible(demo["plans"])
    negative = negative[negative.net_capacity_calculated.lt(0)]
    assert len(negative) == 1 and kpis(negative)["net"] == -5


def test_five_year_periods_are_not_split(demo):
    phases = phasing(demo, demo["plans"])
    multi = phases[phases.period_start.ne(phases.period_end)]
    assert len(multi) == 2
    assert multi.period_label.tolist() == ["2036 t/m 2040", "2041 t/m 2045"]
    assert len(phases) == 12


def test_missing_phase_not_zero_filled(demo):
    phases = phasing(demo, demo["plans"])
    assert phases["missing"].sum() == 1
    assert total(pd.Series([pd.NA], dtype="Float64")) is None


def test_all_missing_breakdown_stays_null(demo):
    modified = copy.deepcopy(demo)
    modified["plan_breakdown"].loc[:, "homes"] = pd.NA
    result = breakdown(modified, modified["plans"], "housing_type")
    assert result.homes.isna().all()
    assert result["missing"].sum() == 90


def test_distinct_object_and_relation_counts_are_different(demo):
    metric = source_metrics(demo, demo["plans"]).set_index("source").loc["DSO documenten"]
    assert metric["objects"] == 33
    assert metric["relations"] == 62


def test_disabled_source_is_not_measured_zero(demo):
    modified = copy.deepcopy(demo)
    modified["source_status"].loc[modified["source_status"].source_name.eq("DSO"), "status"] = "DISABLED"
    metric = source_metrics(modified, modified["plans"]).set_index("source").loc["DSO documenten"]
    assert pd.isna(metric["objects"]) and pd.isna(metric["coverage_pct"])


def test_private_payload_is_not_loaded(demo):
    assert "raw_payload_json" not in demo["plans"]
    assert "source_value" not in demo["dq_issues"]


def test_tampered_csv_rejected(tmp_path):
    path = tmp_path / "bundle"
    shutil.copytree(DEMO, path)
    with (path / "plans.csv").open("a") as stream: stream.write("\n")
    with pytest.raises(DataError, match="gewijzigd"):
        load_bundle(path)


def test_mixed_runs_rejected(tmp_path):
    path = tmp_path / "bundle"
    shutil.copytree(DEMO, path)
    rewrite(path, "plans", lambda f: f.assign(run_id="other-run"))
    with pytest.raises(DataError, match="Run-identifiers"):
        load_bundle(path)


def test_invalid_numeric_is_not_coerced_to_null(tmp_path):
    path = tmp_path / "bundle"
    shutil.copytree(DEMO, path)
    rewrite(path, "plans", lambda f: f.assign(gross_capacity="not-a-number"))
    with pytest.raises(DataError, match="datatype"):
        load_bundle(path)


def test_raw_plans_cannot_be_dashboard_input(tmp_path):
    with pytest.raises(DataError, match="database_ready"):
        load_bundle(tmp_path)


def test_all_polygon_parts_and_holes_are_preserved():
    polygon = Polygon([(0,0),(10,0),(10,10),(0,10)], holes=[[(2,2),(4,2),(4,4),(2,4)]])
    geom = MultiPolygon([polygon, box(20,20,30,30)])
    assert len(list(_segments(geom))) == 3


def test_map_rejects_wrong_crs_and_escapes_tooltip():
    rows = pd.DataFrame([{"geometry_wkt": box(150000,450000,150010,450010).wkt, "crs": "EPSG:28992",
                          "label": "<script>alert('bad')</script>"}])
    trace, omitted = _trace(rows, "Map", "label")
    assert omitted == 0 and "&lt;script&gt;" in trace.text[0]
    rows["crs"] = "EPSG:4326"
    _, omitted = _trace(rows, "Map", "label")
    assert omitted == 1


def test_report_is_self_contained(demo):
    html = make_html(demo, demo["plans"])
    assert '<script src=' not in html and "chart-map-detail" in html
    assert "Plotly.newPlot" in html and 'id="kpi-gross"' in html
    assert 'source_value' not in html


def test_all_charts_support_empty_selection(demo):
    empty = filter_plans(demo, [])
    assert len(dashboard_charts(demo, empty)) == 5
    assert len(quality_charts(demo, empty)) == 4


def test_crs_copy_preserves_business_fields(tmp_path):
    source, row = input_file(tmp_path)
    before = source.read_bytes()
    target = tmp_path / "prepared.csv"
    assert prepare_csv(source, target, crs="EPSG:28992") == 1
    with target.open(encoding="utf-8-sig", newline="") as stream:
        updated = next(csv.DictReader(stream, delimiter=";"))
    assert updated.pop("CRS") == "EPSG:28992"
    assert updated == row and source.read_bytes() == before


def test_helper_refuses_overwrite(tmp_path):
    source, _ = input_file(tmp_path)
    with pytest.raises(ValueError, match="nieuw uitvoerbestand"):
        prepare_csv(source, source, crs="EPSG:28992")


def test_helper_refuses_conflicting_crs(tmp_path):
    source, _ = input_file(tmp_path, {"CRS": "EPSG:4326"})
    with pytest.raises(ValueError, match="wijkt af"):
        prepare_csv(source, tmp_path / "copy.csv", crs="EPSG:28992")


def test_helper_selects_wgs84_explicitly_and_preserves_old_geometry(tmp_path):
    wgs = box(4.3,52,4.4,52.1).wkt
    source, row = input_file(tmp_path, {"Polygon_WKT_4326": wgs})
    target = tmp_path / "copy.csv"
    prepare_csv(source, target, crs="EPSG:4326", wkt_column="Polygon_WKT_4326")
    with target.open(encoding="utf-8-sig", newline="") as stream:
        updated = next(csv.DictReader(stream, delimiter=";"))
    assert updated["Polygon_WKT"] == wgs
    assert updated["Original_Polygon_WKT"] == row["Polygon_WKT"]


def test_helper_does_not_silently_strip_markdown(tmp_path):
    source, _ = input_file(tmp_path, {"**2027": "0"})
    with pytest.raises(ValueError, match="Markdown"):
        prepare_csv(source, tmp_path / "copy.csv", crs="EPSG:28992")


def test_all_modules_parse_without_optional_streamlit_dependency():
    import ast
    for file in Path(__file__).resolve().parents[1].glob("*.py"):
        ast.parse(file.read_text(encoding="utf-8"), filename=str(file))


@pytest.mark.parametrize("page", ["Portefeuille", "Kaarten en plan", "Datakwaliteit"])
def test_streamlit_pages_when_installed(monkeypatch, page):
    testing = pytest.importorskip("streamlit.testing.v1", reason="Optional Streamlit UI dependency is not installed")
    monkeypatch.delenv("LMVW_BUNDLE_DIR", raising=False)
    app = Path(__file__).resolve().parents[1] / "app.py"
    at = testing.AppTest.from_file(str(app), default_timeout=20).run()
    assert not at.exception
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception
