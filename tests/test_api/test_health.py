"""Tests for the API health endpoint."""

from app import config
from app._version import __version__


def test_health_includes_version_when_enabled(client, monkeypatch):
    monkeypatch.setitem(config.get_app_config()["webapp"], "show_version", True)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "version": __version__}


def test_health_omits_version_when_disabled(client, monkeypatch):
    monkeypatch.setitem(config.get_app_config()["webapp"], "show_version", False)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
