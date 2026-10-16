"""Input validation must remain a standalone Python stage."""
from copy import deepcopy
from pathlib import Path

from pipeline.ingestion import read_delivery
from pipeline.quality import validate_delivery
from pipeline.settings import load_config, Config, strict_integer

ROOT = Path(__file__).resolve().parents[1]


def quality_result():
    cfg = load_config(ROOT / "config.yaml")
    return validate_delivery(read_delivery(cfg), cfg.values["mapping"], cfg.values["quality"])


def test_integer_parser_preserves_null_not_zero():
    assert strict_integer(None) is None
    assert strict_integer("0") == 0


def test_no_plan_disappears_during_validation():
    result = quality_result()
    assert len(result.plans) == 8
    assert len(set(row["record_id"] for row in result.plans)) == 8
    assert result.rejected_count == 4
    assert len(result.quarantine) == 4


def test_duplicate_koppelcodes_do_not_merge_records():
    records = [r for r in quality_result().plans if r["koppelcode"] == "SYN_A"]
    assert len(records) == 2
    assert records[0]["record_id"] != records[1]["record_id"]


def test_quality_findings_have_severity_and_rule_id():
    issues = quality_result().issues
    assert issues
    assert all(i["severity"] in ("ERROR", "WARNING", "INFO") for i in issues)
    assert all(i["rule_id"].startswith("DQ-") for i in issues)


def test_source_values_not_silently_overwritten():
    result = quality_result()
    assert all("raw_payload_json" in row for row in result.plans)
    assert any(i["severity"] == "ERROR" for i in result.issues)
