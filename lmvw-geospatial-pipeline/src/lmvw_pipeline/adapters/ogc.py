"""Bounded OGC API Features pagination with scope-preserving next links."""
from __future__ import annotations

from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from ..common import SourceError, digest
from ..geometry import RD_URI
from ..http import JsonClient, Payload

BAG_BASE = "https://api.pdok.nl/kadaster/bag/ogc/v2"
BRK_BASE = "https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1"


class OgcClient:
    def __init__(self, http: JsonClient, *, page_size: int = 1000, max_pages: int = 100,
                 max_features: int = 250000) -> None:
        self.http = http
        self.page_size = page_size
        self.max_pages = max_pages
        self.max_features = max_features
        self.responses_without_crs = 0

    def _get(self, url: str) -> Payload:
        result = self.http.request("GET", url)
        if result.content_crs:
            normal = result.content_crs.strip().strip("<>").rstrip("/").replace("https://", "http://")
            if normal != RD_URI:
                raise SourceError("OGC response CRS differs from requested RD New")
        else:
            self.responses_without_crs += 1
        return result

    def _url(self, url: str, collection: str, fixed: dict[str, str], *, item: bool = False) -> str:
        full = self.http.validate_url(url)
        p = urlsplit(full)
        expected = urlsplit(self.http.base).path + f"/collections/{collection}/items"
        if not (p.path == expected or (item and p.path.startswith(expected + "/"))):
            raise SourceError("OGC link points outside the requested collection")
        pairs = parse_qsl(p.query, keep_blank_values=True)
        if len({k for k, _ in pairs}) != len(pairs):
            raise SourceError("OGC link has duplicate query parameters")
        params = dict(pairs)
        for key, value in fixed.items():
            if key in params and params[key] != value:
                equivalent = False
                if key == "bbox":
                    try:
                        equivalent = tuple(map(float, params[key].split(","))) == tuple(map(float, value.split(",")))
                    except ValueError:
                        pass
                if not equivalent:
                    raise SourceError("OGC pagination changed the requested filter or CRS")
            params[key] = value
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(sorted(params.items())), ""))

    def pages(self, collection: str, *, bbox: tuple[float, ...] | None = None,
              filters: dict[str, str] | None = None) -> Iterator[tuple[dict[str, Any], str]]:
        fixed = {"f": "json", "crs": RD_URI, "limit": str(self.page_size), **(filters or {})}
        if bbox is not None:
            fixed.update(bbox=",".join(map(str, bbox)), **{"bbox-crs": RD_URI})
        url = self._url(f"{self.http.base}/collections/{collection}/items", collection, fixed)
        seen_urls, seen_pages = set(), set()
        total = 0
        expected_total = None
        for _ in range(self.max_pages):
            if url in seen_urls:
                raise SourceError("Repeated OGC next link; refusing a partial source export")
            seen_urls.add(url)
            payload = self._get(url)
            data = payload.data
            features = data.get("features")
            if data.get("type") != "FeatureCollection" or not isinstance(features, list):
                raise SourceError("OGC response is not a FeatureCollection")
            if data.get("numberReturned", len(features)) != len(features):
                raise SourceError("OGC numberReturned does not match the response")
            if isinstance(data.get("numberMatched"), int):
                if expected_total is not None and expected_total != data["numberMatched"]:
                    raise SourceError("OGC result count changed during pagination")
                expected_total = data["numberMatched"]
            total += len(features)
            if total > self.max_features:
                raise SourceError("OGC feature safety limit reached")
            page_hash = digest(features)
            if features and page_hash in seen_pages:
                raise SourceError("Repeated OGC response page")
            seen_pages.add(page_hash)
            links = {link["href"] for link in data.get("links", [])
                     if link.get("rel") == "next" and link.get("href")}
            if len(links) > 1 or (links and not features):
                raise SourceError("Inconsistent OGC pagination links")
            for feature in features:
                if not isinstance(feature, dict) or feature.get("type") != "Feature":
                    raise SourceError("Invalid OGC feature")
                yield feature, payload.retrieved_at
            if not links:
                if expected_total is not None and total != expected_total:
                    raise SourceError("OGC pagination ended before all reported features were read")
                return
            url = self._url(urljoin(url, next(iter(links))), collection, fixed)
        raise SourceError("OGC page safety limit reached; reduce the query scope")

    def feature(self, collection: str, href: str) -> tuple[dict[str, Any], str]:
        url = self._url(href, collection, {"f": "json", "crs": RD_URI}, item=True)
        payload = self._get(url)
        if payload.data.get("type") != "Feature":
            raise SourceError("OGC item endpoint did not return a Feature")
        return payload.data, payload.retrieved_at
