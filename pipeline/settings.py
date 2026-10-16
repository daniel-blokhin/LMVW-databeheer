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


"""Explicit configuration. Paths resolve relative to the YAML file, not the CWD."""

import math
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml



@dataclass(frozen=True)
class Config:
    path: Path
    values: dict[str, Any]

    def resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return (self.path.parent / path).resolve() if not path.is_absolute() else path.resolve()

    @property
    def mode(self) -> str:
        return self.values["sources"]["mode"]

    @property
    def fingerprint(self) -> str:
        # Fingerprint the effective configuration. Local path changes affect this hash.
        return digest(self.values)

    def with_overrides(self, **kwargs: Any) -> "Config":
        values = deepcopy(self.values)
        for key, value in kwargs.items():
            if value is not None:
                if key == "mode":
                    values["sources"]["mode"] = value
                else:
                    values[key] = value
        return Config(self.path, values)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise PipelineError("Configuration must be a YAML object")
    return data


def load_config(path: Path) -> Config:
    data = load_yaml(path)
    allowed = {"version", "input", "output_dir", "mapping", "quality", "sources", "geo", "http", "snapshot_utc"}
    if set(data) - allowed:
        raise PipelineError("Unknown top-level configuration option")
    if data.get("version") != 1:
        raise PipelineError("Only configuration version 1 is supported")
    for required in ("input", "output_dir", "mapping", "quality", "sources"):
        if required not in data:
            raise PipelineError(f"Missing configuration section: {required}")
    sections = {
        "input": {"plans", "sheet", "delimiter", "geometries", "geometry_layer", "geometry_key"},
        "sources": {"mode", "fixtures_dir", "bag", "brk", "dso", "dso_environment", "fetch_publication_text", "only_residential_vbo"},
        "geo": {"buffer_m", "tile_size_m", "min_overlap_m2", "max_tiles", "max_scope_km2", "include_rejected_plans"},
        "http": {"page_size", "max_pages", "max_features", "max_response_bytes", "attempts", "pause_seconds"},
    }
    for name, keys in sections.items():
        section = data.get(name, {})
        if not isinstance(section, dict) or set(section) - keys:
            raise PipelineError(f"Invalid or unknown configuration options in {name}")
    if not isinstance(data["output_dir"], str) or not data["output_dir"].strip():
        raise PipelineError("output_dir must be a non-empty path")
    for key in ("mapping", "quality"):
        if not isinstance(data[key], dict):
            raise PipelineError(f"{key} must be a YAML mapping in config.yaml")
    if not isinstance(data["input"].get("plans"), str):
        raise PipelineError("input.plans is required")
    if len(data["input"].get("delimiter", ";")) != 1:
        raise PipelineError("CSV delimiter must be exactly one character")
    sources = data["sources"]
    sources.setdefault("dso_environment", "PRODUCTION")
    if sources.get("mode") not in {"fixtures", "live"}:
        raise PipelineError("Unknown source mode")
    if sources.get("dso_environment", "PRODUCTION") not in {"PRODUCTION", "PRE"}:
        raise PipelineError("DSO environment must be PRODUCTION or PRE")
    # A secret may NEVER be supplied as a value in committed configuration.
    def reject_secrets(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if any(term in str(key).lower() for term in ("api_key", "apikey", "password", "token", "secret")):
                    raise PipelineError("Secrets are not accepted in YAML; use the documented environment variables")
                reject_secrets(value)
        elif isinstance(obj, list):
            for value in obj:
                reject_secrets(value)
    reject_secrets(data)
    for name in ("bag", "brk", "dso", "fetch_publication_text", "only_residential_vbo"):
        if not isinstance(sources.get(name, False), bool):
            raise PipelineError(f"sources.{name} must be a YAML boolean")
    data.setdefault("geo", {})
    for key, default in {"buffer_m": 50.0, "tile_size_m": 500.0, "min_overlap_m2": 0.01,
                         "max_tiles": 500, "max_scope_km2": 100.0,
                         "include_rejected_plans": False}.items():
        data["geo"].setdefault(key, default)
    geo = data["geo"]
    for name in ("buffer_m", "tile_size_m", "min_overlap_m2", "max_scope_km2"):
        if type(geo[name]) not in (int, float) or not math.isfinite(geo[name]):
            raise PipelineError("Geographic numeric settings must be finite numbers")
    if type(geo["max_tiles"]) is not int or not isinstance(geo["include_rejected_plans"], bool):
        raise PipelineError("Invalid geographic integer or boolean setting")
    if not 0 < geo["max_scope_km2"] <= 10000:
        raise PipelineError("Geographic scope must be explicitly bounded")
    if not 0 <= geo["buffer_m"] <= 1000 or not 50 <= geo["tile_size_m"] <= 5000:
        raise PipelineError("Geographic buffer or tile size is outside the supported limits")
    if geo["min_overlap_m2"] <= 0 or not 1 <= geo["max_tiles"] <= 10000:
        raise PipelineError("Positive overlap threshold and bounded tile count are required")
    data.setdefault("http", {})
    for key, default in {"page_size": 1000, "max_pages": 100, "max_features": 250000,
                         "max_response_bytes": 50000000, "attempts": 4,
                         "pause_seconds": 0.05}.items():
        data["http"].setdefault(key, default)
    http = data["http"]
    for name, low, high in (("max_pages", 1, 10000), ("max_features", 1, 2000000), ("max_response_bytes", 1024, 200000000),
                            ("page_size", 1, 1000), ("attempts", 1, 6)):
        if type(http[name]) is not int or not low <= http[name] <= high:
            raise PipelineError("HTTP limits must be bounded integers")
    if type(http["pause_seconds"]) not in (int, float) or not math.isfinite(http["pause_seconds"]) or not 0 <= http["pause_seconds"] <= 60:
        raise PipelineError("HTTP pause must be finite and between 0 and 60 seconds")
    if not 1 <= data["http"]["page_size"] <= 1000 or not 1 <= data["http"]["attempts"] <= 6:
        raise PipelineError("Invalid page size or retry count")
    return Config(path.resolve(), data)


"""Runtime-only credentials. No defaults, command-line key flags or .env auto-loading."""

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path



@dataclass(frozen=True)
class Secret:
    _value: str = field(repr=False)

    def reveal(self) -> str:
        """Only the HTTP transport should call this method."""
        return self._value

    def __repr__(self) -> str:
        return "Secret([REDACTED])"

    def __str__(self) -> str:
        return "[REDACTED]"


def load_secret(name: str) -> Secret:
    """Accept an injected environment variable OR a read-only mounted secret file."""
    direct = os.environ.get(name)
    filename = os.environ.get(name + "_FILE")
    if direct and filename:
        raise PipelineError(f"Set only {name} or {name}_FILE, not both")
    if filename:
        path = Path(filename)
        try:
            if path.is_symlink() or not path.is_file():
                raise PipelineError("Secret file must be a regular non-symlink file")
            if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise PipelineError("Secret file must not be accessible to group or other users")
            direct = path.read_text(encoding="utf-8").strip()
        except OSError:
            raise PipelineError("Cannot read the configured secret file") from None
    if not direct or not direct.strip():
        raise PipelineError(f"Missing runtime credential: {name}")
    value = direct.strip()
    if any(c.isspace() for c in value) or not value.isascii() or len(value) > 4096:
        raise PipelineError("Invalid credential format")
    if value.lower() in {"changeme", "replace_me", "your_api_key", "placeholder"}:
        raise PipelineError("A placeholder cannot be used as a credential")
    return Secret(value)
