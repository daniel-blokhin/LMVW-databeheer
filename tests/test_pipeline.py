"""Small end-to-end demonstration through SQL Server-ready CSV exports."""
import csv
from pathlib import Path

from pipeline.export import verify_bundle
from pipeline.run import run_pipeline, main
from pipeline.settings import read_json

ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_creates_database_ready_csvs(tmp_path):
    run = run_pipeline(ROOT / "config.yaml", output_dir=tmp_path)
    assert run.status == "COMPLETE_WITH_REJECTIONS"
    assert run.counts["input_plans"] == 8
    assert run.counts["rejected_plans"] == 4
    assert verify_bundle(run.bundle)["status"] == "VERIFIED"
    assert (run.bundle / "schema.sql").exists()
    with (run.bundle / "plans.csv").open(encoding="utf-8", newline="") as f:
        plans = list(csv.DictReader(f))
    assert len(plans) == 8
    assert sum(r["processing_status"] == "REJECTED" for r in plans) == 4
    assert any(r["processing_status"] != "REJECTED" for r in plans)


def test_standalone_quality_stage_makes_no_api_output(tmp_path):
    run = run_pipeline(ROOT / "config.yaml", validate_only=True, output_dir=tmp_path)
    assert run.bundle is None
    assert run.counts["input_plans"] == 8
    assert (run.run_dir / "validation" / "issues.json").exists()
    assert not (run.run_dir / "raw").exists()
    assert len(read_json(run.run_dir / "validation" / "quarantine.json")) == 4


def test_cli_run_and_verify(tmp_path):
    assert main(["run", "--config", str(ROOT / "config.yaml"), "--output-dir", str(tmp_path)]) == 0
    export = next(tmp_path.glob("*/database_ready"))
    assert main(["verify", str(export)]) == 0
