"""M5: name uniqueness must be atomic under concurrent creates."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import NameConflictError
from app.models import ObjectCreate

DEFAULT_URL = "https://cdn.example.com/models/concurrent.glb"


def test_concurrent_create_with_same_name_has_exactly_one_winner(
    app: FastAPI, client: TestClient
) -> None:
    service = app.state.service
    payload = ObjectCreate(name="Concurrent Chair", model_url=DEFAULT_URL)
    start = threading.Event()

    def attempt(_: int) -> str:
        start.wait()
        try:
            service.create(payload)
        except NameConflictError:
            return "conflict"
        return "created"

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(attempt, index) for index in range(25)]
        start.set()
        results = [future.result(timeout=10) for future in futures]

    assert results.count("created") == 1
    assert results.count("conflict") == 24

    listing = client.get("/api/v1/objects")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "Concurrent Chair"
