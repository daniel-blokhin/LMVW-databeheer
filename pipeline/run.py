"""Run the LMVW pipeline: ingest -> validate -> APIs -> spatial joins -> CSV exports.

Examples:
    python -m pipeline.run run --config config.yaml
    python -m pipeline.run validate --config config.yaml
    python -m pipeline.run run --mode live --plans data/private/plans.xlsx \
        --geometries data/private/areas.gpkg --geometry-layer plans
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .settings import Config, PipelineError, load_config, utc_now, write_json, json_text
from .ingestion import read_delivery
from .quality import validate_delivery
from .sources import SourceData, fetch_sources
from .geospatial import match_sources
from .export import BY_NAME, export_bundle, verify_bundle


@dataclass
class RunResult:
    run_dir: Path
    bundle: Path | None
    status: str
    counts: dict[str, int]


def run_pipeline(config_path: Path, *, validate_only: bool = False,
                 mode: str | None = None, plans: Path | None = None,
                 geometries: Path | None = None, geometry_layer: str | None = None,
                 output_dir: Path | None = None) -> RunResult:
    """Preserve original records and isolate invalid plans before enrichment.

    No data is published here. The only final artifacts are SQL Server-ready CSVs.
    """
    config = load_config(config_path)
    options = copy.deepcopy(config.values)
    if mode:
        options["sources"]["mode"] = mode
    if plans:
        options["input"]["plans"] = str(plans.resolve())
    if geometries:
        options["input"]["geometries"] = str(geometries.resolve())
    if geometry_layer:
        options["input"]["geometry_layer"] = geometry_layer
    config = Config(config.path, options)
    mapping, rules = options["mapping"], options["quality"]
    if not isinstance(rules.get("version"), str):
        raise PipelineError("Quality rules must contain a version string")

    folder = output_dir.resolve() if output_dir else config.resolve(options["output_dir"])
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_id = str(uuid.uuid4())
    run_dir = folder / run_id
    run_dir.mkdir(mode=0o700)
    started = utc_now()
    try:
        print("[1/5] Reading housing plan delivery", flush=True)
        delivery = read_delivery(config)
        print("[2/5] Checking data quality (Python)", flush=True)
        quality = validate_delivery(delivery, mapping, rules)
        if len(quality.plans) != len(delivery.records):
            raise PipelineError("Validation must retain all source records")
        counts = {
            "input_plans": len(quality.plans),
            "valid_plans": len(quality.plans) - quality.rejected_count,
            "rejected_plans": quality.rejected_count,
            "quality_issues": len(quality.issues),
        }
        validation = run_dir / "validation"
        validation.mkdir(mode=0o700)
        write_json(validation / "issues.json", quality.issues)
        write_json(validation / "quarantine.json", quality.quarantine)
        write_json(validation / "summary.json", {"counts": counts, "rules": quality.rule_results})
        if validate_only:
            print("Quality-only run complete:", validation, flush=True)
            return RunResult(run_dir, None, "VALIDATED", counts)

        # Rejected records remain in the export but must not trigger API enrichment.
        eligible = [p for p in quality.plans if p["record_id"] in quality.geometries
                    and p["processing_status"] != "REJECTED"]
        eligible_geo = {p["record_id"]: quality.geometries[p["record_id"]] for p in eligible}
        print("[3/5] Collecting BAG, BRK and DSO source data", flush=True)
        snapshot = utc_now() if config.mode == "live" else (options.get("snapshot_utc") or utc_now())
        try:
            instant = datetime.fromisoformat(str(snapshot).replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError()
            snapshot = instant.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except ValueError:
            raise PipelineError("snapshot_utc must be a timezone-aware ISO timestamp") from None
        if eligible:
            sources = fetch_sources(config, eligible, eligible_geo, run_dir, snapshot)
        else:
            sources = SourceData()
            sources.statuses = [{"source_name": name.upper(), "status": "NOT_QUERIED", "environment": "NOT_APPLICABLE",
                                 "record_count": 0, "message": "No valid plans"}
                                for name in ("bag", "brk", "dso")]

        print("[4/5] Matching source objects spatially", flush=True)
        relations, link_issues = match_sources(eligible, eligible_geo, sources, options["geo"]["min_overlap_m2"])
        counts["matched_relations"] = sum(map(len, relations.values()))
        counts["link_warnings"] = len(link_issues)
        tables = {name: [] for name in BY_NAME}
        tables.update(plans=quality.plans, plan_phasing=quality.phasing, plan_breakdown=quality.breakdown,
                      quarantine=quality.quarantine, dq_issues=quality.issues + link_issues,
                      source_status=sources.statuses, **sources.tables, **relations)
        for name, rows in tables.items():
            if name != "pipeline_run":
                tables[name] = [{"run_id": run_id, **row} for row in rows]
        finished = utc_now()
        status = "COMPLETE_WITH_REJECTIONS" if quality.rejected_count else "COMPLETE"
        tables["pipeline_run"] = [{
            "run_id": run_id, "delivery_id": delivery.delivery_id, "mode": config.mode,
            "status": status, "snapshot_utc": snapshot, "started_at": started,
            "completed_at": finished, "rule_version": rules["version"],
            "config_sha256": config.fingerprint,
            "source_metadata_json": json_text({"source_file": delivery.source_metadata,
                                               "synthetic": config.mode == "fixtures"}),
        }]
        print("[5/5] Writing database-ready CSVs", flush=True)
        bundle = export_bundle(tables, run_dir, metadata={"counts": counts, "mode": config.mode,
                                                         "synthetic": config.mode == "fixtures"})
        write_json(run_dir / "quality_summary.json", {"counts": counts, "rules": quality.rule_results,
                                                        "sources": sources.statuses})
        print("Done:", bundle, flush=True)
        return RunResult(run_dir, bundle, status, counts)
    except Exception:
        # Do not log exceptions/URLs/headers: API errors can contain sensitive material.
        write_json(run_dir / "failed.json", {"status": "FAILED", "at": utc_now()})
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LMVW data engineering portfolio pipeline")
    command = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "validate"):
        sub = command.add_parser(name)
        sub.add_argument("--config", type=Path, default=Path("config.yaml"))
        sub.add_argument("--output-dir", type=Path)
        sub.add_argument("--plans", type=Path, help="Optional Excel/CSV delivery; e.g. data/private/plans.xlsx")
        sub.add_argument("--geometries", type=Path, help="Optional GeoPackage containing plan polygons")
        sub.add_argument("--geometry-layer", help="GeoPackage layer")
        if name == "run":
            sub.add_argument("--mode", choices=("fixtures", "live"))
    verify = command.add_parser("verify")
    verify.add_argument("folder", type=Path, help="Path to a generated database_ready folder")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            print(json.dumps(verify_bundle(args.folder), ensure_ascii=False))
            return 0
        result = run_pipeline(args.config, validate_only=args.command == "validate",
                              mode=getattr(args, "mode", None), plans=args.plans,
                              geometries=args.geometries, geometry_layer=args.geometry_layer,
                              output_dir=args.output_dir)
        print(json.dumps({"status": result.status, "counts": result.counts}, ensure_ascii=False))
        return 2 if args.command == "validate" and result.counts["rejected_plans"] else 0
    except PipelineError as exc:
        # Controlled errors never include raw request data or headers.
        print(f"Pipeline error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Pipeline failed ({type(exc).__name__}); inspect input/configuration. Sensitive values are not printed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
