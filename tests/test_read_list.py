"""List/read behavior: defaults, pagination (T13) and search (T14)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient


def _sort_contract(objects: list[dict]) -> list[dict]:
    """created_at descending, id ascending (stable id sort first)."""
    ordered = sorted(objects, key=lambda obj: obj["id"])
    ordered.sort(key=lambda obj: obj["created_at"], reverse=True)
    return ordered


def test_empty_list_returns_document_defaults(client: TestClient) -> None:
    response = client.get("/api/v1/objects")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }


def test_list_pagination_returns_expected_page_and_total(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    """T13: 25 objects, limit=10&offset=20 -> 5 items, total=25, sorted."""
    created = [
        make_object(
            name=f"Object-{index:02d}",
            model_url=f"https://cdn.example.com/models/{index}.glb",
        )
        for index in range(25)
    ]

    all_response = client.get("/api/v1/objects", params={"limit": 100})
    assert all_response.status_code == 200
    assert all_response.json()["total"] == 25
    assert len(all_response.json()["items"]) == 25

    response = client.get("/api/v1/objects", params={"limit": 10, "offset": 20})
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 25
    assert body["limit"] == 10
    assert body["offset"] == 20
    assert len(body["items"]) == 5

    expected_page = _sort_contract(created)[20:25]
    assert [item["id"] for item in body["items"]] == [
        item["id"] for item in expected_page
    ]

    timestamps = [item["created_at"] for item in body["items"]]
    assert timestamps == sorted(timestamps, reverse=True)
    for previous, current in zip(body["items"], body["items"][1:]):
        if previous["created_at"] == current["created_at"]:
            assert previous["id"] < current["id"]


@pytest.mark.parametrize(
    ("query", "expected_count"),
    [
        ("chair", 3),
        ("CHaIR", 3),
        ("  chair  ", 3),
        ("air", 3),
        ("beta", 1),
        ("zzz", 0),
    ],
)
def test_list_search_is_case_insensitive_and_total_is_filtered(
    client: TestClient,
    make_object: Callable[..., dict],
    query: str,
    expected_count: int,
) -> None:
    """T14: substring match on name, total reflects the filtered set."""
    for name in ["Chair Alpha", "chair Beta", "CHAIR-03", "Table Gamma"]:
        make_object(name=name, model_url="https://cdn.example.com/models/x.glb")

    response = client.get("/api/v1/objects", params={"q": query})
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == expected_count
    assert len(body["items"]) == expected_count

    needle = query.strip().casefold()
    if needle:
        assert all(needle in item["name"].casefold() for item in body["items"])


def test_list_empty_q_is_treated_as_not_provided(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    for name in ["Chair Alpha", "chair Beta", "CHAIR-03", "Table Gamma"]:
        make_object(name=name, model_url="https://cdn.example.com/models/x.glb")

    response = client.get("/api/v1/objects", params={"q": ""})

    assert response.status_code == 200
    assert response.json()["total"] == 4
    assert len(response.json()["items"]) == 4


def test_list_limit_and_offset_are_applied_within_range(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    created = [
        make_object(
            name=f"Item-{index}",
            model_url=f"https://cdn.example.com/models/{index}.glb",
        )
        for index in range(5)
    ]

    response = client.get("/api/v1/objects", params={"limit": 2, "offset": 1})
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [item["id"] for item in body["items"]] == [
        item["id"] for item in _sort_contract(created)[1:3]
    ]


def test_list_offset_beyond_total_returns_empty_items(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    for index in range(3):
        make_object(
            name=f"Offset-{index}",
            model_url=f"https://cdn.example.com/models/{index}.glb",
        )

    response = client.get("/api/v1/objects", params={"limit": 20, "offset": 50})

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 3,
        "limit": 20,
        "offset": 50,
    }


def test_list_whitespace_only_q_is_treated_as_absent(
    client: TestClient, make_object: Callable[..., dict]
) -> None:
    make_object(name="Whitespace One")
    make_object(name="Whitespace Two")

    response = client.get("/api/v1/objects", params={"q": "   "})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
