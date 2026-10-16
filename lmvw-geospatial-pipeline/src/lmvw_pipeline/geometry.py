"""CRS-aware geometry validation and metric query scoping."""
from __future__ import annotations

import math
from typing import Iterable

from pyproj import CRS, Transformer
from shapely import from_wkt, to_wkt
from shapely.geometry import box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from .common import PipelineError, digest, json_text

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
