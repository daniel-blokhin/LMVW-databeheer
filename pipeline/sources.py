"""Source-independent result types and strict source value parsing."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .settings import SourceError, digest, strict_integer, text
from .geospatial import RD, checked_geometry, geojson_wgs84, rd_wkt


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


"""Source selection: live requests, offline replay, synthetic fixtures or private snapshots."""

from pathlib import Path
from typing import Any

from shapely import from_wkt
from shapely.geometry import mapping

from .settings import SourceError, file_sha256, read_csv, read_json
from .settings import Config
from .geospatial import RD, RD_URI, checked_geometry, geometry_key, query_scope
from .http_client import JsonClient
from .settings import load_secret
from .http_client import BAG_BASE, BRK_BASE, OgcClient


class FixtureDsoClient:
    """Synthetic API-shaped payloads, never a silent fallback for a live outage."""
    def __init__(self, path: Path) -> None:
        self.data = read_json(path)
        if self.data.get("synthetic") is not True:
            raise SourceError("DSO fixture must explicitly declare synthetic data")
        self.publication_calls = 0
        self.geometry_calls = 0

    def search(self, resource: str, geom: Any) -> list[tuple[dict, str]]:
        key = geometry_key(geom)
        area = self.data["areas"].get(key)
        if area is None:
            raise SourceError("Synthetic DSO fixture does not cover this search geometry")
        return [(item, self.data["retrieved_at"]) for item in area.get(resource, [])]

    def geometry(self, identifier: str) -> Any:
        self.geometry_calls += 1
        return checked_geometry(self.data["geometries"][identifier])

    def publication(self, identifier: str) -> tuple[str | None, str]:
        self.publication_calls += 1
        from .dso import document_text
        return document_text(self.data["document_structures"][identifier]), self.data["retrieved_at"]


def _fixture_features(path: Path) -> list[tuple[dict, str]]:
    envelope = read_json(path)
    if envelope.get("content_crs") != RD_URI or envelope.get("synthetic") is not True:
        raise SourceError("Fixture must be explicitly synthetic with a declared RD CRS")
    return [(feature, envelope["retrieved_at"]) for feature in envelope["data"]["features"]]


def fetch_sources(config: Config, plans: list[dict], geometries: dict, run_dir: Path,
                  snapshot_utc: str) -> SourceData:
    # Loaded only here: source normalizers depend on common helpers in this module.
    from .bag import collect_bag
    from .brk import collect_brk
    from .dso import DSO_HOSTS, DsoClient, collect_documents
    settings, http_settings, geo = config.values["sources"], config.values["http"], config.values["geo"]
    result = SourceData()
    scope, tiles = query_scope(geometries.values(), buffer_m=geo["buffer_m"], tile_size_m=geo["tile_size_m"],
                               max_tiles=geo["max_tiles"], max_scope_km2=geo["max_scope_km2"])
    clients = []
    bag_api = brk_api = None
    dso_client = None
    mode = config.mode
    enabled = {name: settings.get(name, False) for name in ("bag", "brk", "dso")}
    def new_http(base: str, name: str, secret: Any = None) -> JsonClient:
        client = JsonClient(base, secret=secret, cache_dir=run_dir / "raw" / name,
                            attempts=http_settings["attempts"], max_response_bytes=http_settings["max_response_bytes"],
                            pause_seconds=http_settings["pause_seconds"])
        clients.append(client)
        return client
    try:
        if mode == "fixtures":
            directory = config.resolve(settings["fixtures_dir"])
            panden = _fixture_features(directory / "bag_panden.json") if enabled["bag"] else []
            vbos = _fixture_features(directory / "bag_vbo.json") if enabled["bag"] else []
            parcels = _fixture_features(directory / "brk.json") if enabled["brk"] else []
            if enabled["dso"]:
                dso_client = FixtureDsoClient(directory / "dso.json")
            for path in directory.glob("*.json"):
                result.input_hashes[path.name] = file_sha256(path)
            by_native = {row["properties"]["identificatie"]: (row, when) for row, when in panden}
            by_feature = {row["id"]: (row, when) for row, when in panden}
            def resolve(ref: tuple[str, str]) -> tuple[dict, str]:
                found = (by_native if ref[0] == "bag_id" else by_feature).get(ref[1])
                if found is None:
                    raise SourceError("BAG parent is missing from the synthetic example")
                return found
        else:
            # Preflight ALL credentials before making any external API request.
            dso_secret = load_secret("DSO_API_KEY_" + settings["dso_environment"]) if mode == "live" and enabled["dso"] else None
            bag_api = OgcClient(new_http(BAG_BASE, "bag"), page_size=http_settings["page_size"],
                                max_pages=http_settings["max_pages"], max_features=http_settings["max_features"]) if enabled["bag"] else None
            brk_api = OgcClient(new_http(BRK_BASE, "brk"), page_size=http_settings["page_size"],
                                max_pages=http_settings["max_pages"], max_features=http_settings["max_features"]) if enabled["brk"] else None
            def tiled(api: Any, collection: str):
                if api is not None:
                    for bbox in tiles:
                        yield from api.pages(collection, bbox=bbox)
            vbos, panden, parcels = tiled(bag_api, "verblijfsobject"), tiled(bag_api, "pand"), tiled(brk_api, "perceel")
            def resolve(ref: tuple[str, str]) -> tuple[dict, str]:
                if bag_api is None:
                    raise SourceError("BAG is not enabled")
                if ref[0] == "feature_id":
                    return bag_api.feature("pand", BAG_BASE + "/collections/pand/items/" + ref[1])
                records = list(bag_api.pages("pand", filters={"identificatie": ref[1], "limit": "2"}))
                if len(records) != 1:
                    raise SourceError("BAG identifier filter did not return exactly one pand")
                return records[0]
            host = DSO_HOSTS[settings["dso_environment"]]
            prefix = host + "/publiek/omgevingsdocumenten/api/"
            present = new_http(prefix + "presenteren/v8", "dso_present", dso_secret) if enabled["dso"] else None
            geometry = new_http(prefix + "geometrieopvragen/v1", "dso_geometry", dso_secret) if enabled["dso"] else None
            if enabled["dso"]:
                dso_client = DsoClient(present, geometry, snapshot_utc=snapshot_utc,
                                       max_pages=http_settings["max_pages"], max_features=http_settings["max_features"])
        if enabled["bag"]:
            result.tables.update(collect_bag(vbos, panden, scope=scope, resolve=resolve,
                                             max_features=http_settings["max_features"],
                                             only_residential=settings.get("only_residential_vbo", True)))
        if enabled["brk"]:
            result.tables["brk_percelen"] = collect_brk(parcels, scope=scope, max_features=http_settings["max_features"])
        if dso_client:
            documents = collect_documents(plans, geometries, dso_client,
                                            environment=settings["dso_environment"], enabled_dso=enabled["dso"],
                                            fetch_text=settings.get("fetch_publication_text", True),
                                            max_features=http_settings["max_features"], synthetic=mode == "fixtures")
            for table in ("dso_documents", "dso_document_text"):
                result.tables[table] = documents.tables[table]
            result.dso_candidates = documents.dso_candidates
        counts = {"bag": sum(len(result.tables[k]) for k in ("bag_panden", "bag_verblijfsobjecten", "bag_vbo_pand")),
                  "brk": len(result.tables["brk_percelen"]),
                  "dso": len(result.tables["dso_documents"])}
        for name, flag in enabled.items():
            result.statuses.append({"source_name": name.upper(), "status": mode.upper() if flag else "DISABLED",
                                    "environment": "SYNTHETIC" if mode == "fixtures" and flag else settings["dso_environment"] if name == "dso" else "PRODUCTION",
                                    "record_count": counts[name],
                                    "message": "Explicitly disabled, not a measured zero-result query." if not flag else ""})
        for name, api in (("BAG", bag_api), ("BRK", brk_api)):
            if api is not None and api.responses_without_crs:
                for status in result.statuses:
                    if status["source_name"] == name:
                        status["message"] = f"{api.responses_without_crs} responses omitted Content-Crs; explicit RD request and coordinate bounds were used. CRS response confirmation is incomplete."
        return result
    finally:
        for client in clients:
            client.close()
