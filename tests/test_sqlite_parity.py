"""M4: SQLite repository must satisfy the same contract as in-memory storage."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


def _create(client: TestClient, name: str, url: str | None = None) -> dict:
    response = client.post(
        "/api/v1/objects",
        json={
            "name": name,
            "model_url": url or "https://cdn.example.com/models/sqlite.glb",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _ordered(objects: list[dict]) -> list[dict]:
    """created_at descending, id ascending (stable id sort first)."""
    ordered = sorted(objects, key=lambda obj: obj["id"])
    ordered.sort(key=lambda obj: obj["created_at"], reverse=True)
    return ordered


def test_sqlite_create_then_read_has_z_timestamps(sqlite_client: TestClient) -> None:
    created = _create(
        sqlite_client,
        "SQLite Object",
        "https://cdn.example.com/models/sqlite-object.glb",
    )

    assert TIMESTAMP_RE.fullmatch(created["created_at"]), created["created_at"]
    assert TIMESTAMP_RE.fullmatch(created["updated_at"]), created["updated_at"]

    response = sqlite_client.get(f"/api/v1/objects/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_sqlite_duplicate_name_is_case_insensitive_409(
    sqlite_client: TestClient,
) -> None:
    _create(sqlite_client, "SQLite Chair")

    response = sqlite_client.post(
        "/api/v1/objects",
        json={
            "name": "sqlite chair",
            "model_url": "https://cdn.example.com/models/other.glb",
        },
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "name_conflict"
    assert any("name" in detail["field"] for detail in error["details"])

    listing = sqlite_client.get("/api/v1/objects")
    assert listing.json()["total"] == 1


def test_sqlite_rename_conflict_keeps_original_name(
    sqlite_client: TestClient,
) -> None:
    alpha = _create(
        sqlite_client,
        "SQLite Alpha",
        "https://cdn.example.com/models/alpha.glb",
    )
    beta = _create(
        sqlite_client,
        "SQLite Beta",
        "https://cdn.example.com/models/beta.glb",
    )

    response = sqlite_client.put(
        f"/api/v1/objects/{alpha['id']}",
        json={
            "name": "sqlite beta",
            "model_url": "https://cdn.example.com/models/alpha.glb",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "name_conflict"

    alpha_after = sqlite_client.get(f"/api/v1/objects/{alpha['id']}")
    beta_after = sqlite_client.get(f"/api/v1/objects/{beta['id']}")
    assert alpha_after.json()["name"] == "SQLite Alpha"
    assert beta_after.json()["name"] == "SQLite Beta"
    assert sqlite_client.get("/api/v1/objects").json()["total"] == 2


def test_sqlite_put_omitting_scale_resets_it(sqlite_client: TestClient) -> None:
    created = _create(sqlite_client, "SQLite Scale")
    response = sqlite_client.put(
        f"/api/v1/objects/{created['id']}",
        json={
            "name": "SQLite Scale",
            "model_url": created["model_url"],
            "scale": {"x": 2, "y": 3, "z": 4},
        },
    )
    assert response.status_code == 200
    before_reset = response.json()
    assert before_reset["scale"] == {"x": 2, "y": 3, "z": 4}

    response = sqlite_client.put(
        f"/api/v1/objects/{created['id']}",
        json={"name": "SQLite Scale", "model_url": created["model_url"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scale"] == {"x": 1, "y": 1, "z": 1}
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] != before_reset["updated_at"]
    assert body["id"] == created["id"]


def test_sqlite_delete_returns_204_then_get_and_put_404(
    sqlite_client: TestClient,
) -> None:
    created = _create(sqlite_client, "SQLite Delete")

    deleted = sqlite_client.delete(f"/api/v1/objects/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    fetched = sqlite_client.get(f"/api/v1/objects/{created['id']}")
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "not_found"

    replaced = sqlite_client.put(
        f"/api/v1/objects/{created['id']}",
        json={
            "name": "SQLite Delete",
            "model_url": "https://cdn.example.com/models/after-delete.glb",
        },
    )
    assert replaced.status_code == 404
    assert replaced.json()["error"]["code"] == "not_found"

    assert sqlite_client.get("/api/v1/objects").json()["total"] == 0


def test_sqlite_q_search_escapes_percent_and_underscore(
    sqlite_client: TestClient,
) -> None:
    _create(sqlite_client, "a%b")
    _create(sqlite_client, "axb")
    _create(sqlite_client, "a_b")

    percent = sqlite_client.get("/api/v1/objects", params={"q": "%"})
    assert percent.status_code == 200
    assert percent.json()["total"] == 1
    assert [item["name"] for item in percent.json()["items"]] == ["a%b"]

    underscore = sqlite_client.get("/api/v1/objects", params={"q": "_"})
    assert underscore.status_code == 200
    assert underscore.json()["total"] == 1
    assert [item["name"] for item in underscore.json()["items"]] == ["a_b"]


def test_sqlite_pagination_total_and_ordering(
    sqlite_client: TestClient,
) -> None:
    created = [
        _create(
            sqlite_client,
            f"SQLite-{index:02d}",
            f"https://cdn.example.com/models/{index}.glb",
        )
        for index in range(25)
    ]

    all_response = sqlite_client.get("/api/v1/objects", params={"limit": 100})
    assert all_response.status_code == 200
    assert all_response.json()["total"] == 25
    assert len(all_response.json()["items"]) == 25

    response = sqlite_client.get(
        "/api/v1/objects", params={"limit": 10, "offset": 20}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 25
    assert body["limit"] == 10
    assert body["offset"] == 20
    assert len(body["items"]) == 5

    expected = _ordered(created)[20:25]
    assert [item["id"] for item in body["items"]] == [
        item["id"] for item in expected
    ]

    timestamps = [item["created_at"] for item in body["items"]]
    assert timestamps == sorted(timestamps, reverse=True)
    for previous, current in zip(body["items"], body["items"][1:]):
        if previous["created_at"] == current["created_at"]:
            assert previous["id"] < current["id"]


def test_sqlite_offset_beyond_total_returns_empty_page(
    sqlite_client: TestClient,
) -> None:
    for index in range(3):
        _create(sqlite_client, f"SQLite Offset {index}")

    response = sqlite_client.get(
        "/api/v1/objects", params={"limit": 20, "offset": 50}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 3
    assert body["limit"] == 20
    assert body["offset"] == 50


def test_sqlite_client_starts_with_empty_store(sqlite_client: TestClient) -> None:
    response = sqlite_client.get("/api/v1/objects")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }
