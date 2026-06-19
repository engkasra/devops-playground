"""Smoke tests used by the CI 'test' stage."""
from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "alive"


def test_ready():
    with TestClient(app) as client:
        r = client.get("/ready")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"


def test_root():
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "app" in r.json()


def test_metrics_endpoint_exposed():
    with TestClient(app) as client:
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "http_request" in r.text
