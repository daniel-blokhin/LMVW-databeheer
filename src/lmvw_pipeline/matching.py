"""Spatial matching with explicit boundary rules and authoritative BAG relations."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from shapely import STRtree, from_wkt

from .common import ContractError, digest
from .adapters.models import SourceData


def match_sources(plans: list[dict], geometries: dict, sources: SourceData,
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
