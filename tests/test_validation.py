"""Input validation rules (T05, T06, T07, T15) and error envelope details."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient


def _assert_validation_error(response, field_part: str) -> None:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert isinstance(error["details"], list) and error["details"]
    assert any(field_part in detail["field"] for detail in error["details"]), error


@pytest.mark.parametrize(
    "model_url",
    [
        "ftp://cdn.example.com/models/chair.glb",
        "javascript:alert(1)",
        "models/chair.glb",
        "/models/chair.glb",
        "//cdn.example.com/models/chair.glb",
        "https://",
    ],
)
def test_create_rejects_non_http_or_relative_model_url(
    client: TestClient, object_data: Callable[..., dict], model_url: str
) -> None:
    """T05: only absolute http(s) URLs with a host are accepted."""
    response = client.post("/api/v1/objects", json=object_data(model_url=model_url))

    _assert_validation_error(response, "model_url")


def test_create_rejects_model_url_longer_than_2048(
    client: TestClient, object_data: Callable[..., dict]
) -> None:
    too_long = "https://example.com/" + "a" * 2040
    assert len(too_long) > 2048

    response = client.post("/api/v1/objects", json=object_data(model_url=too_long))

    _assert_validation_error(response, "model_url")


@pytest.mark.parametrize(
    "scale",
    [
        {"x": 1, "y": 0, "z": 1},
        {"x": 1, "y": -0.5, "z": 1},
        {"x": -1, "y": 1, "z": 1},
        {"x": 1, "y": 1, "z": 1000.1},
    ],
)
def test_create_rejects_non_positive_or_too_large_scale(
    client: TestClient, object_data: Callable[..., dict], scale: dict
) -> None:
    """T06: every scale component must satisfy 0 < v <= 1000."""
    response = client.post("/api/v1/objects", json=object_data(scale=scale))

    _assert_validation_error(response, "scale")


@pytest.mark.parametrize("visible", ["yes", "true", 1, 0, None, []])
def test_create_rejects_non_boolean_visible(
    client: TestClient, object_data: Callable[..., dict], visible: object
) -> None:
    """T06: visible must be a JSON boolean, not a truthy substitute."""
    response = client.post("/api/v1/objects", json=object_data(visible=visible))

    _assert_validation_error(response, "visible")


@pytest.mark.parametrize(
    ("name", "case"),
    [
        ("", "empty"),
        ("   ", "whitespace only"),
        ("a" * 121, "121 chars"),
    ],
)
def test_create_rejects_invalid_name_length(
    client: TestClient, object_data: Callable[..., dict], name: str, case: str
) -> None:
    """T07: trimmed name must be 1-120 characters."""
    response = client.post("/api/v1/objects", json=object_data(name=name))

    _assert_validation_error(response, "name")


def test_create_accepts_name_of_exactly_120_characters(
    client: TestClient,
) -> None:
    name = "n" * 120

    response = client.post(
        "/api/v1/objects",
        json={
            "name": name,
            "model_url": "https://cdn.example.com/models/long-name.glb",
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == name


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
        ({"offset": -1}, "offset"),
        ({"offset": -100}, "offset"),
    ],
)
def test_list_rejects_out_of_range_pagination(
    client: TestClient, params: dict, field: str
) -> None:
    """T15: limit must be 1-100 and offset >= 0."""
    response = client.get("/api/v1/objects", params=params)

    _assert_validation_error(response, field)


def test_list_rejects_too_long_q(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    make_object(name="Chair")

    response = client.get("/api/v1/objects", params={"q": "x" * 65})

    _assert_validation_error(response, "q")


def test_list_accepts_q_of_exactly_64_characters(client: TestClient) -> None:
    response = client.get("/api/v1/objects", params={"q": "x" * 64})

    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.parametrize(
    "position",
    [
        {"x": 1, "y": 2},
        {"x": 1, "z": 2},
        {"y": 1, "z": 2},
        None,
        "not-a-vector",
    ],
)
def test_create_rejects_vec3_missing_components(
    client: TestClient, object_data: Callable[..., dict], position: object
) -> None:
    """A Vec3 must provide all of x, y and z."""
    response = client.post("/api/v1/objects", json=object_data(position=position))

    _assert_validation_error(response, "position")


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_create_rejects_non_finite_vector_components(
    client: TestClient, token: str
) -> None:
    raw = (
        '{"name":"NonFinite","model_url":"https://example.com/m.glb",'
        '"scale":{"x":1,"y":%s,"z":1}}' % token
    )

    response = client.post(
        "/api/v1/objects",
        content=raw.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    _assert_validation_error(response, "scale")


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"name": 123}, "name"),
        ({"model_url": 123}, "model_url"),
        ({"scale": {"x": "not-a-number", "y": 1, "z": 1}}, "scale"),
        ({"rotation": "abc"}, "rotation"),
    ],
)
def test_create_rejects_wrong_field_types(
    client: TestClient,
    object_data: Callable[..., dict],
    overrides: dict,
    field: str,
) -> None:
    response = client.post("/api/v1/objects", json=object_data(**overrides))

    _assert_validation_error(response, field)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"position": {"x": 1_000_001, "y": 0, "z": 0}}, "position"),
        ({"position": {"x": 0, "y": 0, "z": -1_000_001}}, "position"),
        ({"rotation": {"x": 360_001, "y": 0, "z": 0}}, "rotation"),
    ],
)
def test_create_rejects_vector_values_out_of_bounds(
    client: TestClient,
    object_data: Callable[..., dict],
    overrides: dict,
    field: str,
) -> None:
    response = client.post("/api/v1/objects", json=object_data(**overrides))

    _assert_validation_error(response, field)
