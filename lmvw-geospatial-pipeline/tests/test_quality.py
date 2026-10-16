from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook

from lmvw_pipeline.common import PipelineError, strict_integer
from lmvw_pipeline.config import load_config
from lmvw_pipeline.intake import _read_rows, read_delivery
from lmvw_pipeline.validation.engine import validate_delivery


@pytest.mark.parametrize("value,expected", [(None, None), ("", None), ("  ", None), ("0", 0), (0, 0),
                                            ("1.0", 1), ("-7", -7), ("1e2", 100), (2**63-1, 2**63-1)])
def test_strict_integer_valid(value, expected):
    assert strict_integer(value) == expected


@pytest.mark.parametrize("value", [True, False, "nan", "inf", "-inf", "1.5", "1,000", "abc", 2**63])
def test_strict_integer_rejects_lossy_values(value):
    with pytest.raises(ValueError):
        strict_integer(value)


def test_row_conservation_and_quarantine(quality):
    assert len(quality.plans) == 8
    assert quality.rejected_count == 4
    assert len(quality.quarantine) == 4
    assert len({p["record_id"] for p in quality.plans}) == 8
    assert sum(i["severity"] == "ERROR" for i in quality.issues) == 5


def test_shared_area_key_is_not_a_primary_key(quality):
    shared = [p for p in quality.plans if p["koppelcode"] == "SYN_A"]
    assert len(shared) == 2
    assert shared[0]["record_id"] != shared[1]["record_id"]
    assert {p["processing_status"] for p in shared} == {"WARNING"}
    assert shared[0]["geometry_wkt"] == shared[1]["geometry_wkt"]


def test_negative_net_is_valid(quality):
    plan = next(p for p in quality.plans if p["koppelcode"] == "SYN_H")
    assert plan["net_capacity_calculated"] == -3
    assert plan["net_capacity_reported"] == -3
    assert plan["processing_status"] == "READY"


def test_unknown_confidentiality_never_becomes_public(quality):
    plan = next(p for p in quality.plans if p["koppelcode"] == "SYN_E2")
    assert plan["confidential"] is None
    assert plan["processing_status"] == "REJECTED"


def test_invalid_count_not_zero_and_sum_checks_unevaluable(quality):
    plan = next(p for p in quality.plans if p["koppelcode"] == "SYN_E4")
    assert plan["gross_capacity"] is None
    assert '"ten"' in plan["raw_payload_json"]
    assert quality.rule_results["DQ-SUM-001"]["not_evaluable"] == 1


def test_five_year_bucket_not_fabricated_into_annual_data(quality):
    rid = quality.plans[2]["record_id"]
    phase = [p for p in quality.phasing if p["record_id"] == rid]
    assert len(phase) == 12
    assert next(p for p in phase if p["period_start"] == 2036)["period_end"] == 2040
    assert not any(p["period_start"] == 2037 for p in phase)


def test_exact_duplicate_is_retained_and_rejected(delivery, mapping, rules):
    delivery.records[1]["raw"] = deepcopy(delivery.records[0]["raw"])
    result = validate_delivery(delivery, mapping, rules)
    assert len(result.plans) == 8
    assert all(result.plans[i]["processing_status"] == "REJECTED" for i in (0, 1))
    assert sum(i["rule_id"] == "DQ-DUP-002" for i in result.issues) == 2


def test_missing_mapping_header_aborts(delivery, mapping, rules):
    del mapping["fields"]["municipality"]
    mapping["fields"]["municipality"] = "Required but absent"
    with pytest.raises(PipelineError, match="schema"):
        validate_delivery(delivery, mapping, rules)


def test_formula_without_cached_result(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Planlijst"
    sheet.append(["Koppelcode", "Bruto Plancapaciteit"])
    sheet.append(["SYN_TEST", "=5+5"])
    path = tmp_path / "formula.xlsx"
    workbook.save(path)
    rows, headers = _read_rows(path, sheet="Planlijst", delimiter=";")
    assert rows[0]["source_row_number"] == 2
    assert rows[0]["missing_formula_cache"] == ["Bruto Plancapaciteit"]
    assert rows[0]["formulae"]["Bruto Plancapaciteit"] == "=5+5"


def test_missing_crs_not_guessed(delivery, mapping, rules):
    delivery.records[0]["raw"]["CRS"] = ""
    result = validate_delivery(delivery, mapping, rules)
    assert result.plans[0]["geometry_wkt"] is None
    assert result.plans[0]["processing_status"] == "REJECTED"


def test_overlap_phasing_header_rejected(delivery, mapping, rules):
    delivery.source_metadata["source_columns"].append("2035 t/m 2039")
    with pytest.raises(PipelineError, match="overlap"):
        validate_delivery(delivery, mapping, rules)


@pytest.mark.parametrize("section,key,value", [("geo", "max_tiles", 0), ("geo", "include_rejected_plans", "false"),
                                                ("geo", "buffer_m", float("nan")), ("http", "max_pages", 0),
                                                ("http", "attempts", 50), ("sources", "dso", "yes")])
def test_configuration_bounds(demo_config, tmp_path, section, key, value):
    data = deepcopy(demo_config.values)
    data[section][key] = value
    path = tmp_path / "test.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(PipelineError):
        load_config(path)


def test_missing_core_capacity_is_rejected(delivery, mapping, rules):
    delivery.records[0]["raw"][mapping["fields"]["gross_capacity"]] = ""
    result = validate_delivery(delivery, mapping, rules)
    assert result.plans[0]["processing_status"] == "REJECTED"
    assert any(i["rule_id"] == "DQ-COM-003" and i["record_id"] == result.plans[0]["record_id"] for i in result.issues)
