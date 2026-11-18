"""App/store isolation (T18) and the optional SQLite backend smoke test."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_two_app_instances_do_not_share_state(
    app_factory: Callable[[], FastAPI],
) -> None:
    """T18: each app has its own repository, so the same name succeeds twice."""
    payload = {
        "name": "Shared Name",
        "model_url": "https://cdn.example.com/models/shared.glb",
    }

    with TestClient(app_factory()) as client_a, TestClient(app_factory()) as client_b:
        created_a = client_a.post("/api/v1/objects", json=payload)
        created_b = client_b.post("/api/v1/objects", json=payload)

        assert created_a.status_code == 201
        assert created_b.status_code == 201
        assert created_a.json()["id"] != created_b.json()["id"]

        listing_a = client_a.get("/api/v1/objects")
        listing_b = client_b.get("/api/v1/objects")
        assert listing_a.json()["total"] == 1
        assert listing_b.json()["total"] == 1

        missing_in_b = client_b.get(f"/api/v1/objects/{created_a.json()['id']}")
        assert missing_in_b.status_code == 404


def test_sqlite_backend_supports_basic_roundtrip(sqlite_client: TestClient) -> None:
    """P1: XR_DB_PATH selects a SQLite repository that behaves like the API."""
    created = sqlite_client.post(
        "/api/v1/objects",
        json={
            "name": "SQLite Object",
            "model_url": "https://cdn.example.com/models/sqlite.glb",
        },
    )

    assert created.status_code == 201
    object_id = created.json()["id"]

    fetched = sqlite_client.get(f"/api/v1/objects/{object_id}")
    assert fetched.status_code == 200
    assert fetched.json() == created.json()

    listing = sqlite_client.get("/api/v1/objects")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
