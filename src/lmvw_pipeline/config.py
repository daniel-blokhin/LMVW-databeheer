"""Explicit configuration. Paths resolve relative to the YAML file, not the CWD."""
from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .common import PipelineError, digest


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
        "sources": {"mode", "fixtures_dir", "snapshot_dir", "bag", "brk", "dso", "rp", "dso_environment", "fetch_publication_text", "only_residential_vbo"},
        "geo": {"buffer_m", "tile_size_m", "min_overlap_m2", "max_tiles", "max_scope_km2", "include_rejected_plans"},
        "http": {"page_size", "max_pages", "max_features", "max_response_bytes", "attempts", "pause_seconds"},
    }
    for name, keys in sections.items():
        section = data.get(name, {})
        if not isinstance(section, dict) or set(section) - keys:
            raise PipelineError(f"Invalid or unknown configuration options in {name}")
    for key in ("output_dir", "mapping", "quality"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise PipelineError(f"A non-empty path is required for {key}")
    if not isinstance(data["input"].get("plans"), str):
        raise PipelineError("input.plans is required")
    if len(data["input"].get("delimiter", ";")) != 1:
        raise PipelineError("CSV delimiter must be exactly one character")
    sources = data["sources"]
    sources.setdefault("dso_environment", "PRODUCTION")
    if sources.get("mode") not in {"fixtures", "live", "replay", "snapshots"}:
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
    for name in ("bag", "brk", "dso", "rp", "fetch_publication_text", "only_residential_vbo"):
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
