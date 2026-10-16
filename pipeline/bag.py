"""BAG normalisation and authoritative VBO-to-pand relation resolution."""
from __future__ import annotations

import re
import uuid
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

from shapely.geometry.base import BaseGeometry

from .settings import SourceError, text
from .geospatial import checked_geometry
from .sources import Registry, geometry_fields, native_id, number, source_date, use_goals
from .http_client import BAG_BASE


def normalize_bag(feature: dict[str, Any], collection: str, retrieved_at: str) -> dict[str, Any]:
    p = feature.get("properties")
    if not isinstance(p, dict):
        raise SourceError("BAG feature has no properties object")
    row = {"source_feature_id": native_id(feature.get("id")), "status": text(p.get("status")),
           "gebruiksdoel": ", ".join(use_goals(p.get("gebruiksdoel"))),
           "documentdatum": source_date(p.get("documentdatum")), "documentnummer": text(p.get("documentnummer")),
           "retrieved_at": retrieved_at}
    if collection == "pand":
        row.update(bag_pand_id=native_id(p.get("identificatie"), bag=True),
                   bouwjaar=number(p.get("bouwjaar")), aantal_verblijfsobjecten=number(p.get("aantal_verblijfsobjecten")))
        allowed = ("Polygon", "MultiPolygon")
    elif collection == "verblijfsobject":
        row.update(bag_verblijfsobject_id=native_id(p.get("identificatie"), bag=True),
                   oppervlakte_m2=number(p.get("oppervlakte")), huisnummer=number(p.get("huisnummer")),
                   postcode=text(p.get("postcode")), openbare_ruimte_naam=text(p.get("openbare_ruimte_naam")),
                   huisletter=text(p.get("huisletter")), huisnummertoevoeging=text(p.get("toevoeging")))
        allowed = ("Point",)
    else:
        raise SourceError("Unsupported BAG collection")
    row.update(geometry_fields(feature.get("geometry"), allowed))
    return row


def pand_references(feature: dict[str, Any]) -> list[tuple[str, str]]:
    """Parse published BAG IDs or OGC feature UUIDs, never infer a parent by proximity."""
    values: list[Any] = []
    p = feature.get("properties") or {}
    for key in ("pand.href", "pand"):
        if key in p:
            values.append(p[key])
    values.extend(link["href"] for link in feature.get("links", [])
                  if "/collections/pand/items/" in link.get("href", ""))
    flattened: list[str] = []
    def flatten(value: Any) -> None:
        if value in (None, ""):
            return
        if isinstance(value, list):
            for item in value:
                flatten(item)
        elif isinstance(value, dict):
            if "href" in value:
                flatten(value["href"])
            elif "identificatie" in value:
                flatten(value["identificatie"])
            else:
                raise SourceError("Unknown BAG parent-reference object")
        elif isinstance(value, str):
            flattened.append(value)
        else:
            raise SourceError("BAG parent reference must be a string, list or object")
    for value in values:
        flatten(value)
    result = set()
    for value in flattened:
        if re.fullmatch(r"\d{16}", value):
            result.add(("bag_id", value))
            continue
        token = value
        if "://" in value or "/" in value:
            purl, base = urlsplit(value), urlsplit(BAG_BASE)
            prefix = base.path + "/collections/pand/items/"
            if purl.scheme != "https" or purl.netloc != base.netloc or not purl.path.startswith(prefix):
                raise SourceError("BAG parent-reference destination is not allowlisted")
            token = purl.path[len(prefix):].rstrip("/")
        try:
            result.add(("feature_id", str(uuid.UUID(token))))
        except ValueError:
            raise SourceError("Malformed BAG parent-reference identifier") from None
    return sorted(result)


def collect_bag(vbo_features: Iterable[tuple[dict, str]], pand_features: Iterable[tuple[dict, str]],
                *, scope: BaseGeometry, resolve: Callable[[tuple[str, str]], tuple[dict, str]],
                max_features: int, only_residential: bool = True) -> dict[str, list[dict]]:
    vbos, panden = Registry(max_features), Registry(max_features)
    refs_by_vbo: dict[str, list[tuple[str, str]]] = {}
    feature_to_native: dict[str, str] = {}
    for feature, when in vbo_features:
        p = feature.get("properties") or {}
        if only_residential and "woonfunctie" not in use_goals(p.get("gebruiksdoel")):
            continue
        geom = checked_geometry(feature.get("geometry"), allowed=("Point",))
        if not scope.intersects(geom):
            continue
        row = normalize_bag(feature, "verblijfsobject", when)
        key = row["bag_verblijfsobject_id"]
        if vbos.add(key, row, {"properties": p, "geometry": feature["geometry"]}):
            refs = pand_references(feature)
            if not refs:
                raise SourceError("Selected BAG VBO has no authoritative pand reference")
            refs_by_vbo[key] = refs
    def add_pand(feature: dict, when: str, supplementary: bool = False) -> None:
        geom = checked_geometry(feature.get("geometry"))
        if not supplementary and not scope.intersects(geom):
            return
        row = normalize_bag(feature, "pand", when)
        panden.add(row["bag_pand_id"], row, {"properties": feature["properties"], "geometry": feature["geometry"]})
        fid = row["source_feature_id"]
        if fid in feature_to_native and feature_to_native[fid] != row["bag_pand_id"]:
            raise SourceError("BAG feature ID maps to multiple native IDs")
        feature_to_native[fid] = row["bag_pand_id"]
    for feature, when in pand_features:
        add_pand(feature, when)
    def lookup(ref: tuple[str, str]) -> str | None:
        candidate = ref[1] if ref[0] == "bag_id" else feature_to_native.get(ref[1])
        return candidate if candidate in panden.rows else None
    missing = sorted({ref for refs in refs_by_vbo.values() for ref in refs if not lookup(ref)})
    if len(missing) > 2000:
        raise SourceError("Too many supplementary BAG parent requests")
    for ref in missing:
        feature, when = resolve(ref)
        if ref[0] == "feature_id" and feature.get("id") != ref[1]:
            raise SourceError("BAG lookup returned a different feature ID")
        if ref[0] == "bag_id" and feature.get("properties", {}).get("identificatie") != ref[1]:
            raise SourceError("BAG lookup returned a different native ID")
        add_pand(feature, when, supplementary=True)
    links = {}
    for vbo, refs in refs_by_vbo.items():
        for ref in refs:
            pand = lookup(ref)
            if pand is None:
                raise SourceError("Unresolved BAG source relation; database-ready export blocked")
            links[(vbo, pand)] = {"bag_verblijfsobject_id": vbo, "bag_pand_id": pand,
                                  "relation_basis": "OFFICIAL_BAG_REFERENCE", "retrieved_at": vbos.rows[vbo]["retrieved_at"]}
    return {"bag_panden": [panden.rows[k] for k in sorted(panden.rows)],
            "bag_verblijfsobjecten": [vbos.rows[k] for k in sorted(vbos.rows)],
            "bag_vbo_pand": [links[k] for k in sorted(links)]}
