"""Bounded JSON transport with source-scoped credentials and offline replay."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import requests

from .settings import SourceError, digest, read_json, utc_now, write_json
from .settings import Secret


@dataclass(frozen=True)
class Payload:
    data: dict[str, Any]
    retrieved_at: str
    content_crs: str | None = None


class JsonClient:
    """One allowed HTTPS service prefix per client, including on pagination links.

    Redirects are rejected before a second request can occur. Credentials are not
    stored in session.headers and are never included in request fingerprints,
    cached metadata, exception messages or logs. Environment proxies and .netrc
    are disabled. The OS and process owner must still protect process memory.
    """

    def __init__(self, base_url: str, *, secret: Secret | None = None,
                 cache_dir: Path | None = None,
                 attempts: int = 4, max_response_bytes: int = 50_000_000,
                 pause_seconds: float = 0.05, session: Any = None) -> None:
        self.base = base_url.rstrip("/")
        self._secret = secret
        self.cache_dir = cache_dir
        self.attempts = attempts
        self.max_response_bytes = max_response_bytes
        self.pause_seconds = pause_seconds
        self._session = session if session is not None else requests.Session()
        self._session.trust_env = False
        self.requests_made = 0
        self.cache_hits = 0
        self.validate_url(self.base + "/")

    def validate_url(self, url: str) -> str:
        full = urljoin(self.base + "/", url)
        p, b = urlsplit(full), urlsplit(self.base)
        try:
            port_ok = p.port in (None, 443)
        except ValueError:
            raise SourceError("Invalid API URL") from None
        decoded = unquote(p.path)
        if (p.scheme != "https" or p.hostname != b.hostname or not port_ok
                or p.username is not None or p.password is not None or p.fragment
                or not (p.path == b.path or p.path.startswith(b.path + "/"))
                or "\\" in full or any(v in {".", ".."} for v in decoded.split("/"))
                or "%" in decoded or any(ord(c) < 32 for c in full)):
            raise SourceError("API destination blocked by service allowlist")
        for key, _ in parse_qsl(p.query, keep_blank_values=True):
            normal = key.lower().replace("-", "_")
            if any(v in normal for v in ("key", "token", "secret", "password", "authorization")):
                raise SourceError("Credentials must never appear in an API URL")
        return full

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                body: dict[str, Any] | None = None,
                headers: dict[str, str] | None = None) -> Payload:
        method = method.upper()
        url = self.validate_url(path)
        if method not in {"GET", "POST"} or (method == "POST" and not urlsplit(url).path.endswith("/_zoek")):
            raise SourceError("Only read-only GET and _zoek POST operations are supported")
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        if params:
            pairs.extend((key, str(value)) for key, value in params.items() if value is not None)
        if len({k for k, _ in pairs}) != len(pairs):
            raise SourceError("Duplicate query parameters are not permitted")
        url = self.validate_url(urlunsplit((parts.scheme, parts.netloc, parts.path,
                                           urlencode(sorted(pairs)), "")))
        safe_headers = {"Accept": "application/json", **(headers or {})}
        if any(k.lower() in {"authorization", "x-api-key", "cookie", "host"} for k in safe_headers):
            raise SourceError("Authentication headers are owned by the transport")
        fingerprint = digest({"method": method, "url": url, "body": body, "headers": safe_headers})
        if self._secret:
            safe_headers["x-api-key"] = self._secret.reveal()
        last_code = "network"
        for attempt in range(self.attempts):
            response = None
            retry_after = None
            try:
                self.requests_made += 1
                response = self._session.request(method, url, headers=safe_headers,
                                                 json=body, timeout=(10, 60),
                                                 allow_redirects=False, verify=True, stream=True)
                status = response.status_code
                last_code = str(status)
                if status in {429, 500, 502, 503, 504}:
                    retry_after = response.headers.get("Retry-After")
                elif 300 <= status < 400:
                    raise SourceError("API redirect rejected; no credentials forwarded")
                elif not 200 <= status < 300:
                    raise SourceError(f"API HTTP {status}; response body deliberately omitted")
                else:
                    content = bytearray()
                    for chunk in response.iter_content(chunk_size=65536):
                        content.extend(chunk)
                        if len(content) > self.max_response_bytes:
                            raise SourceError("API response exceeded configured byte limit")
                    if self._secret and self._secret.reveal().encode() in content:
                        raise SourceError("API response contained credential material; response discarded")
                    try:
                        data = json.loads(content)
                    except (ValueError, UnicodeError):
                        raise SourceError("API response is not valid JSON") from None
                    if not isinstance(data, dict):
                        raise SourceError("API response must be a JSON object")
                    retrieved = utc_now()
                    crs = response.headers.get("Content-Crs")
                    if self.cache_dir:
                        write_json(self.cache_dir / (fingerprint + ".json"), {
                            "request_digest": fingerprint, "response_digest": digest(data),
                            "retrieved_at": retrieved, "content_crs": crs, "data": data,
                        })
                    if self.pause_seconds:
                        time.sleep(self.pause_seconds)
                    return Payload(data, retrieved, crs)
            except requests.RequestException:
                # No response text, URL, request object, headers or exception chain.
                last_code = "network"
            finally:
                if response is not None:
                    response.close()
            if attempt + 1 < self.attempts:
                wait = min(2**attempt, 30)
                if retry_after and retry_after.isdigit():
                    wait = min(int(retry_after), 60)
                time.sleep(wait)
        raise SourceError(f"API request failed after bounded retries ({last_code})") from None

    def close(self) -> None:
        self._session.close()


"""Bounded OGC API Features pagination with scope-preserving next links."""

from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .settings import SourceError, digest
from .geospatial import RD_URI

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
