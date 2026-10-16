"""DSO API key must only be injected into authorized HTTPS request headers."""
import json
from pathlib import Path

import pytest

from pipeline.http_client import JsonClient
from pipeline.settings import PipelineError, SourceError, Secret, load_secret
from pipeline.run import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://service.pre.omgevingswet.overheid.nl/publiek/omgevingsdocumenten/api/presenteren/v8"


class Response:
    def __init__(self, status=200):
        self.status_code = status
        self.headers = {}
    def iter_content(self, chunk_size):
        yield b'{"ok": true}'
    def close(self):
        pass


class Session:
    def __init__(self, status=200):
        self.status = status
        self.calls = []
        self.trust_env = True
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return Response(self.status)
    def close(self):
        pass


def test_secret_loaded_at_runtime_and_redacted(monkeypatch):
    monkeypatch.setenv("DSO_API_KEY_PRE", "unit-test-secret-not-real")
    secret = load_secret("DSO_API_KEY_PRE")
    assert secret.reveal() == "unit-test-secret-not-real"
    assert "unit-test-secret-not-real" not in repr(secret)
    assert "unit-test-secret-not-real" not in str(secret)


def test_no_placeholder_is_accepted(monkeypatch):
    monkeypatch.setenv("DSO_API_KEY_PRE", "placeholder")
    with pytest.raises(PipelineError):
        load_secret("DSO_API_KEY_PRE")


def test_destination_allowlist_rejects_other_domains_and_http():
    client = JsonClient(BASE)
    with pytest.raises(SourceError):
        client.validate_url("http://service.pre.omgevingswet.overheid.nl/leak")
    with pytest.raises(SourceError):
        client.validate_url("https://attacker.invalid/capture")


def test_secret_only_sent_in_header_not_query_or_logs(tmp_path):
    session = Session()
    secret = Secret("unit-test-secret-not-real")
    client = JsonClient(BASE, secret=secret, session=session, cache_dir=tmp_path, attempts=1, pause_seconds=0)
    client.request("GET", "regelingen/example/documentstructuur")
    _, url, kwargs = session.calls[0]
    assert "unit-test-secret-not-real" not in url
    assert kwargs["headers"]["x-api-key"] == secret.reveal()
    assert kwargs["allow_redirects"] is False
    assert "unit-test-secret-not-real" not in repr(list(tmp_path.glob("*")))
    assert all("unit-test-secret-not-real" not in f.read_text() for f in tmp_path.glob("*"))


def test_live_mode_fails_without_dso_secret_before_api_calls(tmp_path, monkeypatch):
    monkeypatch.delenv("DSO_API_KEY_PRODUCTION", raising=False)
    monkeypatch.delenv("DSO_API_KEY_PRODUCTION_FILE", raising=False)
    with pytest.raises(PipelineError, match="Missing runtime credential"):
        run_pipeline(ROOT / "config.yaml", mode="live", output_dir=tmp_path)


def test_redirect_does_not_forward_credential():
    session = Session(status=302)
    client = JsonClient(BASE, secret=Secret("unit-test-secret-not-real"), session=session, attempts=1, pause_seconds=0)
    with pytest.raises(SourceError, match="redirect"):
        client.request("GET", "regelingen/example/documentstructuur")
    assert len(session.calls) == 1
