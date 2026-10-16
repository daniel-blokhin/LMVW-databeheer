"""Pure-Python, record-level quality checks with explicit unevaluable checks."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry.base import BaseGeometry

from ..common import PipelineError, digest, json_text, strict_integer, text
from ..geometry import RD, checked_geometry, geojson_wgs84, rd_wkt
from ..intake import Delivery


@dataclass
class QualityResult:
    plans: list[dict[str, Any]] = field(default_factory=list)
    phasing: list[dict[str, Any]] = field(default_factory=list)
    breakdown: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    quarantine: list[dict[str, Any]] = field(default_factory=list)
    geometries: dict[str, BaseGeometry] = field(default_factory=dict)
    rule_results: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def rejected_count(self) -> int:
        return sum(p["processing_status"] == "REJECTED" for p in self.plans)


class RuleEngine:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self.issues: list[dict[str, Any]] = []
        self.counts: dict[str, Counter] = defaultdict(Counter)

    def check(self, rule: str, valid: bool | None, record: dict, field_name: str,
              message: str, *, category: str, severity: str = "ERROR", value: Any = None) -> None:
        if valid is None:
            self.counts[rule]["not_evaluable"] += 1
            return
        self.counts[rule]["evaluated"] += 1
        if valid:
            self.counts[rule]["passed"] += 1
            return
        self.counts[rule]["failed"] += 1
        effective = self.settings.get("severity_overrides", {}).get(rule, severity)
        if effective not in {"ERROR", "WARNING", "INFO"}:
            raise PipelineError("Unknown severity in quality configuration")
        self.issues.append({
            "issue_id": digest([record["record_id"], rule, field_name, message]),
            "record_id": record["record_id"], "source_name": "PLANS", "source_object_id": None,
            "source_row_number": record["source_row_number"], "rule_id": rule,
            "category": category, "severity": effective, "field_name": field_name,
            "source_value": None if value is None else str(value), "message": message,
        })


def _periods(headers: list[str]) -> list[tuple[str, int, int]]:
    result = []
    for header in headers:
        if re.fullmatch(r"20\d{2}", header):
            result.append((header, int(header), int(header)))
        elif match := re.fullmatch(r"(20\d{2})\s+t/m\s+(20\d{2})", header):
            result.append((header, int(match[1]), int(match[2])))
    result.sort(key=lambda item: (item[1], item[2]))
    for i, (_, start, end) in enumerate(result):
        if start > end or (i and start <= result[i - 1][2]):
            raise PipelineError("Phasing periods overlap or have invalid ranges")
    if not result:
        raise PipelineError("No phasing columns found")
    return result


def validate_delivery(delivery: Delivery, mapping: dict[str, Any], rules: dict[str, Any]) -> QualityResult:
    """Preserve every source record. Parse errors produce NULL plus a quality issue.

    NULL does not become zero. Business errors quarantine records, rather than
    changing source numbers, removing constraints or silently deleting duplicates.
    """
    engine = RuleEngine(rules)
    output = QualityResult()
    headers = delivery.source_metadata["source_columns"]
    scalar = mapping["fields"]  # canonical name -> source header
    groups = mapping["groups"]
    required_headers = set(scalar.values()) | {header for group in groups.values() for header in group.values()}
    missing = required_headers - set(headers)
    if missing:
        raise PipelineError("Plan schema does not match the configured column mapping: " + ", ".join(sorted(missing)))
    periods = _periods(headers)
    group_headers = [header for group in groups.values() for header in group.values()]
    numeric_headers = [scalar[k] for k in ("gross_capacity", "demolition", "net_capacity_reported", "temporary_homes")]
    numeric_headers += group_headers + [header for header, _, _ in periods]
    duplicates = Counter(text(r["raw"].get(scalar["koppelcode"])) for r in delivery.records)
    payload_counts = Counter(digest(r["raw"]) for r in delivery.records)
    hard = set(rules["hard_status_codes"])
    soft = set(rules["soft_status_codes"])
    plantypes = {value.casefold() for value in rules["allowed_plan_types"]}

    for record in delivery.records:
        raw, rid = record["raw"], record["record_id"]
        issue_start = len(engine.issues)
        for header in record["missing_formula_cache"]:
            engine.check("DQ-XLSX-001", False, record, header,
                         "Excel formula has no cached result; recalculate the workbook before delivery.",
                         category="Completeness")
        values: dict[str, int | None] = {}
        for header in numeric_headers:
            try:
                number = strict_integer(raw.get(header))
                engine.check("DQ-TYPE-001", True, record, header, "", category="Validity")
            except ValueError:
                number = None
                engine.check("DQ-TYPE-001", False, record, header,
                             "Expected a finite integer; original value preserved in quarantine.",
                             category="Validity", value=raw.get(header))
            values[header] = number
            engine.check("DQ-COM-002", number is not None, record, header,
                         "Numeric value is missing or unparseable; it was not converted to zero.",
                         category="Completeness", severity="WARNING", value=raw.get(header))
            if header != scalar["net_capacity_reported"]:
                engine.check("DQ-RANGE-001", None if number is None else number >= 0, record, header,
                             "Housing counts other than net capacity must be non-negative.",
                             category="Validity", value=raw.get(header))
        p = {key: text(raw[header]) for key, header in scalar.items()
             if key not in {"gross_capacity", "demolition", "net_capacity_reported", "temporary_homes"}}
        p.update({key: values[scalar[key]] for key in ("gross_capacity", "demolition", "net_capacity_reported", "temporary_homes")})
        p.update({"record_id": rid, "delivery_id": delivery.delivery_id,
                  "source_row_number": record["source_row_number"],
                  "source_record_hash": digest(raw)})
        for key in ("municipality", "plan_name", "koppelcode", "plan_type", "plan_status"):
            engine.check("DQ-COM-001", p[key] is not None, record, scalar[key],
                         "Required plan attribute is missing.", category="Completeness", value=p[key])
        confidential_raw = p.pop("confidential")
        confidential = {"ja": True, "nee": False}.get((confidential_raw or "").casefold())
        p["confidential"] = confidential
        engine.check("DQ-CONF-001", confidential is not None, record, scalar["confidential"],
                     "Confidentiality must be Ja or Nee; unknown must never default to public.",
                     category="Confidentiality", value=confidential_raw)
        status_match = re.match(r"^(1[ABC]|2[ABC]|3|4[AB]|5[AB])(?:\b|\.)", (p["plan_status"] or "").upper())
        status = status_match[1] if status_match else None
        p["status_code"] = status
        p["hard_soft"] = "HARD" if status in hard else "SOFT" if status in soft else "UNKNOWN"
        engine.check("DQ-CAT-001", status in hard | soft, record, scalar["plan_status"],
                     "Plan status is not in the configured monitoring categories.", category="Validity", value=p["plan_status"])
        engine.check("DQ-CAT-002", (p["plan_type"] or "").casefold() in plantypes, record, scalar["plan_type"],
                     "Unrecognised dominant plan type.", category="Validity", value=p["plan_type"])
        engine.check("DQ-DUP-001", not p["koppelcode"] or duplicates[p["koppelcode"]] <= 1, record, scalar["koppelcode"],
                     "Area key is shared by multiple source records; records remain distinct.",
                     category="Uniqueness", severity="WARNING", value=p["koppelcode"])
        engine.check("DQ-DUP-002", payload_counts[digest(raw)] == 1, record, "source_record_hash",
                     "Exact duplicate source record; no automatic deletion or merging.", category="Uniqueness")
        for key in ("gross_capacity", "demolition"):
            engine.check("DQ-COM-003", p[key] is not None, record, scalar[key],
                         "Gross capacity and demolition are required for usable capacity metrics.",
                         category="Completeness", value=raw.get(scalar[key]))
        gross, demolition, reported = p["gross_capacity"], p["demolition"], p["net_capacity_reported"]
        p["net_capacity_calculated"] = gross - demolition if gross is not None and demolition is not None else None
        expected_net = p["net_capacity_calculated"]
        engine.check("DQ-NET-001", None if expected_net is None or reported is None else expected_net == reported,
                     record, scalar["net_capacity_reported"], "Reported net capacity differs from gross capacity minus demolition.",
                     category="Consistency", value=reported)
        temporary = p["temporary_homes"]
        engine.check("DQ-RANGE-002", None if temporary is None or gross is None else temporary <= gross,
                     record, scalar["temporary_homes"], "Temporary housing exceeds gross capacity.", category="Plausibility", value=temporary)
        for group, fields in groups.items():
            counts = [values[header] for header in fields.values()]
            for category, header in fields.items():
                output.breakdown.append({"record_id": rid, "category_group": group, "category_code": category,
                                         "source_field": header, "homes": values[header]})
            total = sum(counts) if all(v is not None for v in counts) else None
            if group in {"housing_type", "tenure_price"}:
                rule = "DQ-SUM-001" if group == "housing_type" else "DQ-SUM-002"
                engine.check(rule, None if total is None or gross is None else total == gross,
                             record, group, "Category sum differs from gross capacity.", category="Consistency", value=total)
            elif group == "senior_housing":
                engine.check("DQ-RANGE-003", None if total is None or gross is None else total <= gross,
                             record, group, "Sum of the disjoint senior-housing categories exceeds gross capacity.",
                             category="Plausibility", value=total)
        phase_values = [values[header] for header, _, _ in periods]
        phase_total = sum(phase_values) if all(v is not None for v in phase_values) else None
        engine.check("DQ-SUM-003", None if phase_total is None or gross is None else phase_total == gross,
                     record, "phasing", "Phasing sum differs from gross capacity; five-year buckets were not split into years.",
                     category="Consistency", value=phase_total)
        for index, (header, start, end) in enumerate(periods, 1):
            output.phasing.append({"record_id": rid, "period_start": start, "period_end": end,
                                   "period_label": header, "sort_order": index, "planned_homes": values[header]})
        geom = None
        if delivery.uses_geometry_file:
            geometry_value, crs = delivery.geometry_by_key.get(p["koppelcode"], (None, ""))
        else:
            geometry_value, crs = raw.get("Polygon_WKT"), text(raw.get("CRS"))
        if geometry_value is not None and crs:
            try:
                geom = checked_geometry(geometry_value, crs=crs)
            except PipelineError:
                pass
        engine.check("DQ-GEO-001", geom is not None, record, "geometry",
                     "Plan has no valid polygon with a known CRS; no automatic repair or inferred location.", category="Geometry")
        p["geometry_wkt"] = rd_wkt(geom) if geom is not None else None
        p["geometry_geojson_wgs84"] = geojson_wgs84(geom) if geom is not None else None
        p["crs"] = RD if geom is not None else None
        if geom is not None:
            output.geometries[rid] = geom
        record_issues = engine.issues[issue_start:]
        errors = sum(i["severity"] == "ERROR" for i in record_issues)
        warnings = sum(i["severity"] == "WARNING" for i in record_issues)
        p["processing_status"] = "REJECTED" if errors else "WARNING" if warnings else "READY"
        p["error_count"], p["warning_count"] = errors, warnings
        p["raw_payload_json"] = json_text({"values": raw, "formulae": record["formulae"]})
        output.plans.append(p)
        if errors:
            output.quarantine.append({"record_id": rid, "source_row_number": record["source_row_number"],
                                      "error_count": errors, "raw_payload_json": p["raw_payload_json"]})
    output.issues = engine.issues
    output.rule_results = {rule: dict(counts) for rule, counts in sorted(engine.counts.items())}
    return output
