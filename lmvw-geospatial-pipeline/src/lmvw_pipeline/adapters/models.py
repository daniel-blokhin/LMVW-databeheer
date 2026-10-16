"""Source-independent result types and strict source value parsing."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ..common import SourceError, digest, strict_integer, text
from ..geometry import RD, checked_geometry, geojson_wgs84, rd_wkt


SOURCE_TABLES = ("bag_panden", "bag_verblijfsobjecten", "bag_vbo_pand", "brk_percelen",
                 "dso_documents", "dso_document_text")


@dataclass
class SourceData:
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {name: [] for name in SOURCE_TABLES})
    dso_candidates: list[dict[str, Any]] = field(default_factory=list)
    statuses: list[dict[str, Any]] = field(default_factory=list)
    input_hashes: dict[str, str] = field(default_factory=dict)


def native_id(value: Any, *, bag: bool = False) -> str:
    if not isinstance(value, str) or not value.strip() or (bag and not re.fullmatch(r"\d{16}", value)):
        raise SourceError("Missing or malformed native identifier; numeric identifiers are not reconstructed")
    return value.strip()


def number(value: Any) -> int | None:
    try:
        result = strict_integer(value)
    except ValueError:
        raise SourceError("Malformed integer in external source") from None
    if result is not None and result < 0:
        raise SourceError("Negative count in external source")
    return result


def decimal_number(value: Any) -> str | None:
    if text(value) is None:
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise SourceError("Malformed decimal in external source") from None
    if not result.is_finite() or result < 0:
        raise SourceError("Non-finite or negative decimal in external source")
    return format(result, "f")


def source_date(value: Any) -> str | None:
    if text(value) is None:
        return None
    try:
        raw = str(value)
        if "T" in raw or " " in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise SourceError("Malformed date in external source") from None


def use_goals(value: Any) -> list[str]:
    parts = value if isinstance(value, list) else [value] if value is not None else []
    if not all(isinstance(p, str) for p in parts):
        raise SourceError("Unknown BAG use-goal representation")
    return sorted({item.strip().casefold() for part in parts for item in part.split(",") if item.strip()})


def geometry_fields(value: Any, allowed: tuple[str, ...], crs: str = RD) -> dict[str, Any]:
    geometry = checked_geometry(value, crs=crs, allowed=allowed)
    return {"geometry_wkt": rd_wkt(geometry), "geometry_geojson_wgs84": geojson_wgs84(geometry), "crs": RD}


class Registry:
    """Deduplicate overlapping API tiles; conflicting source versions fail closed."""
    def __init__(self, limit: int) -> None:
        self.rows: dict[Any, dict] = {}
        self.hashes: dict[Any, str] = {}
        self.duplicates = 0
        self.limit = limit

    def add(self, key: Any, row: dict, source_content: Any) -> bool:
        checksum = digest(source_content)
        if key in self.rows:
            if checksum != self.hashes[key]:
                raise SourceError("Conflicting records with the same source identifier")
            self.duplicates += 1
            return False
        if len(self.rows) >= self.limit:
            raise SourceError("Unique source feature safety limit reached")
        self.rows[key], self.hashes[key] = row, checksum
        return True
