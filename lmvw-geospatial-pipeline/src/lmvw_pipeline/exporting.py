"""Atomic, typed database bundles. A success manifest is written only after readback."""
from __future__ import annotations

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
from .common import ContractError, digest, file_sha256, read_json, strict_integer, write_json
from .contracts import BY_NAME, TABLES, Column, schema_document, sql_ddl

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
