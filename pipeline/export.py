"""Single source of truth for CSV exports, validation and SQL Server DDL."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Column:
    name: str
    kind: str = "text"
    nullable: bool = True
    length: int | None = None

    @property
    def sql_type(self) -> str:
        if self.kind == "text":
            return f"NVARCHAR({self.length or 'MAX'}) COLLATE Latin1_General_100_BIN2"
        return {"json": "NVARCHAR(MAX)", "int": "BIGINT", "bool": "BIT", "decimal": "DECIMAL(38,12)",
                "date": "DATE", "datetime": "DATETIMEOFFSET(7)"}[self.kind]


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    parent: str
    parent_columns: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ForeignKey, ...] = ()


def t(name: str, length: int | None = None, nullable: bool = True) -> Column:
    return Column(name, "text", nullable, length)


def c(name: str, kind: str = "int", nullable: bool = True) -> Column:
    return Column(name, kind, nullable)


RUN = t("run_id", 36, False)
RECORD = t("record_id", 64, False)
RUN_FK = ForeignKey(("run_id",), "pipeline_run", ("run_id",))
PLAN_FK = ForeignKey(("run_id", "record_id"), "plans", ("run_id", "record_id"))
DOC_FK = ForeignKey(("run_id", "document_id"), "dso_documents", ("run_id", "document_id"))
GEOMETRY = (t("geometry_wkt"), c("geometry_geojson_wgs84", "json"), t("crs", 32))
SOURCE_COMMON = (t("source_feature_id", 100, False), c("retrieved_at", "datetime", False))


def table(name: str, columns: tuple[Column, ...], key: tuple[str, ...], *fks: ForeignKey) -> Table:
    return Table(name, (RUN, *columns), ("run_id", *key), (RUN_FK, *fks))


TABLES = (
    Table("pipeline_run", (RUN, t("delivery_id", 64, False), t("mode", 20, False), t("status", 40, False),
                          c("snapshot_utc", "datetime", False), c("started_at", "datetime", False),
                          c("completed_at", "datetime", False), t("rule_version", 32, False),
                          t("config_sha256", 64, False), c("source_metadata_json", "json", False)), ("run_id",)),
    table("source_status", (t("source_name", 20, False), t("status", 32, False), t("environment", 32, False),
                            c("record_count", nullable=False), t("message")), ("source_name",)),
    table("plans", (RECORD, t("delivery_id", 64, False), c("source_row_number", nullable=False),
                    t("source_record_hash", 64, False), t("municipality", 300), t("plan_name", 1000), t("koppelcode", 100),
                    c("confidential", "bool"), c("gross_capacity"), c("demolition"), c("net_capacity_reported"),
                    c("net_capacity_calculated"), c("temporary_homes"), t("plan_type", 300), t("plan_status", 300),
                    t("status_code", 8), t("hard_soft", 16, False), *GEOMETRY,
                    t("processing_status", 16, False), c("error_count", nullable=False),
                    c("warning_count", nullable=False), c("raw_payload_json", "json", False)), ("record_id",)),
    table("plan_phasing", (RECORD, c("period_start", nullable=False), c("period_end", nullable=False),
                           t("period_label", 80, False), c("sort_order", nullable=False), c("planned_homes")),
          ("record_id", "period_start", "period_end"), PLAN_FK),
    table("plan_breakdown", (RECORD, t("category_group", 40, False), t("category_code", 80, False),
                             t("source_field", 300, False), c("homes")), ("record_id", "category_group", "category_code"), PLAN_FK),
    table("quarantine", (RECORD, c("source_row_number", nullable=False), c("error_count", nullable=False),
                         c("raw_payload_json", "json", False)), ("record_id",), PLAN_FK),
    table("dq_issues", (t("issue_id", 64, False), t("record_id", 64), t("source_name", 40, False),
                        t("source_object_id", 2000), c("source_row_number"), t("rule_id", 80, False),
                        t("category", 40, False), t("severity", 16, False), t("field_name", 300, False),
                        t("source_value"), t("message", None, False)), ("issue_id",), PLAN_FK),
    table("bag_panden", (t("bag_pand_id", 16, False), *SOURCE_COMMON, t("status", 300), c("bouwjaar"),
                          c("aantal_verblijfsobjecten"), t("gebruiksdoel", 1000), c("documentdatum", "date"),
                          t("documentnummer", 1000), *GEOMETRY), ("bag_pand_id",)),
    table("bag_verblijfsobjecten", (t("bag_verblijfsobject_id", 16, False), *SOURCE_COMMON,
                                    t("status", 300), t("gebruiksdoel", 1000), c("oppervlakte_m2"),
                                    t("postcode", 16), t("openbare_ruimte_naam", 1000), c("huisnummer"),
                                    t("huisletter", 50), t("huisnummertoevoeging", 100), c("documentdatum", "date"),
                                    t("documentnummer", 1000), *GEOMETRY), ("bag_verblijfsobject_id",)),
    table("bag_vbo_pand", (t("bag_verblijfsobject_id", 16, False), t("bag_pand_id", 16, False),
                           t("relation_basis", 80, False), c("retrieved_at", "datetime", False)),
          ("bag_verblijfsobject_id", "bag_pand_id"),
          ForeignKey(("run_id", "bag_verblijfsobject_id"), "bag_verblijfsobjecten", ("run_id", "bag_verblijfsobject_id")),
          ForeignKey(("run_id", "bag_pand_id"), "bag_panden", ("run_id", "bag_pand_id"))),
    table("brk_percelen", (t("brk_namespace", 100, False), t("brk_local_id", 100, False), *SOURCE_COMMON,
                           t("kadastrale_gemeente_code", 100), t("kadastrale_gemeente_naam", 300), t("sectie", 50),
                           c("perceelnummer"), c("kadastrale_grootte_m2", "decimal"), t("grootte_status", 300),
                           t("historie_status", 300), *GEOMETRY), ("brk_namespace", "brk_local_id")),
    table("dso_documents", (t("document_id", 64, False), t("source_type", 64, False), t("environment", 32, False),
                            t("native_id", 2000, False), t("document_type", 500), t("title", 4000), c("document_date", "date"),
                            t("authority_name", 1000), t("authority_code", 100), t("plan_status", 300), t("rule_status", 300),
                            t("dossier_status", 300), t("dossier_id", 1000), t("reference_number", 1000), t("publication_id", 1000),
                            c("geometry_ids_json", "json", False), *GEOMETRY, t("geometry_status", 32, False),
                            t("text_status", 32, False), t("source_url", 4000), c("retrieved_at", "datetime", False)), ("document_id",)),
    table("dso_document_text", (t("document_id", 64, False), t("publication_text", None, False),
                                t("text_sha256", 64, False), c("character_count", nullable=False),
                                c("retrieved_at", "datetime", False)), ("document_id",), DOC_FK),
    table("plan_bag_vbo", (RECORD, t("bag_verblijfsobject_id", 16, False), t("match_method", 100, False),
                           t("spatial_relation", 100, False)), ("record_id", "bag_verblijfsobject_id"), PLAN_FK,
          ForeignKey(("run_id", "bag_verblijfsobject_id"), "bag_verblijfsobjecten", ("run_id", "bag_verblijfsobject_id"))),
    table("plan_bag_pand", (RECORD, t("bag_pand_id", 16, False), t("match_method", 100, False),
                            t("spatial_relation", 100, False), c("overlap_area_m2", "decimal"), c("via_vbo_count", nullable=False)),
          ("record_id", "bag_pand_id"), PLAN_FK,
          ForeignKey(("run_id", "bag_pand_id"), "bag_panden", ("run_id", "bag_pand_id"))),
    table("plan_brk_perceel", (RECORD, t("brk_namespace", 100, False), t("brk_local_id", 100, False),
                               t("match_method", 100, False), c("intersection_area_m2", "decimal", False),
                               c("overlap_pct_plan", "decimal", False), c("overlap_pct_perceel", "decimal", False)),
          ("record_id", "brk_namespace", "brk_local_id"), PLAN_FK,
          ForeignKey(("run_id", "brk_namespace", "brk_local_id"), "brk_percelen", ("run_id", "brk_namespace", "brk_local_id"))),
    table("plan_dso", (RECORD, t("document_id", 64, False), t("search_geometry_hash", 64, False),
                       t("relation_basis", 100, False), t("relation_status", 100, False),
                       c("spatial_verified", "bool", False), c("substantively_confirmed", "bool", False),
                       c("overlap_area_m2", "decimal"), c("retrieved_at", "datetime", False)),
          ("record_id", "document_id"), PLAN_FK, DOC_FK),
)
BY_NAME = {spec.name: spec for spec in TABLES}


def schema_document() -> dict[str, Any]:
    return json.loads(json.dumps({"version": "1.0.0", "dialect": "SQL Server", "encoding": "utf-8", "delimiter": ",",
            "newline": "LF", "null_token": "\\N", "load_order": [t.name for t in TABLES],
            "tables": [asdict(spec) for spec in TABLES]}))


def sql_ddl() -> str:
    lines = ["-- Generated from lmvw_pipeline.contracts. No source data or credentials.",
             "-- First installation into an empty lmvw schema; do not disable constraints.",
             "IF SCHEMA_ID(N'lmvw') IS NULL EXEC(N'CREATE SCHEMA [lmvw]');", "GO", ""]
    for spec in TABLES:
        definitions = [f"    [{col.name}] {col.sql_type} {'NULL' if col.nullable else 'NOT NULL'}" for col in spec.columns]
        keys = ", ".join(f"[{k}]" for k in spec.primary_key)
        definitions.append(f"    CONSTRAINT [PK_{spec.name}] PRIMARY KEY ({keys})")
        for i, fk in enumerate(spec.foreign_keys):
            child = ", ".join(f"[{k}]" for k in fk.columns)
            parent = ", ".join(f"[{k}]" for k in fk.parent_columns)
            definitions.append(f"    CONSTRAINT [FK_{spec.name}_{i}] FOREIGN KEY ({child}) REFERENCES [lmvw].[{fk.parent}] ({parent})")
        lines += [f"CREATE TABLE [lmvw].[{spec.name}] (", ",\n".join(definitions), ");", "GO", ""]
    return "\n".join(lines)


"""Atomic, typed database bundles. A success manifest is written only after readback."""

import csv
import json
import os
import re
import shutil
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from . import __version__
from .settings import ContractError, digest, file_sha256, read_json, strict_integer, write_json

NULL = "\\N"


def validate_value(value: Any, col: Column) -> None:
    if value is None:
        if not col.nullable:
            raise ContractError(f"NULL in required column {col.name}")
        return
    if col.kind in {"text", "json"}:
        if not isinstance(value, str) or "\x00" in value or value == NULL:
            raise ContractError(f"Invalid or reserved text in {col.name}")
        if col.length and len(value.encode("utf-16-le")) // 2 > col.length:
            raise ContractError(f"SQL NVARCHAR length exceeded in {col.name}; truncation is disabled")
        if col.kind == "json":
            try:
                parsed = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, TypeError):
                raise ContractError(f"Invalid JSON in {col.name}") from None
            if not isinstance(parsed, (dict, list)):
                raise ContractError(f"JSON object or array required in {col.name}")
    elif col.kind == "int":
        try:
            parsed = strict_integer(value)
            if parsed is None:
                raise ValueError()
        except ValueError:
            raise ContractError(f"Invalid SQL BIGINT in {col.name}") from None
    elif col.kind == "bool":
        if not isinstance(value, bool):
            raise ContractError(f"Python boolean required in {col.name}")
    elif col.kind == "decimal":
        try:
            with localcontext() as ctx:
                ctx.prec = 50
                number = Decimal(str(value))
                if not number.is_finite() or abs(number) >= Decimal(10)**26 or number != number.quantize(Decimal("0.000000000001")):
                    raise ValueError()
        except (ValueError, InvalidOperation):
            raise ContractError(f"Value cannot be represented as DECIMAL(38,12) in {col.name}") from None
    elif col.kind == "date":
        try:
            if date.fromisoformat(str(value)).isoformat() != value:
                raise ValueError()
        except ValueError:
            raise ContractError(f"ISO date required in {col.name}") from None
    elif col.kind == "datetime":
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
                raise ValueError()
            if parsed.tzinfo is None or abs(parsed.utcoffset().total_seconds()) > 14 * 3600:
                raise ValueError()
        except ValueError:
            raise ContractError(f"Timezone-aware ISO timestamp with at most six fractional digits required in {col.name}") from None


def validate_tables(tables: dict[str, list[dict]]) -> None:
    if set(tables) != set(BY_NAME):
        raise ContractError("Bundle table set differs from the contract")
    keysets = {}
    for spec in TABLES:
        columns = {col.name for col in spec.columns}
        keys = set()
        for row in tables[spec.name]:
            if set(row) != columns:
                missing, extra = sorted(columns - set(row)), sorted(set(row) - columns)
                raise ContractError(f"Column mismatch in {spec.name}: missing={missing}, extra={extra}")
            for col in spec.columns:
                validate_value(row[col.name], col)
            key = tuple(row[k] for k in spec.primary_key)
            if any(k is None or k == "" for k in key) or key in keys:
                raise ContractError(f"Empty or duplicate primary key in {spec.name}")
            keys.add(key)
        keysets[spec.name] = keys
    for spec in TABLES:
        for fk in spec.foreign_keys:
            parent = {tuple(row[k] for k in fk.parent_columns) for row in tables[fk.parent]}
            for row in tables[spec.name]:
                key = tuple(row[k] for k in fk.columns)
                if any(v is None for v in key):
                    continue
                if key not in parent:
                    raise ContractError(f"Orphan foreign key in {spec.name} -> {fk.parent}")


def _encode(value: Any) -> str:
    if value is None:
        return NULL
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def read_table(path: Path, name: str) -> list[dict]:
    spec = BY_NAME[name]
    csv.field_size_limit(100 * 1024 * 1024)
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != [c.name for c in spec.columns]:
            raise ContractError(f"CSV column order differs from the contract: {name}")
        rows = []
        for raw in reader:
            if None in raw or any(v is None for v in raw.values()):
                raise ContractError("Malformed CSV record")
            row = {}
            for col in spec.columns:
                value = raw[col.name]
                if value == NULL:
                    row[col.name] = None
                elif col.kind == "bool":
                    if value not in {"0", "1"}:
                        raise ContractError("CSV boolean must be 0 or 1")
                    row[col.name] = value == "1"
                elif col.kind == "int":
                    if not re.fullmatch(r"-?\d+", value):
                        raise ContractError("CSV integer has an unexpected representation")
                    row[col.name] = int(value)
                else:
                    row[col.name] = value
            rows.append(row)
        return rows


def verify_bundle(directory: Path) -> dict:
    manifest = read_json(directory / "manifest.json")
    if manifest.get("contract_sha256") != digest(schema_document()):
        raise ContractError("Bundle contract differs from installed code")
    expected = {spec.name + ".csv" for spec in TABLES} | {"schema.json", "schema.sql"}
    if set(manifest.get("files", {})) != expected:
        raise ContractError("Manifest does not contain exactly the contracted files")
    for name, record in manifest["files"].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or file_sha256(path) != record["sha256"]:
            raise ContractError("Bundle checksum verification failed")
    if read_json(directory / "schema.json") != schema_document():
        raise ContractError("Schema contents differ from installed code")
    if (directory / "schema.sql").read_text(encoding="utf-8") != sql_ddl():
        raise ContractError("SQL schema differs from installed code")
    tables = {spec.name: read_table(directory / (spec.name + ".csv"), spec.name) for spec in TABLES}
    validate_tables(tables)
    for name, rows in tables.items():
        if len(rows) != manifest["files"][name + ".csv"]["rows"]:
            raise ContractError("Manifest row count mismatch")
    return {"status": "VERIFIED", "tables": len(tables), "rows": sum(len(rows) for rows in tables.values()),
            "counts": {name: len(rows) for name, rows in tables.items()}}


def export_bundle(tables: dict[str, list[dict]], run_dir: Path, *, metadata: dict) -> Path:
    validate_tables(tables)
    target = run_dir / "database_ready"
    temp = run_dir / ".database_ready.tmp"
    if target.exists() or temp.exists():
        raise ContractError("Output bundle already exists; overwrite is disabled")
    temp.mkdir(mode=0o700)
    try:
        files = {}
        for spec in TABLES:
            path = temp / (spec.name + ".csv")
            ordered = sorted(tables[spec.name], key=lambda row: tuple(str(row[k]) for k in spec.primary_key))
            with path.open("w", encoding="utf-8", newline="") as stream:
                if os.name == "posix":
                    os.fchmod(stream.fileno(), 0o600)
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow([col.name for col in spec.columns])
                for row in ordered:
                    writer.writerow([_encode(row[col.name]) for col in spec.columns])
            files[path.name] = {"rows": len(ordered), "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        write_json(temp / "schema.json", schema_document())
        (temp / "schema.sql").write_text(sql_ddl(), encoding="utf-8")
        for name in ("schema.json", "schema.sql"):
            files[name] = {"bytes": (temp / name).stat().st_size, "sha256": file_sha256(temp / name)}
        manifest = {"bundle_version": 1, "package_version": __version__, "contract_sha256": digest(schema_document()),
                    "classification": "INTERNAL_DATA_NOT_PUBLICATION_APPROVAL", "metadata": metadata, "files": files}
        write_json(temp / "manifest.json", manifest)
        verify_bundle(temp)
        temp.rename(target)
        return target
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
