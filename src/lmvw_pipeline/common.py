"""Small deterministic utilities shared by the processing stages."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class PipelineError(Exception):
    """Expected failure with an intentionally non-sensitive diagnostic."""


class SourceError(PipelineError):
    """External source contract, completeness or transport failure."""


class ContractError(PipelineError):
    """Output would violate a database contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    """Atomic write; parent directory access remains the operator's responsibility."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        if os.name == "posix":
            os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    temp.replace(path)


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result if result else None


def strict_integer(value: Any) -> int | None:
    """No thousands-separator guesses, booleans, NaN, truncation or zero filling."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a housing count")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError("Not a numeric value") from None
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError("Not a finite integer")
    if not -(2**63) <= number <= 2**63 - 1:
        raise ValueError("Outside SQL BIGINT range")
    return int(number)


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    csv.field_size_limit(100 * 1024 * 1024)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise PipelineError("CSV has missing or duplicate column names")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise PipelineError("CSV row width differs from its header")
            rows.append(row)
        return rows
