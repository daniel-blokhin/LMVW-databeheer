"""CRS-aware geometry validation and metric query scoping."""
from __future__ import annotations

import math
from typing import Iterable

from pyproj import CRS, Transformer
from shapely import from_wkt, to_wkt
from shapely.geometry import box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from .settings import PipelineError, digest, json_text

RD = "EPSG:28992"
WGS84 = "EPSG:4326"
RD_URI = "http://www.opengis.net/def/crs/EPSG/0/28992"
_TO_WGS84 = Transformer.from_crs(RD, WGS84, always_xy=True)


def checked_geometry(value: BaseGeometry | str | dict, *, crs: str = RD,
                     allowed: tuple[str, ...] = ("Polygon", "MultiPolygon")) -> BaseGeometry:
    """Reject rather than silently repair source geometry or guess its CRS."""
    try:
        geom = from_wkt(value) if isinstance(value, str) else shape(value) if isinstance(value, dict) else value
        source = CRS.from_user_input(crs)
        if geom is None or geom.is_empty or not geom.is_valid or geom.geom_type not in allowed:
            raise ValueError("Invalid geometry")
        if geom.has_z or geom.has_m:
            raise ValueError("Only two-dimensional geometry is supported")
        if source != CRS.from_epsg(28992):
            converter = Transformer.from_crs(source, RD, always_xy=True)
            geom = transform(converter.transform, geom)
        x1, y1, x2, y2 = geom.bounds
        if not all(math.isfinite(v) for v in geom.bounds):
            raise ValueError("Non-finite coordinates")
        if not (-100000 <= x1 <= x2 <= 400000 and 200000 <= y1 <= y2 <= 700000):
            raise ValueError("Coordinates outside European Netherlands RD range")
        if not geom.is_valid or (geom.geom_type in {"Polygon", "MultiPolygon"} and geom.area <= 0):
            raise ValueError("Invalid transformed geometry")
        return geom
    except Exception:
        # Shapely and pyproj details are intentionally not exposed with raw WKT.
        raise PipelineError("Invalid geometry, unsupported type, CRS or coordinate range") from None


def rd_wkt(geom: BaseGeometry) -> str:
    # Full double precision for calculations and round-tripping; no .buffer(0).
    return to_wkt(geom, rounding_precision=-1, trim=True)


def geojson_wgs84(geom: BaseGeometry) -> str:
    return json_text(mapping(transform(_TO_WGS84.transform, geom)))


def geometry_key(geom: BaseGeometry) -> str:
    return digest(geom.normalize().wkb_hex)


def query_scope(geometries: Iterable[BaseGeometry], *, buffer_m: float,
                tile_size_m: float, max_tiles: int, max_scope_km2: float) -> tuple[BaseGeometry, list[tuple[float, ...]]]:
    geoms = list(geometries)
    if not geoms:
        raise PipelineError("No eligible plan geometry; no API requests made")
    scope = unary_union(geoms).buffer(buffer_m) if buffer_m else unary_union(geoms)
    if scope.area / 1e6 > max_scope_km2:
        raise PipelineError("Source scope exceeds the configured area limit")
    # Enumerate tiles per component, avoiding a huge national bounding-box loop.
    parts = list(scope.geoms) if hasattr(scope, "geoms") else [scope]
    tile_keys: set[tuple[int, int]] = set()
    for part in parts:
        x1, y1, x2, y2 = part.bounds
        a, b = math.floor(x1 / tile_size_m), math.floor(y1 / tile_size_m)
        c, d = math.floor(x2 / tile_size_m), math.floor(y2 / tile_size_m)
        if (c - a + 1) * (d - b + 1) > max_tiles * 100:
            raise PipelineError("Query bounding box is too large")
        for ix in range(a, c + 1):
            for iy in range(b, d + 1):
                tile = box(ix * tile_size_m, iy * tile_size_m, (ix + 1) * tile_size_m, (iy + 1) * tile_size_m)
                if part.intersects(tile):
                    tile_keys.add((ix, iy))
                    if len(tile_keys) > max_tiles:
                        raise PipelineError("Too many API query tiles; reduce scope explicitly")
    tiles = [(x * tile_size_m, y * tile_size_m, (x + 1) * tile_size_m, (y + 1) * tile_size_m)
             for x, y in sorted(tile_keys)]
    return scope, tiles


"""Spatial matching with explicit boundary rules and authoritative BAG relations."""

from collections import defaultdict
from typing import Any

from shapely import STRtree, from_wkt

from .settings import ContractError, digest


def match_sources(plans: list[dict], geometries: dict, sources: Any,
                  min_overlap_m2: float) -> tuple[dict[str, list[dict]], list[dict]]:
    result = {name: [] for name in ("plan_bag_vbo", "plan_bag_pand", "plan_brk_perceel", "plan_dso")}
    issues = []
    vbos = sources.tables["bag_verblijfsobjecten"]
    panden = sources.tables["bag_panden"]
    parcels = sources.tables["brk_percelen"]
    vg = [from_wkt(row["geometry_wkt"]) for row in vbos]
    pg = [from_wkt(row["geometry_wkt"]) for row in panden]
    bg = [from_wkt(row["geometry_wkt"]) for row in parcels]
    vt, pt, bt = STRtree(vg), STRtree(pg), STRtree(bg)
    pand_lookup = {row["bag_pand_id"]: i for i, row in enumerate(panden)}
    parents = defaultdict(set)
    for relation in sources.tables["bag_vbo_pand"]:
        parents[relation["bag_verblijfsobject_id"]].add(relation["bag_pand_id"])
    for plan in plans:
        rid = plan["record_id"]
        geom = geometries[rid]
        via = defaultdict(set)
        for i in vt.query(geom, predicate="intersects"):
            vbo = vbos[i]["bag_verblijfsobject_id"]
            result["plan_bag_vbo"].append({"record_id": rid, "bag_verblijfsobject_id": vbo,
                                           "match_method": "SPATIAL_POINT_COVERED_BY_PLAN",
                                           "spatial_relation": "INTERIOR" if geom.contains(vg[i]) else "BOUNDARY_INCLUDED"})
            for pand in parents[vbo]:
                via[pand].add(vbo)
        direct = {}
        for i in pt.query(geom, predicate="intersects"):
            area = float(geom.intersection(pg[i]).area)
            if area >= min_overlap_m2:
                direct[panden[i]["bag_pand_id"]] = area
        for pand in sorted(set(direct) | set(via)):
            if pand not in pand_lookup:
                raise ContractError("Official BAG relation refers to a missing pand")
            spatial, official = pand in direct, pand in via
            method = "SPATIAL_AND_OFFICIAL_BAG" if spatial and official else "SPATIAL_AREA_OVERLAP" if spatial else "OFFICIAL_BAG_VBO_PAND"
            result["plan_bag_pand"].append({"record_id": rid, "bag_pand_id": pand,
                                            "match_method": method,
                                            "spatial_relation": "POSITIVE_AREA_OVERLAP" if spatial else "VIA_VBO_WITHOUT_AREA_MATCH",
                                            "overlap_area_m2": f"{direct[pand]:.3f}" if spatial else None,
                                            "via_vbo_count": len(via.get(pand, set()))})
        for i in bt.query(geom, predicate="intersects"):
            area = float(geom.intersection(bg[i]).area)
            if area < min_overlap_m2:
                continue
            row = parcels[i]
            result["plan_brk_perceel"].append({"record_id": rid, "brk_namespace": row["brk_namespace"],
                                               "brk_local_id": row["brk_local_id"], "match_method": "POSITIVE_AREA_OVERLAP",
                                               "intersection_area_m2": f"{area:.3f}",
                                               "overlap_pct_plan": f"{area / geom.area * 100:.6f}",
                                               "overlap_pct_perceel": f"{area / bg[i].area * 100:.6f}"})
    docs = {row["document_id"]: row for row in sources.tables["dso_documents"]}
    plan_by_id = {row["record_id"]: row for row in plans}
    for candidate in sources.dso_candidates:
        rid, did = candidate["record_id"], candidate["document_id"]
        doc, geom = docs[did], geometries[rid]
        area = None
        verified = False
        state = "API_CANDIDATE_UNVERIFIED"
        if doc["geometry_wkt"]:
            doc_geom = from_wkt(doc["geometry_wkt"])
            area = float(geom.intersection(doc_geom).area)
            verified = area >= min_overlap_m2
            state = "SPATIAL_MATCH" if verified else "BOUNDARY_ONLY" if geom.intersects(doc_geom) else "API_CANDIDATE_OUTSIDE"
        result["plan_dso"].append({**candidate, "relation_basis": "API_GEOGRAPHICAL_SEARCH",
                                   "relation_status": state, "spatial_verified": verified,
                                   "substantively_confirmed": False,
                                   "overlap_area_m2": None if area is None else f"{area:.3f}"})
        if not verified:
            issues.append({"issue_id": digest([rid, did, "DQ-LINK-001"]), "record_id": rid,
                           "source_name": "DSO", "source_object_id": did,
                           "source_row_number": plan_by_id[rid]["source_row_number"],
                           "rule_id": "DQ-LINK-001", "category": "SpatialEvidence", "severity": "WARNING",
                           "field_name": "relation_status", "source_value": state,
                           "message": "API candidate has no locally verified positive-area match; substantive confirmation remains false."})
    return result, issues
