from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from shapely.geometry import box

from lmvw_pipeline.adapters.bag import pand_references
from lmvw_pipeline.adapters.collect import FixtureDsoClient
from lmvw_pipeline.adapters.dso import DsoClient, collect_documents, document_text, uri_id
from lmvw_pipeline.adapters.models import Registry, native_id
from lmvw_pipeline.adapters.ogc import BAG_BASE, OgcClient
from lmvw_pipeline.common import SourceError
from lmvw_pipeline.geometry import RD_URI
from lmvw_pipeline.http import JsonClient, Payload


class FakeTransport:
    def __init__(self, base, pages):
        self.base, self.pages, self.calls = base, list(pages), []
        self.validator = JsonClient(base)

    def validate_url(self, url):
        return self.validator.validate_url(url)

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        data = self.pages.pop(0)
        return data if isinstance(data, Payload) else Payload(data, "2026-10-16T09:00:00Z", RD_URI)


def fc(number, next_link=None, total=None):
    data = {"type": "FeatureCollection", "features": [{"type": "Feature", "id": str(number), "properties": {}, "geometry": None}],
            "numberReturned": 1, "links": [{"rel": "next", "href": next_link}] if next_link else []}
    if total is not None:
        data["numberMatched"] = total
    return data


def test_ogc_relative_next_link_keeps_crs_and_bbox():
    http = FakeTransport(BAG_BASE, [fc(1, "?offset=1", 2), fc(2, total=2)])
    api = OgcClient(http, page_size=1)
    values = list(api.pages("pand", bbox=(150000., 450000., 150100., 450100.)))
    assert len(values) == 2
    second = parse_qs(urlsplit(http.calls[1][1]).query)
    assert second["crs"] == [RD_URI] and second["bbox-crs"] == [RD_URI]
    assert second["offset"] == ["1"]


@pytest.mark.parametrize("pages", [[fc(1, "?offset=1"), fc(1)],
                                    [fc(1, total=5)], [fc(1, "https://evil.example/x")],
                                    [fc(1, "?crs=EPSG:4326")]])
def test_ogc_partial_unsafe_or_repeated_pages_rejected(pages):
    api = OgcClient(FakeTransport(BAG_BASE, pages), page_size=1)
    with pytest.raises(SourceError):
        list(api.pages("pand"))


def test_ogc_wrong_response_crs_rejected():
    http = FakeTransport(BAG_BASE, [Payload(fc(1), "2026-01-01T00:00:00Z", "http://www.opengis.net/def/crs/EPSG/0/4326")])
    with pytest.raises(SourceError, match="CRS"):
        list(OgcClient(http).pages("pand"))


def test_missing_content_crs_is_visible():
    http = FakeTransport(BAG_BASE, [Payload(fc(1), "2026-01-01T00:00:00Z", None)])
    api = OgcClient(http)
    list(api.pages("pand"))
    assert api.responses_without_crs == 1


def test_authoritative_bag_references():
    uuid = "00000000-0000-4000-8000-000000000001"
    record = {"properties": {"pand": ["0000100000000001", {"href": BAG_BASE + "/collections/pand/items/" + uuid}]}}
    assert pand_references(record) == [("bag_id", "0000100000000001"), ("feature_id", uuid)]
    record["properties"]["pand"] = "https://evil.example/collections/pand/items/" + uuid
    with pytest.raises(SourceError):
        pand_references(record)


@pytest.mark.parametrize("value", [10000000001, None, "123", "000010000000000x"])
def test_bag_ids_must_be_native_strings(value):
    with pytest.raises(SourceError):
        native_id(value, bag=True)


def test_source_deduplication_does_not_hide_conflicts():
    registry = Registry(10)
    assert registry.add("SYN", {"field": 1}, {"field": 1})
    assert not registry.add("SYN", {"field": 1}, {"field": 1})
    with pytest.raises(SourceError, match="Conflicting"):
        registry.add("SYN", {"field": 2}, {"field": 2})


def test_dso_one_based_pagination_and_temporal_scope():
    base = "https://service.pre.omgevingswet.overheid.nl/publiek/omgevingsdocumenten/api/presenteren/v8"
    pages = [{"_embedded": {"regelingen": [{"identificatie": "a"}]}, "page": {"totalElements": 2, "totalPages": 2},
              "_links": {"next": {"href": "?page=2"}}},
             {"_embedded": {"regelingen": [{"identificatie": "b"}]}, "page": {"totalElements": 2, "totalPages": 2}}]
    http = FakeTransport(base, pages)
    client = DsoClient(http, None, None, snapshot_utc="2026-10-16T09:00:00Z")
    assert len(client.search("regelingen", box(150000, 450000, 150100, 450100))) == 2
    assert [call[2]["params"]["page"] for call in http.calls] == [1, 2]
    assert http.calls[0][2]["params"]["geldigOp"] == "2026-10-16"
    assert http.calls[0][2]["headers"]["Content-Crs"] == RD_URI


def test_dso_dedup_before_text_and_preserve_repeated_clauses(root, quality):
    plans = [p for p in quality.plans if p["processing_status"] != "REJECTED"]
    geoms = {p["record_id"]: quality.geometries[p["record_id"]] for p in plans}
    client = FixtureDsoClient(root / "data/sample/api/dso.json")
    result = collect_documents(plans, geoms, client, environment="PRE", enabled_dso=True, enabled_rp=True,
                               fetch_text=True, max_features=100, synthetic=True)
    assert client.publication_calls == 1  # one regulation across three geometries, four plan records
    assert len(result.tables["dso_documents"]) == 5
    assert result.tables["dso_document_text"][0]["publication_text"].count("Herhaalde clausule") == 2
    assert all(d["environment"] == "SYNTHETIC" for d in result.tables["dso_documents"])


def test_text_never_renders_script_content():
    payload = {"_embedded": {"documentComponenten": [{"kop": "Title", "inhoud": "<p>One &amp; two.</p><script>untrusted</script>"}]}}
    value = document_text(payload)
    assert "One & two." in value and "untrusted" not in value
    assert uri_id("/akn/nl/act/gm0000/2026/test") == "_akn_nl_act_gm0000_2026_test"
