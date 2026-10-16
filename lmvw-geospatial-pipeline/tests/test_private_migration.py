import copy
import csv
import runpy
import zipfile

import geopandas as gpd
import pytest
import yaml
from shapely.geometry import box

from lmvw_pipeline.adapters.collect import fetch_sources
from lmvw_pipeline.common import PipelineError, SourceError, read_json
from lmvw_pipeline.config import Config
from lmvw_pipeline.intake import read_delivery
from lmvw_pipeline.pipeline import run_pipeline


def test_geopackage_area_key_join_retains_plan_rows(demo_config, tmp_path):
    path = tmp_path / "areas.gpkg"
    data = gpd.GeoDataFrame({"Koppelcode": ["SYN_A"]}, geometry=[box(150000, 450000, 150100, 450100)], crs="EPSG:28992")
    data.to_file(path, layer="areas", driver="GPKG")
    values = copy.deepcopy(demo_config.values)
    values["input"].update(geometries=str(path), geometry_layer="areas")
    delivery = read_delivery(Config(demo_config.path, values))
    assert len(delivery.records) == 8 and len(delivery.geometry_by_key) == 1
    assert delivery.uses_geometry_file is True


def test_geopackage_ambiguous_keys_are_not_dissolved(demo_config, tmp_path):
    path = tmp_path / "areas.gpkg"
    data = gpd.GeoDataFrame({"Koppelcode": ["SYN_A", "SYN_A"]}, geometry=[box(150000, 450000, 150100, 450100)] * 2, crs="EPSG:28992")
    data.to_file(path, layer="areas", driver="GPKG")
    values = copy.deepcopy(demo_config.values)
    values["input"].update(geometries=str(path), geometry_layer="areas")
    with pytest.raises(PipelineError, match="non-unique"):
        read_delivery(Config(demo_config.path, values))


def test_snapshot_mode_reprocesses_source_csvs(root, demo_config, quality, tmp_path):
    plans = [p for p in quality.plans if p["processing_status"] != "REJECTED"]
    geoms = {p["record_id"]: quality.geometries[p["record_id"]] for p in plans}
    original = fetch_sources(demo_config, plans, geoms, tmp_path, "2026-10-16T09:00:00Z")
    directory = tmp_path / "private"
    directory.mkdir()
    names = {"bag_panden": "bag_panden_db.csv", "bag_verblijfsobjecten": "bag_verblijfsobjecten_db.csv",
             "bag_vbo_pand": "bag_verblijfsobject_pand_relatie_db.csv", "brk_percelen": "brk_percelen_db.csv"}
    for table, filename in names.items():
        rows = original.tables[table]
        with (directory / filename).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    values = copy.deepcopy(demo_config.values)
    values["sources"].update(mode="snapshots", snapshot_dir=str(directory), dso=False, rp=False)
    values["input"]["plans"] = str(root / "data/sample/plans.csv")
    values["mapping"] = str(root / "configs/columns.yaml")
    values["quality"] = str(root / "configs/quality.yaml")
    path = tmp_path / "snapshots.yaml"
    path.write_text(yaml.safe_dump(values))
    result = run_pipeline(path, output_dir=tmp_path / "runs")
    summary = read_json(result.run_dir / "quality_summary.json")
    assert summary["table_counts"]["bag_vbo_pand"] == 5
    assert summary["table_counts"]["brk_percelen"] == 4
    assert {s["status"] for s in summary["source_statuses"] if s["source_name"] in {"DSO", "RP"}} == {"DISABLED"}
    assert len(read_json(result.run_dir / "run_context.json")["source_input_hashes"]) == 4


def test_private_import_allowlist_never_extracts_code_or_traversal(root, tmp_path):
    helper = runpy.run_path(str(root / "scripts/import_legacy_data.py"))
    path = tmp_path / "original.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name in helper["NAMES"]:
            prefix = "source/output_lmvw/bag/run/" if name.endswith("_db.csv") else "0. LMVW data/"
            archive.writestr(prefix + name, "synthetic test bytes only")
        archive.writestr("original_notebook.ipynb", '{"code": "never copied"}')
        archive.writestr("../outside.txt", "never extracted")
    target = tmp_path / "private"
    report = helper["import_legacy"](path, target)
    assert report["files"] == 6
    assert len(list(target.iterdir())) == 7  # six inputs plus private manifest
    assert not (tmp_path / "outside.txt").exists()
    assert not (target / "original_notebook.ipynb").exists()
    with pytest.raises(PipelineError, match="already exists"):
        helper["import_legacy"](path, target)


def test_snapshot_mode_does_not_fabricate_missing_dso(demo_config, quality, tmp_path):
    values = copy.deepcopy(demo_config.values)
    values["sources"]["mode"] = "snapshots"
    plans = [p for p in quality.plans if p["processing_status"] != "REJECTED"]
    geoms = {p["record_id"]: quality.geometries[p["record_id"]] for p in plans}
    with pytest.raises(SourceError, match="No DSO response"):
        fetch_sources(Config(demo_config.path, values), plans, geoms, tmp_path, "2026-01-01T00:00:00Z")
