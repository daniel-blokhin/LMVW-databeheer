"""Public BRK cadastral-map parcels only: no ownership or rights inference."""
from __future__ import annotations

from typing import Iterable

from shapely.geometry.base import BaseGeometry

from .settings import SourceError, text
from .geospatial import checked_geometry
from .sources import Registry, decimal_number, geometry_fields, native_id, number


def normalize_brk(feature: dict, retrieved_at: str) -> dict:
    p = feature.get("properties")
    if not isinstance(p, dict):
        raise SourceError("BRK feature has no properties object")
    row = {"source_feature_id": native_id(feature.get("id")),
           "brk_namespace": native_id(p.get("identificatie_namespace")),
           "brk_local_id": native_id(p.get("identificatie_lokaal_id")),
           "kadastrale_gemeente_code": text(p.get("kadastrale_gemeente_code")),
           "kadastrale_gemeente_naam": text(p.get("kadastrale_gemeente_waarde")),
           "sectie": text(p.get("sectie")), "perceelnummer": number(p.get("perceelnummer")),
           "kadastrale_grootte_m2": decimal_number(p.get("kadastrale_grootte_waarde")),
           "grootte_status": text(p.get("soort_grootte_waarde")),
           "historie_status": text(p.get("status_historie_waarde")), "retrieved_at": retrieved_at}
    row.update(geometry_fields(feature.get("geometry"), ("Polygon", "MultiPolygon")))
    return row


def collect_brk(features: Iterable[tuple[dict, str]], *, scope: BaseGeometry, max_features: int) -> list[dict]:
    registry = Registry(max_features)
    for feature, when in features:
        geom = checked_geometry(feature.get("geometry"))
        if not scope.intersects(geom):
            continue
        row = normalize_brk(feature, when)
        registry.add((row["brk_namespace"], row["brk_local_id"]), row,
                     {"properties": feature["properties"], "geometry": feature["geometry"]})
    return [registry.rows[key] for key in sorted(registry.rows)]
