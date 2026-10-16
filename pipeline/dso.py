"""DSO Presenteren v8 and Geometrieopvragen v1.

A geographical API hit is evidence of a search result, NOT proof that a permit
belongs to a housing plan. Local overlap and substantive confirmation are separate.
"""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from shapely.geometry import mapping
from shapely.ops import unary_union

from .settings import SourceError, digest, json_text, text
from .geospatial import RD, RD_URI, checked_geometry, geojson_wgs84, geometry_key, rd_wkt
from .http_client import JsonClient
from .sources import SourceData, native_id, source_date

DSO_HOSTS = {"PRODUCTION": "https://service.omgevingswet.overheid.nl",
             "PRE": "https://service.pre.omgevingswet.overheid.nl"}


def uri_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", value)


def _rounded(value: Any) -> Any:
    if isinstance(value, (tuple, list)):
        return [_rounded(item) for item in value]
    return round(value, 3) if isinstance(value, float) else value


def search_geometry(geom: Any) -> dict:
    result = dict(mapping(geom))
    result["coordinates"] = _rounded(result["coordinates"])
    # Only the request is rounded. Local matching uses original precision.
    checked_geometry(result)
    return result


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def document_text(payload: dict[str, Any]) -> str | None:
    """Extract ordered text without deleting repeated legal clauses or HTML execution."""
    roots = (payload.get("_embedded") or {}).get("documentComponenten", [])
    if not isinstance(roots, list):
        raise SourceError("Unexpected DSO document-component structure")
    stack = list(reversed(roots))
    fragments, visited = [], 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > 100000 or not isinstance(node, dict):
            raise SourceError("Invalid or excessively large DSO document tree")
        for field in ("kop", "inhoud"):
            value = node.get(field)
            if value:
                if not isinstance(value, str):
                    raise SourceError("DSO document text field is not a string")
                parser = _TextParser()
                parser.feed(value)
                parser.close()
                fragment = re.sub(r"\s+", " ", "".join(parser.parts)).strip()
                if fragment:
                    fragments.append(fragment)
        children = (node.get("_embedded") or {}).get("documentComponenten", [])
        if not isinstance(children, list):
            raise SourceError("Unexpected child-component structure")
        stack.extend(reversed(children))
    return "\n".join(fragments) or None


class DsoClient:
    def __init__(self, present: JsonClient | None, geometry: JsonClient | None,
                 *, snapshot_utc: str, max_pages: int = 100,
                 max_features: int = 250000) -> None:
        self.present, self.geometry_http = present, geometry
        self.snapshot_utc = snapshot_utc
        self.max_pages, self.max_features = max_pages, max_features
        self._geometry_cache: dict[str, Any] = {}

    @property
    def temporal(self) -> dict[str, str]:
        return {"geldigOp": self.snapshot_utc[:10], "inWerkingOp": self.snapshot_utc[:10],
                "beschikbaarOp": self.snapshot_utc}

    def search(self, resource: str, geom: Any) -> list[tuple[dict, str]]:
        if resource not in {"regelingen", "omgevingsvergunningen"}:
            raise SourceError("Only DSO regulations and permits are supported")
        if self.present is None:
            raise SourceError("DSO Presenteren source is not enabled")
        http = self.present
        headers = {"Content-Crs": RD_URI, "Content-Type": "application/json",
                   "Accept": "application/hal+json"}
        params = {"_expand": "true", **self.temporal}
        body = {"geometrie": search_geometry(geom)}
        size, size_key = 200, "size"
        result, seen = [], set()
        expected_total = None
        # Presenteren v8's published OpenAPI explicitly starts page numbering at 1.
        for page in range(1, self.max_pages + 1):
            response = http.request("POST", f"{resource}/_zoek", headers=headers, body=body,
                                    params={**params, "page": page, size_key: size})
            payload = response.data
            embedded = payload.get("_embedded") or {}
            items = embedded.get(resource)
            meta = payload.get("page") or {}
            if items is None and meta.get("totalElements") == 0:
                items = []
            if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
                raise SourceError("DSO response lacks the expected embedded resource list")
            content_hash = digest(items)
            if items and content_hash in seen:
                raise SourceError("DSO pagination repeated a response page")
            seen.add(content_hash)
            if meta.get("totalElements") is not None:
                count = int(meta["totalElements"])
                if expected_total is not None and count != expected_total:
                    raise SourceError("DSO result count changed during pagination")
                expected_total = count
            result.extend((item, response.retrieved_at) for item in items)
            if len(result) > self.max_features:
                raise SourceError("DSO feature safety limit reached")
            next_link = ((payload.get("_links") or {}).get("next") or {}).get("href")
            if next_link:
                # Do not follow untrusted URLs; validate then use bounded page numbers.
                next_url = http.validate_url(urljoin(http.base + f"/{resource}/_zoek", next_link))
                if urlsplit(next_url).path != urlsplit(http.base).path + f"/{resource}/_zoek":
                    raise SourceError("DSO pagination moved to an unexpected endpoint")
            total_pages = meta.get("totalPages")
            if next_link and not items:
                raise SourceError("DSO returned an empty page with a next link")
            done = (total_pages is not None and page >= int(total_pages)) or (not next_link and len(items) < size)
            if done:
                if expected_total is not None and len(result) != expected_total:
                    raise SourceError("DSO pagination ended before all reported results were read")
                if next_link:
                    raise SourceError("DSO pagination metadata contradicts its next link")
                return result
        raise SourceError("DSO page safety limit reached; reduce the query scope")

    def geometry(self, geometry_id: str) -> Any:
        if geometry_id not in self._geometry_cache:
            if self.geometry_http is None:
                raise SourceError("DSO geometry service is not enabled")
            result = self.geometry_http.request("GET", "geometrieen/" + quote(geometry_id, safe=""),
                                                params={"crs": RD_URI})
            self._geometry_cache[geometry_id] = checked_geometry(result.data)
        return self._geometry_cache[geometry_id]

    def publication(self, identifier: str) -> tuple[str | None, str]:
        if self.present is None:
            raise SourceError("DSO Presenteren is not enabled")
        result = self.present.request("GET", f"regelingen/{uri_id(identifier)}/documentstructuur",
                                      headers={"Accept": "application/hal+json"},
                                      params={**self.temporal, "_transformXml": "inhoud",
                                              "_conditieArtikel": "eigenDocumentComponent"})
        return document_text(result.data), result.retrieved_at


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _geometry_ids(item: dict, area_name: str) -> list[str]:
    areas = (item.get("_embedded") or {}).get(area_name, [])
    areas = [areas] if isinstance(areas, dict) else areas
    ids = set()
    for area in areas or []:
        if isinstance(area, dict):
            if area.get("geometrieIdentificatie"):
                ids.add(native_id(area["geometrieIdentificatie"]))
            ids.update(native_id(i) for i in area.get("geometrieIdentificaties", []))
    return sorted(ids)


def normalize_document(item: dict, resource: str, environment: str, when: str, client: Any) -> dict:
    source_type = {"regelingen": "DSO_REGELING", "omgevingsvergunningen": "DSO_OMGEVINGSVERGUNNING"}[resource]
    identifier = native_id(item.get("identificatie"))
    document_id = digest([environment, source_type, identifier])
    area = "regelingsgebied" if resource == "regelingen" else "vergunningsgebied"
    geometry_ids = _geometry_ids(item, area)
    geometry = None
    if geometry_ids:
        geometry = checked_geometry(unary_union([client.geometry(i) for i in geometry_ids]))
    authority = _dict(item.get("aangeleverdDoorEen"))
    typ = item.get("type")
    typ = typ.get("waarde") or typ.get("code") if isinstance(typ, dict) else typ
    registration, dossier = _dict(item.get("geregistreerdMet")), _dict(item.get("dossier"))
    link = ((item.get("_links") or {}).get("self") or {}).get("href")
    # Provenance URLs never include query strings or fragments.
    if link:
        p = urlsplit(link)
        link = urlunsplit((p.scheme, p.netloc, p.path, "", "")) if not p.username and not p.password else None
    return {"document_id": document_id, "source_type": source_type, "environment": environment,
            "native_id": identifier, "document_type": text(typ),
            "title": text(item.get("officieleTitel") or item.get("citeerTitel") or item.get("opschrift")),
            "document_date": source_date(registration.get("beginGeldigheid") or registration.get("beginInwerking")),
            "authority_name": text(authority.get("naam")), "authority_code": text(authority.get("code")),
            "plan_status": None, "rule_status": text(item.get("regelStatus")),
            "dossier_status": text(dossier.get("status")), "dossier_id": text(dossier.get("id")),
            "reference_number": text(item.get("referentienummer")),
            "publication_id": text(item.get("publicatieID")), "geometry_ids_json": json_text(geometry_ids),
            "geometry_wkt": rd_wkt(geometry) if geometry is not None else None,
            "geometry_geojson_wgs84": geojson_wgs84(geometry) if geometry is not None else None,
            "crs": RD if geometry is not None else None, "geometry_status": "AVAILABLE" if geometry is not None else "NOT_AVAILABLE",
            "text_status": "NOT_REQUESTED" if resource == "regelingen" else "OUT_OF_SCOPE",
            "source_url": link, "retrieved_at": when}


def collect_documents(plans: list[dict], geometries: dict, client: Any, *, environment: str,
                      enabled_dso: bool, fetch_text: bool,
                      max_features: int, synthetic: bool = False) -> SourceData:
    result = SourceData()
    areas: dict[str, dict] = {}
    for plan in plans:
        rid = plan["record_id"]
        geom = geometries[rid]
        key = geometry_key(geom)
        areas.setdefault(key, {"geometry": geom, "records": []})["records"].append(rid)
    resources = ["regelingen", "omgevingsvergunningen"] if enabled_dso else []
    docs, hashes, candidates = {}, {}, {}
    for key, area in sorted(areas.items()):
        for resource in resources:
            env = "SYNTHETIC" if synthetic else environment
            for item, when in client.search(resource, area["geometry"]):
                native = native_id(item.get("identificatie"))
                source_type = {"regelingen": "DSO_REGELING", "omgevingsvergunningen": "DSO_OMGEVINGSVERGUNNING"}[resource]
                doc_id = digest([env, source_type, native])
                content_hash = digest(item)
                if doc_id in hashes and hashes[doc_id] != content_hash:
                    raise SourceError("DSO document changed within one collection run")
                if doc_id not in docs:
                    if len(docs) >= max_features:
                        raise SourceError("Unique DSO document safety limit reached")
                    docs[doc_id] = normalize_document(item, resource, env, when, client)
                    hashes[doc_id] = content_hash
                for rid in area["records"]:
                    candidates[(rid, doc_id)] = {"record_id": rid, "document_id": doc_id,
                                                  "search_geometry_hash": key, "retrieved_at": when}
    if fetch_text:
        for doc_id in sorted(docs):
            doc = docs[doc_id]
            if doc["source_type"] != "DSO_REGELING":
                continue
            content, when = client.publication(doc["native_id"])
            doc["text_status"] = "AVAILABLE" if content else "EMPTY"
            if content:
                result.tables["dso_document_text"].append({"document_id": doc_id, "publication_text": content,
                                                          "text_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "character_count": len(content),
                                                          "retrieved_at": when})
    result.tables["dso_documents"] = [docs[key] for key in sorted(docs)]
    result.dso_candidates = [candidates[key] for key in sorted(candidates)]
    return result
