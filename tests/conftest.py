"""Shared test setup: configuration, fake Redis and the Flask test app."""

from pathlib import Path

from app import config

# Initialize the configuration from the example files before any app module
# is imported, because the repositories and utils read it at import time.
config.init(Path(__file__).resolve().parent.parent / "config-example")

import pytest

from app.repositories import redis_pool
from tests.fake_redis import FakeRedis


@pytest.fixture()
def fake_redis(monkeypatch) -> FakeRedis:
    """Replace the shared Redis client with an in-memory fake."""
    server = FakeRedis()
    monkeypatch.setattr(redis_pool, "get_client", lambda: server)
    return server


@pytest.fixture(scope="session")
def flask_app():
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()
