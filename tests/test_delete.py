"""Delete semantics (T12)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient


def test_delete_returns_204_then_get_returns_404(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    """T12: 204 with no body, then 404 not_found."""
    created = make_object(name="Disposable")

    response = client.delete(f"/api/v1/objects/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""

    fetched = client.get(f"/api/v1/objects/{created['id']}")
    assert fetched.status_code == 404
    error = fetched.json()["error"]
    assert error["code"] == "not_found"
    assert error["details"] == []


def test_delete_removes_object_from_list_and_second_delete_is_404(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    kept = make_object(name="Kept")
    removed = make_object(name="Removed")

    assert client.delete(f"/api/v1/objects/{removed['id']}").status_code == 204

    listing = client.get("/api/v1/objects")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [kept["id"]]

    second = client.delete(f"/api/v1/objects/{removed['id']}")
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "not_found"


def test_deleted_name_can_be_reused(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    created = make_object(name="Reusable")
    assert client.delete(f"/api/v1/objects/{created['id']}").status_code == 204

    response = client.post(
        "/api/v1/objects",
        json={
            "name": "Reusable",
            "model_url": "https://cdn.example.com/models/reused.glb",
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Reusable"
