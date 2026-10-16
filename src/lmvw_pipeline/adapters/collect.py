"""Source selection: live requests, offline replay, synthetic fixtures or private snapshots."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from shapely import from_wkt
from shapely.geometry import mapping

from ..common import SourceError, file_sha256, read_csv, read_json
from ..config import Config
from ..geometry import RD, RD_URI, checked_geometry, geometry_key, query_scope
from ..http import JsonClient
from ..secrets import load_secret
from .bag import collect_bag
from .brk import collect_brk
from .dso import DSO_HOSTS, RP_BASE, DsoClient, collect_documents, document_text
from .models import SourceData
from .ogc import BAG_BASE, BRK_BASE, OgcClient


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
        return document_text(self.data["document_structures"][identifier]), self.data["retrieved_at"]


def _fixture_features(path: Path) -> list[tuple[dict, str]]:
    envelope = read_json(path)
    if envelope.get("content_crs") != RD_URI or envelope.get("synthetic") is not True:
        raise SourceError("Fixture must be explicitly synthetic with a declared RD CRS")
    return [(feature, envelope["retrieved_at"]) for feature in envelope["data"]["features"]]


def _snapshot_features(directory: Path, result: SourceData) -> tuple[list, list, list]:
    """Use the latest LMVW-scope _db.csv files from the supplied notebooks.

    IDs and the authoritative VBO/pand relation table are preserved as strings.
    No old notebook or precomputed plan link is executed or trusted.
    """
    required = ["bag_panden_db.csv", "bag_verblijfsobjecten_db.csv",
                "bag_verblijfsobject_pand_relatie_db.csv", "brk_percelen_db.csv"]
    data = {}
    for filename in required:
        path = directory / filename
        if not path.is_file():
            raise SourceError("A required private source snapshot is missing; see the migration guide")
        result.input_hashes[filename] = file_sha256(path)
        data[filename] = read_csv(path)
        if file_sha256(path) != result.input_hashes[filename]:
            raise SourceError("Private snapshot changed while being read")
    parents: dict[str, list[str]] = {}
    for row in data["bag_verblijfsobject_pand_relatie_db.csv"]:
        parents.setdefault(row["bag_verblijfsobject_id"], []).append(row["bag_pand_id"])
    def geom(row: dict) -> dict:
        crs = str(row.get("crs") or row.get("crs_epsg"))
        if crs not in {"28992", RD}:
            raise SourceError("Snapshot CRS is missing or not RD New")
        return mapping(checked_geometry(row["geometry_wkt"], allowed=("Point", "Polygon", "MultiPolygon")))
    panden, vbos, parcels = [], [], []
    for row in data["bag_panden_db.csv"]:
        props = {k: row.get(k) or None for k in ("status", "bouwjaar", "aantal_verblijfsobjecten", "gebruiksdoel", "documentdatum", "documentnummer")}
        props["identificatie"] = row["bag_pand_id"]
        panden.append(({"type": "Feature", "id": row["source_feature_id"], "properties": props, "geometry": geom(row)}, row["retrieved_at"]))
    for row in data["bag_verblijfsobjecten_db.csv"]:
        props = {k: row.get(k) or None for k in ("status", "gebruiksdoel", "postcode", "openbare_ruimte_naam", "huisnummer", "huisletter", "documentdatum", "documentnummer")}
        props.update(identificatie=row["bag_verblijfsobject_id"], oppervlakte=row.get("oppervlakte_m2"),
                     toevoeging=row.get("huisnummertoevoeging"), pand=parents.get(row["bag_verblijfsobject_id"], []))
        vbos.append(({"type": "Feature", "id": row["source_feature_id"], "properties": props, "geometry": geom(row)}, row["retrieved_at"]))
    brk_fields = {"identificatie_namespace": "brk_namespace", "identificatie_lokaal_id": "brk_local_id",
                  "kadastrale_gemeente_code": "kadastrale_gemeente_code", "kadastrale_gemeente_waarde": "kadastrale_gemeente_naam",
                  "sectie": "sectie", "perceelnummer": "perceelnummer", "kadastrale_grootte_waarde": "kadastrale_grootte_m2",
                  "soort_grootte_waarde": "grootte_status", "status_historie_waarde": "historie_status"}
    for row in data["brk_percelen_db.csv"]:
        props = {source: row.get(old) or None for source, old in brk_fields.items()}
        parcels.append(({"type": "Feature", "id": row["source_feature_id"], "properties": props, "geometry": geom(row)}, row["retrieved_at"]))
    return panden, vbos, parcels


def fetch_sources(config: Config, plans: list[dict], geometries: dict, run_dir: Path,
                  snapshot_utc: str, replay_from: Path | None = None) -> SourceData:
    settings, http_settings, geo = config.values["sources"], config.values["http"], config.values["geo"]
    result = SourceData()
    scope, tiles = query_scope(geometries.values(), buffer_m=geo["buffer_m"], tile_size_m=geo["tile_size_m"],
                               max_tiles=geo["max_tiles"], max_scope_km2=geo["max_scope_km2"])
    clients = []
    bag_api = brk_api = None
    dso_client = None
    mode = config.mode
    enabled = {name: settings.get(name, False) for name in ("bag", "brk", "dso", "rp")}
    def new_http(base: str, name: str, secret: Any = None) -> JsonClient:
        client = JsonClient(base, secret=secret, cache_dir=run_dir / "raw" / name,
                            replay_dir=replay_from / "raw" / name if replay_from else None,
                            attempts=http_settings["attempts"], max_response_bytes=http_settings["max_response_bytes"],
                            pause_seconds=http_settings["pause_seconds"])
        clients.append(client)
        return client
    try:
        if mode in {"fixtures", "snapshots"}:
            if mode == "fixtures":
                directory = config.resolve(settings["fixtures_dir"])
                panden = _fixture_features(directory / "bag_panden.json") if enabled["bag"] else []
                vbos = _fixture_features(directory / "bag_vbo.json") if enabled["bag"] else []
                parcels = _fixture_features(directory / "brk.json") if enabled["brk"] else []
                if enabled["dso"] or enabled["rp"]:
                    dso_client = FixtureDsoClient(directory / "dso.json")
                for path in directory.glob("*.json"):
                    result.input_hashes[path.name] = file_sha256(path)
            else:
                if enabled["dso"] or enabled["rp"]:
                    raise SourceError("No DSO response snapshots were supplied; use live or replay mode for DSO")
                panden, vbos, parcels = _snapshot_features(config.resolve(settings["snapshot_dir"]), result)
            by_native = {row["properties"]["identificatie"]: (row, when) for row, when in panden}
            by_feature = {row["id"]: (row, when) for row, when in panden}
            def resolve(ref: tuple[str, str]) -> tuple[dict, str]:
                found = (by_native if ref[0] == "bag_id" else by_feature).get(ref[1])
                if found is None:
                    raise SourceError("BAG parent is absent from the supplied source fixture or snapshot")
                return found
        else:
            if mode == "replay" and not replay_from:
                raise SourceError("Replay requires --replay-from; live fallback is disabled")
            # Preflight ALL credentials before making any external API request.
            dso_secret = load_secret("DSO_API_KEY_" + settings["dso_environment"]) if mode == "live" and enabled["dso"] else None
            rp_secret = load_secret("RUIMTELIJKE_PLANNEN_API_KEY") if mode == "live" and enabled["rp"] else None
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
            rp = new_http(RP_BASE, "rp", rp_secret) if enabled["rp"] else None
            if enabled["dso"] or enabled["rp"]:
                dso_client = DsoClient(present, geometry, rp, snapshot_utc=snapshot_utc,
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
                                            enabled_rp=enabled["rp"], fetch_text=settings.get("fetch_publication_text", True),
                                            max_features=http_settings["max_features"], synthetic=mode == "fixtures")
            for table in ("dso_documents", "dso_document_text"):
                result.tables[table] = documents.tables[table]
            result.dso_candidates = documents.dso_candidates
        counts = {"bag": sum(len(result.tables[k]) for k in ("bag_panden", "bag_verblijfsobjecten", "bag_vbo_pand")),
                  "brk": len(result.tables["brk_percelen"]),
                  "dso": sum(d["source_type"].startswith("DSO_") for d in result.tables["dso_documents"]),
                  "rp": sum(d["source_type"] == "RUIMTELIJK_PLAN" for d in result.tables["dso_documents"])}
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
