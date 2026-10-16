"""Orchestrate explicit stages without notebooks, a database or IO Factory."""
from __future__ import annotations

import csv
import json
import os
import platform
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable

from .adapters.collect import fetch_sources
from .adapters.models import SourceData
from .common import PipelineError, digest, file_sha256, json_text, read_json, utc_now, write_json
from .config import Config, load_config, load_yaml
from .contracts import BY_NAME
from .exporting import export_bundle
from .intake import read_delivery
from .matching import match_sources
from .validation.engine import QualityResult, validate_delivery


@dataclass(frozen=True)
class RunResult:
    run_dir: Path
    bundle: Path | None
    status: str
    counts: dict[str, int]


def _versions() -> dict[str, str]:
    output = {"python": platform.python_version()}
    for package in ("lmvw-geospatial-pipeline", "requests", "PyYAML", "openpyxl", "shapely", "pyproj", "geopandas", "pyogrio", "pandas"):
        try:
            output[package] = version(package)
        except PackageNotFoundError:
            output[package] = "not-installed-as-package"
    return output


def _implementation_hash() -> str:
    root = Path(__file__).parent
    return digest({str(p.relative_to(root)): file_sha256(p) for p in sorted(root.rglob("*.py"))})


def _snapshot(value: str | None) -> str:
    if not value:
        return utc_now()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except ValueError:
        raise PipelineError("snapshot_utc must be a timezone-aware ISO timestamp") from None


def _write_validation(run_dir: Path, quality: QualityResult) -> dict:
    counts = {"source_records": len(quality.plans), "accepted_records": len(quality.plans) - quality.rejected_count,
              "rejected_records": quality.rejected_count, "input_issues": len(quality.issues),
              "input_errors": sum(i["severity"] == "ERROR" for i in quality.issues),
              "input_warnings": sum(i["severity"] == "WARNING" for i in quality.issues)}
    # JSON is deliberately used for diagnostic records: lossless, no CSV formula execution.
    directory = run_dir / "validation"
    directory.mkdir(mode=0o700)
    write_json(directory / "issues.json", quality.issues)
    write_json(directory / "quarantine.json", quality.quarantine)
    write_json(directory / "plans.json", quality.plans)
    write_json(directory / "summary.json", {"counts": counts, "rules": quality.rule_results,
                                              "scope": "INPUT_VALIDATION_ONLY"})
    return counts


def run_pipeline(config_path: Path, *, output_dir: Path | None = None, mode: str | None = None,
                 replay_from: Path | None = None, validate_only: bool = False,
                 emit: Callable[[dict], None] | None = None) -> RunResult:
    """A failed source cannot silently become a successful empty database export.

    Input validation always preserves one plan row per source row. ERROR rows are
    kept in staging/quarantine and excluded from enrichment by default. Publication
    and database loading are deliberately outside this pipeline's boundary.
    """
    config = load_config(config_path).with_overrides(mode=mode)
    if replay_from and config.mode != "replay":
        raise PipelineError("--replay-from is valid only with --mode replay")
    if config.mode == "replay" and not replay_from and not validate_only:
        raise PipelineError("Replay requires --replay-from and never falls back to live requests")
    mapping_path, quality_path = config.resolve(config.values["mapping"]), config.resolve(config.values["quality"])
    mapping, rules = load_yaml(mapping_path), load_yaml(quality_path)
    if not isinstance(rules.get("version"), str):
        raise PipelineError("Quality rules require a string version")
    output = output_dir.resolve() if output_dir else config.resolve(config.values["output_dir"])
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_id = str(uuid.uuid4())
    run_dir = output / run_id
    run_dir.mkdir(mode=0o700)
    started = utc_now()
    context = {"run_id": run_id, "started_at": started, "status": "STARTED", "stage": "intake",
               "mode": "validation" if validate_only else config.mode,
               "config_sha256": config.fingerprint, "mapping_sha256": file_sha256(mapping_path),
               "quality_sha256": file_sha256(quality_path), "versions": _versions(),
               "implementation_sha256": _implementation_hash()}
    def event(stage: str, **values: object) -> None:
        context["stage"] = stage
        write_json(run_dir / "run_context.json", context)
        if emit:
            # No raw input records, source URLs, exception text or credential objects.
            emit({"event": stage, "run_id": run_id, **values})
    try:
        delivery = read_delivery(config)
        context.update(input_metadata=delivery.source_metadata, delivery_id=delivery.delivery_id)
        snapshot = _snapshot(config.values.get("snapshot_utc"))
        if config.mode == "replay" and not validate_only:
            old = read_json(replay_from / "run_context.json")
            if old.get("status") not in {"COMPLETE", "COMPLETE_WITH_REJECTIONS"} or old.get("mode") != "live":
                raise PipelineError("Replay needs a completed live run with private raw response caches")
            for key, expected in (("delivery_id", delivery.delivery_id), ("mapping_sha256", context["mapping_sha256"]),
                                  ("quality_sha256", context["quality_sha256"])):
                if old.get(key) != expected:
                    raise PipelineError("Replay input or rule mapping differs from the recorded live run")
            snapshot = old["snapshot_utc"]
            context["replay_of_run_id"] = old["run_id"]
        context["snapshot_utc"] = snapshot
        event("validate", source_records=len(delivery.records))
        quality = validate_delivery(delivery, mapping, rules)
        if len(quality.plans) != len(delivery.records):
            raise PipelineError("Record conservation invariant failed")
        counts = _write_validation(run_dir, quality)
        if validate_only:
            status = "VALIDATED_WITH_REJECTIONS" if quality.rejected_count else "VALIDATED"
            context.update(status=status, completed_at=utc_now(), counts=counts)
            event("validation_complete", **counts)
            return RunResult(run_dir, None, status, counts)
        include_rejected = config.values["geo"]["include_rejected_plans"]
        eligible = [p for p in quality.plans if p["record_id"] in quality.geometries
                    and (include_rejected or p["processing_status"] != "REJECTED")]
        geometries = {p["record_id"]: quality.geometries[p["record_id"]] for p in eligible}
        event("ingest_sources", eligible_records=len(eligible), source_mode=config.mode)
        settings = config.values["sources"]
        if eligible:
            sources = fetch_sources(config, eligible, geometries, run_dir, snapshot, replay_from)
        else:
            sources = SourceData()
            sources.statuses = [{"source_name": name.upper(),
                                 "status": "NOT_QUERIED" if settings.get(name, False) else "DISABLED",
                                 "environment": "NOT_APPLICABLE", "record_count": 0,
                                 "message": "No eligible plans; no source query was performed."}
                                for name in ("bag", "brk", "dso", "rp")]
        event("match_sources")
        relations, link_issues = match_sources(eligible, geometries, sources, config.values["geo"]["min_overlap_m2"])
        counts.update(eligible_records=len(eligible), enrichment_issues=len(link_issues),
                      matched_relations=sum(len(rows) for rows in relations.values()))
        tables = {name: [] for name in BY_NAME}
        tables.update(plans=quality.plans, plan_phasing=quality.phasing, plan_breakdown=quality.breakdown,
                      dq_issues=quality.issues + link_issues, quarantine=quality.quarantine,
                      source_status=sources.statuses, **sources.tables, **relations)
        for name, rows in tables.items():
            if name != "pipeline_run":
                tables[name] = [{"run_id": run_id, **row} for row in rows]
        status = "COMPLETE_WITH_REJECTIONS" if quality.rejected_count else "COMPLETE"
        completed = utc_now()
        metadata = {"input": delivery.source_metadata, "source_input_hashes": sources.input_hashes,
                    "mapping_sha256": context["mapping_sha256"], "quality_sha256": context["quality_sha256"],
                    "versions": context["versions"], "implementation_sha256": context["implementation_sha256"],
                    "enrichment_includes_rejected": include_rejected,
                    "scope": "DATABASE_READY_STAGING_NOT_PUBLICATION", "synthetic_sources": config.mode == "fixtures"}
        tables["pipeline_run"] = [{"run_id": run_id, "delivery_id": delivery.delivery_id, "mode": config.mode,
                                    "status": status, "snapshot_utc": snapshot, "started_at": started,
                                    "completed_at": completed, "rule_version": rules["version"],
                                    "config_sha256": config.fingerprint, "source_metadata_json": json_text(metadata)}]
        event("export")
        bundle = export_bundle(tables, run_dir, metadata={"run_id": run_id, "mode": config.mode, "counts": counts, **metadata})
        write_json(run_dir / "quality_summary.json", {"counts": counts, "rules": quality.rule_results,
                                                       "source_statuses": sources.statuses,
                                                       "enrichment_issues": link_issues,
                                                       "table_counts": {name: len(rows) for name, rows in tables.items()}})
        context.update(status=status, completed_at=completed, counts=counts,
                       source_input_hashes=sources.input_hashes)
        event("complete", status=status, **counts)
        return RunResult(run_dir, bundle, status, counts)
    except BaseException as exc:
        context.update(status="FAILED", completed_at=utc_now(), error_type=type(exc).__name__)
        # Exception messages/tracebacks may contain request headers or private input.
        write_json(run_dir / "run_context.json", context)
        if emit:
            emit({"event": "failed", "run_id": run_id, "stage": context["stage"], "error_type": type(exc).__name__})
        raise
