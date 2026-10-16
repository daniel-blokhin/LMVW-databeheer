import json
import os
from pathlib import Path

import pytest
import requests

from lmvw_pipeline.common import PipelineError, SourceError, read_json, write_json
from lmvw_pipeline.http import JsonClient
from lmvw_pipeline.secrets import Secret, load_secret

BASE = "https://service.pre.omgevingswet.overheid.nl/publiek/omgevingsdocumenten/api/presenteren/v8"
FAKE_CREDENTIAL = "unit-test-only-not-a-real-credential"


class Response:
    def __init__(self, data=None, status=200, headers=None, raw=None):
        self.status_code = status
        self.headers = headers or {}
        self.content = json.dumps(data or {}).encode() if raw is None else raw
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.trust_env = True

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        pass


@pytest.mark.parametrize("url", ["http://service.pre.omgevingswet.overheid.nl/", "https://evil.example/",
                                BASE.replace(".nl/", ".nl.evil.example/") + "/regelingen", BASE + "/%2e%2e/other",
                                BASE + "/%252e%252e/other", BASE + "/x?api_key=example", BASE + "/x#fragment",
                                BASE.replace("https://", "https://user:password@") + "/x",
                                BASE.replace(".nl/", ".nl:8443/") + "/x",
                                "/publiek/other-service/path"])
def test_destination_and_query_allowlist_blocks_before_request(url):
    session = Session([])
    client = JsonClient(BASE, secret=Secret(FAKE_CREDENTIAL), session=session, pause_seconds=0)
    with pytest.raises(SourceError):
        client.request("GET", url)
    assert session.calls == []


def test_header_only_credentials_and_cache_redaction(tmp_path):
    session = Session([Response({"ok": True})])
    client = JsonClient(BASE, secret=Secret(FAKE_CREDENTIAL), session=session, cache_dir=tmp_path, pause_seconds=0)
    value = client.request("GET", "regelingen")
    args, kwargs = session.calls[0]
    assert FAKE_CREDENTIAL not in args[1]
    assert kwargs["headers"]["x-api-key"] == FAKE_CREDENTIAL
    assert kwargs["verify"] is True and kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (10, 60)
    assert session.trust_env is False
    assert FAKE_CREDENTIAL not in repr(client._secret)
    for path in tmp_path.iterdir():
        assert FAKE_CREDENTIAL not in path.read_text()
        assert "x-api-key" not in path.read_text()
    assert value.data == {"ok": True}


def test_replay_requires_no_key_and_never_network(tmp_path):
    live = JsonClient(BASE, secret=Secret(FAKE_CREDENTIAL), session=Session([Response({"value": 42})]),
                      cache_dir=tmp_path, pause_seconds=0)
    first = live.request("GET", "regelingen", params={"size": 1})
    replay = JsonClient(BASE, replay_dir=tmp_path, session=Session([]), pause_seconds=0)
    assert replay.request("GET", "regelingen", params={"size": 1}) == first
    assert replay.requests_made == 0 and replay.cache_hits == 1
    with pytest.raises(SourceError, match="missing"):
        replay.request("GET", "unknown")
    path = next(tmp_path.glob("*.json"))
    data = read_json(path)
    data["data"]["value"] = 99
    write_json(path, data)
    with pytest.raises(SourceError, match="integrity"):
        replay.request("GET", "regelingen", params={"size": 1})


def test_redirect_never_forwards_key():
    response = Response(status=302, headers={"Location": "https://evil.example"})
    session = Session([response])
    client = JsonClient(BASE, secret=Secret(FAKE_CREDENTIAL), session=session, pause_seconds=0)
    with pytest.raises(SourceError, match="redirect"):
        client.request("GET", "regelingen")
    assert len(session.calls) == 1 and response.closed


def test_bounded_retry_and_no_exception_credentials(monkeypatch):
    monkeypatch.setattr("lmvw_pipeline.http.time.sleep", lambda _: None)
    session = Session([Response(status=429), requests.ConnectionError(FAKE_CREDENTIAL), Response({"ok": True})])
    client = JsonClient(BASE, secret=Secret(FAKE_CREDENTIAL), session=session, pause_seconds=0, attempts=3)
    assert client.request("GET", "regelingen").data["ok"]
    assert len(session.calls) == 3
    failed = JsonClient(BASE, secret=Secret(FAKE_CREDENTIAL), session=Session([requests.ConnectionError(FAKE_CREDENTIAL)]), attempts=1)
    with pytest.raises(SourceError) as caught:
        failed.request("GET", "regelingen")
    assert FAKE_CREDENTIAL not in str(caught.value)


@pytest.mark.parametrize("response", [Response(status=401, raw=FAKE_CREDENTIAL.encode()),
                                      Response({"echo": FAKE_CREDENTIAL}), Response(raw=b"not json"),
                                      Response(raw=b"x" * 300)])
def test_body_never_logged_or_cached_on_failure(response, tmp_path):
    client = JsonClient(BASE, secret=Secret(FAKE_CREDENTIAL), session=Session([response]),
                        cache_dir=tmp_path, pause_seconds=0, max_response_bytes=200)
    with pytest.raises(SourceError) as caught:
        client.request("GET", "regelingen")
    assert FAKE_CREDENTIAL not in str(caught.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("method,path,headers", [("DELETE", "regelingen", {}), ("POST", "mutatie", {}),
                                                 ("GET", "regelingen", {"Authorization": "not-allowed"}),
                                                 ("GET", "regelingen", {"x-api-key": "not-allowed"})])
def test_read_only_operations_and_owned_auth_headers(method, path, headers):
    client = JsonClient(BASE, session=Session([]))
    with pytest.raises(SourceError):
        client.request(method, path, headers=headers)


def test_secret_injection_is_required_and_redacted(monkeypatch):
    with pytest.raises(PipelineError, match="Missing"):
        load_secret("DSO_API_KEY_PRE")
    monkeypatch.setenv("DSO_API_KEY_PRE", FAKE_CREDENTIAL)
    value = load_secret("DSO_API_KEY_PRE")
    assert value.reveal() == FAKE_CREDENTIAL
    assert FAKE_CREDENTIAL not in repr(value) + str(value)


def test_mounted_secret_file_and_permissions(monkeypatch, tmp_path):
    path = tmp_path / "secret"
    path.write_text(FAKE_CREDENTIAL)
    path.chmod(0o600)
    monkeypatch.setenv("DSO_API_KEY_PRE_FILE", str(path))
    assert load_secret("DSO_API_KEY_PRE").reveal() == FAKE_CREDENTIAL
    if os.name == "posix":
        path.chmod(0o644)
        with pytest.raises(PipelineError, match="accessible"):
            load_secret("DSO_API_KEY_PRE")
        path.chmod(0o600)
    monkeypatch.setenv("DSO_API_KEY_PRE", FAKE_CREDENTIAL)
    with pytest.raises(PipelineError, match="not both"):
        load_secret("DSO_API_KEY_PRE")
