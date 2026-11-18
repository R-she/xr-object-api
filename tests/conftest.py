"""Shared fixtures.

Every test gets a brand-new application (and therefore a brand-new repository)
so tests are order-independent and never share state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app

DEFAULT_URL = "https://cdn.example.com/models/chair.glb"


@pytest.fixture()
def app_factory(monkeypatch: pytest.MonkeyPatch) -> Callable[[], FastAPI]:
    """Return a factory that builds isolated apps backed by in-memory storage.

    ``XR_DB_PATH`` is removed so a developer machine with that variable set
    cannot accidentally make tests share a SQLite file.
    """

    monkeypatch.delenv("XR_DB_PATH", raising=False)

    def _create() -> FastAPI:
        return create_app()

    return _create


@pytest.fixture()
def app(app_factory: Callable[[], FastAPI]) -> FastAPI:
    return app_factory()


@pytest.fixture()
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def sqlite_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """P1: an app backed by a throw-away SQLite database."""

    monkeypatch.setenv("XR_DB_PATH", str(tmp_path / "objects.sqlite3"))
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture()
def object_data() -> Callable[..., dict]:
    """Build a valid create/replace payload, with optional overrides."""

    def _build(**overrides: object) -> dict:
        data: dict = {"name": "Chair-01", "model_url": DEFAULT_URL}
        data.update(overrides)
        return data

    return _build


@pytest.fixture()
def make_object(client: TestClient) -> Callable[..., dict]:
    """Create an object and return its response body (asserting 201)."""

    def _make(**overrides: object) -> dict:
        data: dict = {"name": "Chair-01", "model_url": DEFAULT_URL}
        data.update(overrides)
        response = client.post("/api/v1/objects", json=data)
        assert response.status_code == 201, response.text
        return response.json()

    return _make
