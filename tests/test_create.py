"""Create behavior (T02, T03, T04) plus name normalization."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


def test_create_minimal_object_applies_defaults_and_location(
    client: TestClient,
) -> None:
    """T02: only name/model_url -> documented defaults + Location header."""
    response = client.post(
        "/api/v1/objects",
        json={
            "name": "Minimal Object",
            "model_url": "https://cdn.example.com/models/minimal.glb",
        },
    )

    assert response.status_code == 201
    body = response.json()

    assert body["name"] == "Minimal Object"
    assert body["model_url"] == "https://cdn.example.com/models/minimal.glb"
    assert body["position"] == {"x": 0, "y": 0, "z": 0}
    assert body["rotation"] == {"x": 0, "y": 0, "z": 0}
    assert body["scale"] == {"x": 1, "y": 1, "z": 1}
    assert body["visible"] is True

    # Server-generated UUID4.
    parsed_id = uuid.UUID(body["id"])
    assert parsed_id.version == 4
    assert str(parsed_id) == body["id"]

    # Timestamps: UTC ISO-8601, millisecond precision, trailing Z.
    assert TIMESTAMP_RE.fullmatch(body["created_at"]), body["created_at"]
    assert TIMESTAMP_RE.fullmatch(body["updated_at"]), body["updated_at"]

    # Location points at the canonical single-object URL.
    assert "location" in {key.lower() for key in response.headers}
    assert response.headers["location"] == f"/api/v1/objects/{body['id']}"

    fetched = client.get(response.headers["location"])
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_create_full_object_then_read_returns_sent_values(
    client: TestClient,
) -> None:
    """T03: full payload round-trips with exact values and Z timestamps."""
    payload = {
        "name": "Full Object",
        "model_url": "https://cdn.example.com/models/full.glb",
        "position": {"x": 1.5, "y": 0, "z": -2},
        "rotation": {"x": 0, "y": 90, "z": 0},
        "scale": {"x": 1, "y": 1.2, "z": 1},
        "visible": False,
    }

    created = client.post("/api/v1/objects", json=payload)
    assert created.status_code == 201
    created_body = created.json()

    response = client.get(f"/api/v1/objects/{created_body['id']}")
    assert response.status_code == 200
    body = response.json()

    assert body["id"] == created_body["id"]
    assert body["name"] == payload["name"]
    assert body["model_url"] == payload["model_url"]
    assert body["position"] == payload["position"]
    assert body["rotation"] == payload["rotation"]
    assert body["scale"] == payload["scale"]
    assert body["visible"] is False
    assert TIMESTAMP_RE.fullmatch(body["created_at"]), body["created_at"]
    assert TIMESTAMP_RE.fullmatch(body["updated_at"]), body["updated_at"]


@pytest.mark.parametrize("duplicate_name", ["Chair-01", "chair-01", "CHAIR-01"])
def test_create_duplicate_name_is_conflict_case_insensitively(
    client: TestClient, make_object: Callable[..., dict], duplicate_name: str
) -> None:
    """T04: same name in any casing -> 409 and no second row."""
    make_object(name="Chair-01")

    response = client.post(
        "/api/v1/objects",
        json={
            "name": duplicate_name,
            "model_url": "https://cdn.example.com/models/other.glb",
        },
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "name_conflict"
    assert isinstance(error["message"], str) and error["message"]
    assert any("name" in detail["field"] for detail in error["details"])

    listing = client.get("/api/v1/objects")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert len(listing.json()["items"]) == 1


def test_create_trims_surrounding_whitespace_from_name(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/objects",
        json={
            "name": "  Trimmed Name  ",
            "model_url": "https://cdn.example.com/models/trim.glb",
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Trimmed Name"

    # The trimmed value participates in uniqueness.
    duplicate = client.post(
        "/api/v1/objects",
        json={
            "name": "Trimmed Name",
            "model_url": "https://cdn.example.com/models/trim2.glb",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "name_conflict"
