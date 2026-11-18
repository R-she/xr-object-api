"""M1 guard: unknown/extra fields must be rejected, not silently ignored."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

DEFAULT_URL = "https://cdn.example.com/models/chair.glb"


def test_post_unknown_field_returns_422(
    client: TestClient, object_data: Callable[..., dict]
) -> None:
    response = client.post(
        "/api/v1/objects",
        json=object_data(
            name="Typo Field",
            sclae={"x": 2, "y": 2, "z": 2},
        ),
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any("sclae" in detail["field"] for detail in error["details"])

    listing = client.get("/api/v1/objects")
    assert listing.status_code == 200
    assert listing.json()["total"] == 0


def test_put_unknown_field_returns_422_and_leaves_object_unchanged(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    created = make_object(
        name="Typo On Put",
        model_url="https://cdn.example.com/models/put.glb",
        position={"x": 1, "y": 2, "z": 3},
        rotation={"x": 10, "y": 20, "z": 30},
        scale={"x": 2, "y": 2, "z": 2},
        visible=False,
    )

    response = client.put(
        f"/api/v1/objects/{created['id']}",
        json={
            "name": "Typo On Put",
            "model_url": "https://cdn.example.com/models/put.glb",
            "positon": {"x": 9, "y": 9, "z": 9},
        },
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any("positon" in detail["field"] for detail in error["details"])

    fetched = client.get(f"/api/v1/objects/{created['id']}")
    assert fetched.status_code == 200
    # Nothing changed: no reset to defaults, no timestamp movement.
    assert fetched.json() == created


def test_vec3_with_extra_component_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/objects",
        json={
            "name": "Extra Vec Component",
            "model_url": DEFAULT_URL,
            "scale": {"x": 1, "y": 1, "z": 1, "w": 9},
        },
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    fields = [detail["field"] for detail in error["details"]]
    assert any("scale" in field for field in fields)
    assert any(field.endswith("w") for field in fields)
