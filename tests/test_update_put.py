"""Full replacement semantics (T08, T09, T10, T11)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient


def test_put_full_update_changes_updated_at_but_not_created_at(
    client: TestClient, make_object: Callable[..., dict], object_data: Callable[..., dict]
) -> None:
    """T08: complete replacement updates fields and only updated_at moves."""
    created = make_object(
        name="Update Me",
        model_url="https://cdn.example.com/models/old.glb",
        position={"x": 0, "y": 0, "z": 0},
        rotation={"x": 0, "y": 0, "z": 0},
        scale={"x": 1, "y": 1, "z": 1},
        visible=True,
    )

    payload = object_data(
        name="Updated Object",
        model_url="https://cdn.example.com/models/new.glb",
        position={"x": -1, "y": 2.5, "z": 3},
        rotation={"x": 10, "y": 20, "z": 30},
        scale={"x": 2, "y": 2, "z": 2},
        visible=False,
    )

    response = client.put(f"/api/v1/objects/{created['id']}", json=payload)
    assert response.status_code == 200
    body = response.json()

    assert body["id"] == created["id"]
    assert body["name"] == "Updated Object"
    assert body["model_url"] == "https://cdn.example.com/models/new.glb"
    assert body["position"] == {"x": -1, "y": 2.5, "z": 3}
    assert body["rotation"] == {"x": 10, "y": 20, "z": 30}
    assert body["scale"] == {"x": 2, "y": 2, "z": 2}
    assert body["visible"] is False

    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] != created["updated_at"]
    assert body["updated_at"] > created["updated_at"]

    fetched = client.get(f"/api/v1/objects/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_put_omitting_scale_resets_it_to_unit_scale(
    client: TestClient, make_object: Callable[..., dict], object_data: Callable[..., dict]
) -> None:
    """T09: omitted scale is reset, not preserved."""
    created = make_object(
        name="Scale Reset",
        model_url="https://cdn.example.com/models/scale.glb",
        scale={"x": 2, "y": 3, "z": 4},
    )

    response = client.put(
        f"/api/v1/objects/{created['id']}",
        json=object_data(
            name="Scale Reset",
            model_url="https://cdn.example.com/models/scale.glb",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scale"] == {"x": 1, "y": 1, "z": 1}
    assert body["id"] == created["id"]
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] != created["updated_at"]


def test_put_resets_every_omitted_optional_field(
    client: TestClient, make_object: Callable[..., dict], object_data: Callable[..., dict]
) -> None:
    created = make_object(
        name="Reset All",
        model_url="https://cdn.example.com/models/reset.glb",
        position={"x": 5, "y": 6, "z": 7},
        rotation={"x": 45, "y": 90, "z": 180},
        scale={"x": 3, "y": 3, "z": 3},
        visible=False,
    )

    response = client.put(
        f"/api/v1/objects/{created['id']}",
        json=object_data(
            name="Reset All",
            model_url="https://cdn.example.com/models/reset.glb",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["position"] == {"x": 0, "y": 0, "z": 0}
    assert body["rotation"] == {"x": 0, "y": 0, "z": 0}
    assert body["scale"] == {"x": 1, "y": 1, "z": 1}
    assert body["visible"] is True


@pytest.mark.parametrize("missing_field", ["name", "model_url"])
def test_put_missing_required_field_returns_422(
    client: TestClient,
    make_object: Callable[..., dict],
    object_data: Callable[..., dict],
    missing_field: str,
) -> None:
    """T10: both name and model_url are required on PUT."""
    created = make_object(name="Needs Required Fields")

    payload = object_data()
    payload.pop(missing_field)

    response = client.put(f"/api/v1/objects/{created['id']}", json=payload)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(missing_field in detail["field"] for detail in error["details"])

    # The stored object is untouched.
    unchanged = client.get(f"/api/v1/objects/{created['id']}")
    assert unchanged.status_code == 200
    assert unchanged.json()["name"] == "Needs Required Fields"


def test_put_renaming_to_another_objects_name_returns_409(
    client: TestClient, make_object: Callable[..., dict], object_data: Callable[..., dict]
) -> None:
    """T11: conflict is rejected and the original name is kept."""
    alpha = make_object(name="Alpha", model_url="https://cdn.example.com/models/a.glb")
    beta = make_object(name="Beta", model_url="https://cdn.example.com/models/b.glb")

    response = client.put(
        f"/api/v1/objects/{alpha['id']}",
        json=object_data(
            name="beta", model_url="https://cdn.example.com/models/a.glb"
        ),
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "name_conflict"
    assert any("name" in detail["field"] for detail in error["details"])

    alpha_after = client.get(f"/api/v1/objects/{alpha['id']}")
    assert alpha_after.status_code == 200
    assert alpha_after.json()["name"] == "Alpha"

    beta_after = client.get(f"/api/v1/objects/{beta['id']}")
    assert beta_after.status_code == 200
    assert beta_after.json()["name"] == "Beta"

    listing = client.get("/api/v1/objects")
    assert listing.json()["total"] == 2


def test_put_can_change_only_the_casing_of_its_own_name(
    client: TestClient, make_object: Callable[..., dict], object_data: Callable[..., dict]
) -> None:
    created = make_object(name="Alpha")

    response = client.put(
        f"/api/v1/objects/{created['id']}",
        json=object_data(name="ALPHA", model_url=created["model_url"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["name"] == "ALPHA"
    assert body["created_at"] == created["created_at"]

    fetched = client.get(f"/api/v1/objects/{created['id']}")
    assert fetched.json()["name"] == "ALPHA"


def test_put_conflict_does_not_modify_the_target_object(
    client: TestClient, make_object: Callable[..., dict], object_data: Callable[..., dict]
) -> None:
    alpha = make_object(
        name="Alpha",
        model_url="https://cdn.example.com/models/a.glb",
        position={"x": 1, "y": 2, "z": 3},
        visible=False,
    )
    make_object(name="Beta")

    rejected = client.put(
        f"/api/v1/objects/{alpha['id']}",
        json=object_data(
            name="Beta",
            model_url="https://cdn.example.com/models/changed.glb",
            position={"x": 9, "y": 9, "z": 9},
        ),
    )
    assert rejected.status_code == 409

    fetched = client.get(f"/api/v1/objects/{alpha['id']}")
    body = fetched.json()
    assert body["name"] == "Alpha"
    assert body["model_url"] == "https://cdn.example.com/models/a.glb"
    assert body["position"] == {"x": 1, "y": 2, "z": 3}
    assert body["visible"] is False
    assert body["updated_at"] == alpha["updated_at"]


def test_put_invalid_scale_returns_422_and_keeps_object_unchanged(
    client: TestClient, make_object: Callable[..., dict], object_data: Callable[..., dict]
) -> None:
    created = make_object(
        name="Invalid PUT Scale",
        model_url="https://cdn.example.com/models/invalid-put.glb",
        position={"x": 1, "y": 2, "z": 3},
        rotation={"x": 5, "y": 10, "z": 15},
        scale={"x": 2, "y": 2, "z": 2},
        visible=False,
    )

    response = client.put(
        f"/api/v1/objects/{created['id']}",
        json=object_data(
            name="Invalid PUT Scale",
            model_url="https://cdn.example.com/models/invalid-put.glb",
            position={"x": 9, "y": 9, "z": 9},
            scale={"x": 0, "y": 1, "z": 1},
            visible=True,
        ),
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any("scale" in detail["field"] for detail in error["details"])

    fetched = client.get(f"/api/v1/objects/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created
