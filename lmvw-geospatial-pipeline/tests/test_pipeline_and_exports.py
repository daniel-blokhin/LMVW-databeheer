from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml
from shapely.geometry import shape

from lmvw_pipeline.cli import main
from lmvw_pipeline.common import ContractError, SourceError, read_json, write_json
from lmvw_pipeline.contracts import BY_NAME, TABLES, Column, schema_document, sql_ddl
from lmvw_pipeline.exporting import export_bundle, read_table, validate_tables, validate_value, verify_bundle
from lmvw_pipeline.geometry import RD_URI, geometry_key
from lmvw_pipeline.pipeline import run_pipeline


@pytest.fixture
def completed(root, tmp_path):
    return run_pipeline(root / "configs/demo.yaml", output_dir=tmp_path / "runs")


def test_end_to_end_output(completed):
    verified = verify_bundle(completed.bundle)
    assert verified["tables"] == 17
    assert verified["counts"]["plans"] == 8
    assert verified["counts"]["dq_issues"] == 10
    assert verified["counts"]["quarantine"] == 4
    assert completed.status == "COMPLETE_WITH_REJECTIONS"
    assert (completed.run_dir / "quality_summary.json").is_file()


def test_csv_native_ids_not_numeric(completed):
    rows = read_table(completed.bundle / "bag_panden.csv", "bag_panden")
    assert all(isinstance(p["bag_pand_id"], str) and p["bag_pand_id"].startswith("0000") for p in rows)


def test_csv_roundtrip_commas_quotes_newlines_unicode_empty_and_null(completed, tmp_path):
    tables = {spec.name: read_table(completed.bundle / (spec.name + ".csv"), spec.name) for spec in TABLES}
    tables["plans"][0]["plan_name"] = 'Unicode \u00e9, comma and "quote"\nNew line'
    tables["plans"][0]["municipality"] = ""
    tables["plans"][1]["municipality"] = None
    tables["dso_document_text"][0]["publication_text"] = ('A, "B"\n\u00e9' * 30000)
    target = tmp_path / "second"
    target.mkdir()
    bundle = export_bundle(tables, target, metadata={"synthetic": True})
    result = read_table(bundle / "plans.csv", "plans")
    assert result[0]["plan_name"] == tables["plans"][0]["plan_name"]
    assert result[0]["municipality"] == "" and result[1]["municipality"] is None
    assert read_table(bundle / "dso_document_text.csv", "dso_document_text")[0]["publication_text"] == tables["dso_document_text"][0]["publication_text"]


def test_manifest_tamper_rejected(completed):
    with (completed.bundle / "plans.csv").open("a") as stream:
        stream.write("tampered\n")
    with pytest.raises(ContractError, match="checksum"):
        verify_bundle(completed.bundle)


def test_duplicate_pk_and_orphan_fk_rejected_before_export(completed, tmp_path):
    tables = {spec.name: read_table(completed.bundle / (spec.name + ".csv"), spec.name) for spec in TABLES}
    tables["plans"].append(dict(tables["plans"][0]))
    with pytest.raises(ContractError, match="duplicate"):
        export_bundle(tables, tmp_path, metadata={})
    assert not (tmp_path / "database_ready").exists()
    tables["plans"].pop()
    tables["plan_bag_pand"][0]["bag_pand_id"] = "9999999999999999"
    with pytest.raises(ContractError, match="Orphan"):
        validate_tables(tables)


@pytest.mark.parametrize("value,col", [("\\N", Column("value")), ("x\x00y", Column("value")),
                                      ("long", Column("value", length=2)), (True, Column("count", "int")),
                                      ("2026-01-01T00:00:00", Column("date", "datetime")),
                                      ("NaN", Column("decimal", "decimal")), ("1.0000000000001", Column("decimal", "decimal")),
                                      ("{bad json", Column("document", "json"))])
def test_unrepresentable_sql_values_blocked(value, col):
    with pytest.raises(ContractError):
        validate_value(value, col)


def test_decimal38_and_microsecond_timestamp_supported():
    validate_value("99999999999999999999999999.999999999999", Column("decimal", "decimal"))
    validate_value("2026-01-01T00:00:00.123456Z", Column("date", "datetime"))
    assert "DATETIMEOFFSET(7)" in sql_ddl()
    assert json.loads(json.dumps(schema_document())) == schema_document()


def test_cli_validate_has_no_api_dependency(root, tmp_path, capsys):
    code = main(["validate", "--config", str(root / "configs/live.example.yaml"), "--output-dir", str(tmp_path)])
    # The live example points at missing private files; no key request or network occurs.
    assert code == 1
    assert "credential" not in capsys.readouterr().err.lower()
    code = main(["validate", "--config", str(root / "configs/demo.yaml"), "--output-dir", str(tmp_path)])
    assert code == 2
    run_dirs = [p for p in tmp_path.iterdir() if (p / "validation/summary.json").is_file()]
    assert run_dirs and all(not (p / "database_ready").exists() for p in run_dirs)


def test_cli_run_fail_on_dq_still_writes_valid_bundle(root, tmp_path, capsys):
    code = main(["run", "--config", str(root / "configs/demo.yaml"), "--output-dir", str(tmp_path), "--fail-on-dq"])
    assert code == 2
    bundles = list(tmp_path.glob("*/database_ready"))
    assert len(bundles) == 1
    assert main(["verify-bundle", str(bundles[0])]) == 0


def test_source_failure_retains_validation_but_no_success_bundle(root, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise SourceError("Synthetic controlled failure")
    monkeypatch.setattr("lmvw_pipeline.pipeline.fetch_sources", fail)
    with pytest.raises(SourceError):
        run_pipeline(root / "configs/demo.yaml", output_dir=tmp_path)
    run = next(tmp_path.iterdir())
    assert (run / "validation/summary.json").is_file()
    assert not (run / "database_ready").exists()
    assert read_json(run / "run_context.json")["status"] == "FAILED"


def test_live_credentials_preflight_occurs_before_any_request(root, tmp_path):
    with pytest.raises(Exception, match="Missing runtime credential"):
        run_pipeline(root / "configs/demo.yaml", output_dir=tmp_path, mode="live")
    run = next(tmp_path.iterdir())
    assert not (run / "raw").exists()


def test_deterministic_business_output_across_runs(root, tmp_path):
    first = run_pipeline(root / "configs/demo.yaml", output_dir=tmp_path)
    second = run_pipeline(root / "configs/demo.yaml", output_dir=tmp_path)
    assert first.run_dir != second.run_dir
    for spec in TABLES:
        if spec.name == "pipeline_run":
            continue
        left = read_table(first.bundle / (spec.name + ".csv"), spec.name)
        right = read_table(second.bundle / (spec.name + ".csv"), spec.name)
        for rows in (left, right):
            for row in rows:
                del row["run_id"]
        assert left == right


def test_mocked_live_request_cache_and_real_replay(root, tmp_path, monkeypatch):
    """Exercise the actual transport, OGC adapters and DSO client, then replay offline."""
    import requests
    fixtures = {name: read_json(root / f"data/sample/api/{name}.json") for name in ("bag_panden", "bag_vbo", "brk", "dso")}
    fake = "unit-test-only-not-a-real-credential"
    for name in ("DSO_API_KEY_PRE", "RUIMTELIJKE_PLANNEN_API_KEY"):
        monkeypatch.setenv(name, fake)
    monkeypatch.setattr("lmvw_pipeline.http.time.sleep", lambda _: None)
    calls = []
    class Response:
        status_code = 200
        headers = {"Content-Crs": RD_URI}
        def __init__(self, payload):
            self.payload = payload
        def iter_content(self, chunk_size):
            yield json.dumps(self.payload).encode()
        def close(self):
            pass
    def request(session, method, url, **kwargs):
        calls.append((method, url))
        path = urlsplit(url).path
        if "api.pdok.nl" in url:
            assert "x-api-key" not in kwargs["headers"]
            collection = path.split("/collections/")[1].split("/")[0]
            table = {"pand": "bag_panden", "verblijfsobject": "bag_vbo", "perceel": "brk"}[collection]
            features = fixtures[table]["data"]["features"]
            if "/items/" in path:
                return Response(next(f for f in features if f["id"] == path.rsplit("/", 1)[1]))
            return Response({"type": "FeatureCollection", "features": features, "numberMatched": len(features), "links": []})
        assert kwargs["headers"]["x-api-key"] == fake
        if path.endswith("/_zoek"):
            resource = path.split("/")[-2]
            body = kwargs["json"]
            geom = body.get("geometrie") or body["_geo"]["intersects"]
            items = fixtures["dso"]["areas"][geometry_key(shape(geom))].get(resource, [])
            assert parse_qs(urlsplit(url).query)["page"] == ["1"]
            return Response({"_embedded": {resource: items}, "page": {"totalElements": len(items), "totalPages": 1}})
        if "/geometrieen/" in path:
            return Response(fixtures["dso"]["geometries"][path.rsplit("/", 1)[1]])
        if path.endswith("/documentstructuur"):
            return Response(next(iter(fixtures["dso"]["document_structures"].values())))
        raise AssertionError("Unexpected mocked source operation")
    monkeypatch.setattr(requests.Session, "request", request)
    live = run_pipeline(root / "configs/demo.yaml", output_dir=tmp_path / "live", mode="live")
    assert len(calls) > 10
    assert len([url for method, url in calls if "documentstructuur" in url]) == 1
    for path in live.run_dir.rglob("*.json"):
        assert fake not in path.read_text()
    for name in ("DSO_API_KEY_PRE", "RUIMTELIJKE_PLANNEN_API_KEY"):
        monkeypatch.delenv(name)
    def blocked(*args, **kwargs):
        raise AssertionError("Replay must never perform network requests")
    monkeypatch.setattr(requests.Session, "request", blocked)
    replay = run_pipeline(root / "configs/demo.yaml", output_dir=tmp_path / "replay", mode="replay", replay_from=live.run_dir)
    for spec in TABLES:
        if spec.name in {"pipeline_run", "source_status"}:
            continue
        left = read_table(live.bundle / (spec.name + ".csv"), spec.name)
        right = read_table(replay.bundle / (spec.name + ".csv"), spec.name)
        for rows in (left, right):
            for row in rows:
                del row["run_id"]
        assert left == right
