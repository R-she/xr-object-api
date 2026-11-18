"""Unified error envelope (T17) and missing-resource behavior (T16)."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient


def _assert_envelope(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")

    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], list)
    return error


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_operating_on_missing_id_returns_404(
    client: TestClient,
    object_data: Callable[..., dict],
    method: str,
) -> None:
    """T16: GET/PUT/DELETE a nonexistent id -> 404 not_found."""
    missing_id = str(uuid.uuid4())
    url = f"/api/v1/objects/{missing_id}"

    if method == "put":
        # Valid body on purpose: existence must be checked, not validation.
        response = client.put(url, json=object_data())
    else:
        response = client.request(method, url)

    error = _assert_envelope(response, 404, "not_found")
    assert error["details"] == []


def test_get_with_non_uuid_id_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/objects/not-a-uuid")

    error = _assert_envelope(response, 404, "not_found")
    assert error["details"] == []


def test_unknown_path_returns_not_found_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    _assert_envelope(response, 404, "not_found")


def test_validation_error_envelope_has_all_fields_and_dot_paths(
    client: TestClient,
) -> None:
    """T17: 422 uses the unified envelope with field/message details."""
    response = client.post(
        "/api/v1/objects",
        json={
            "name": "",
            "model_url": "ftp://bad.example/model.glb",
            "scale": {"x": 1, "y": 0, "z": 1},
        },
    )

    error = _assert_envelope(response, 422, "validation_error")
    assert error["details"]
    for detail in error["details"]:
        assert set(detail) == {"field", "message"}
        assert isinstance(detail["field"], str) and detail["field"]
        assert isinstance(detail["message"], str) and detail["message"]

    fields = [detail["field"] for detail in error["details"]]
    assert any("name" in field for field in fields)
    assert any("model_url" in field for field in fields)
    assert any("scale" in field for field in fields)


def test_malformed_json_returns_validation_error_envelope(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/objects",
        content=b'{"name": "Broken", ',
        headers={"Content-Type": "application/json"},
    )

    error = _assert_envelope(response, 422, "validation_error")
    assert error["details"]
    assert all(isinstance(detail["field"], str) for detail in error["details"])


def test_conflict_error_uses_envelope_with_name_detail(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    make_object(name="Duplicate")

    response = client.post(
        "/api/v1/objects",
        json={
            "name": "duplicate",
            "model_url": "https://cdn.example.com/models/dup.glb",
        },
    )

    error = _assert_envelope(response, 409, "name_conflict")
    assert error["details"]
    assert any("name" in detail["field"] for detail in error["details"])
