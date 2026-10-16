from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from lmvw_pipeline.config import load_config
from lmvw_pipeline.intake import read_delivery
from lmvw_pipeline.validation.engine import validate_delivery

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root():
    return ROOT


@pytest.fixture
def demo_config():
    return load_config(ROOT / "configs/demo.yaml")


@pytest.fixture
def delivery(demo_config):
    return read_delivery(demo_config)


@pytest.fixture
def mapping(demo_config):
    return yaml.safe_load(demo_config.resolve(demo_config.values["mapping"]).read_text())


@pytest.fixture
def rules(demo_config):
    return yaml.safe_load(demo_config.resolve(demo_config.values["quality"]).read_text())


@pytest.fixture
def quality(delivery, mapping, rules):
    return validate_delivery(delivery, mapping, rules)


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    """A regression test must not silently call a real service or consume a key."""
    import requests
    def blocked(*args, **kwargs):
        raise AssertionError("Network disabled in all tests; install an explicit fake session")
    monkeypatch.setattr(requests.Session, "request", blocked)
    for name in ("DSO_API_KEY_PRODUCTION", "DSO_API_KEY_PRE", "RUIMTELIJKE_PLANNEN_API_KEY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name + "_FILE", raising=False)
