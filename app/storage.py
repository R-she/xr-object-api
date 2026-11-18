"""Storage layer: the repository protocol, in-memory and SQLite implementations."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from typing import Protocol

from .errors import NameConflictError, NotFoundError


@dataclass(frozen=True, slots=True)
class SceneObject:
    """Internal storage representation, independent of the API models."""

    id: str
    name: str
    model_url: str
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
    visible: bool
    created_at: str
    updated_at: str


class ObjectRepository(Protocol):
    def list(
        self, *, limit: int, offset: int, q: str | None
    ) -> tuple[list[SceneObject], int]: ...

    def get(self, object_id: str) -> SceneObject | None: ...

    def find_by_name(self, name: str) -> SceneObject | None: ...

    def create(self, obj: SceneObject) -> SceneObject: ...

    def replace(self, obj: SceneObject) -> SceneObject: ...

    def delete(self, object_id: str) -> bool: ...

    def clear(self) -> None: ...


def _matches(obj: SceneObject, needle: str) -> bool:
    return needle.casefold() in obj.name.casefold()


class InMemoryObjectRepository:
    """Thread-safe in-memory store used by the contract tests."""

    def __init__(self) -> None:
        self._items: dict[str, SceneObject] = {}
        self._lock = threading.RLock()

    def list(
        self, *, limit: int, offset: int, q: str | None
    ) -> tuple[list[SceneObject], int]:
        with self._lock:
            items = list(self._items.values())
        if q:
            items = [obj for obj in items if _matches(obj, q)]
        # Stable sorts: id ascending first, then created_at descending.
        items.sort(key=lambda obj: obj.id)
        items.sort(key=lambda obj: obj.created_at, reverse=True)
        total = len(items)
        return items[offset : offset + limit], total

    def get(self, object_id: str) -> SceneObject | None:
        with self._lock:
            return self._items.get(object_id)

    def find_by_name(self, name: str) -> SceneObject | None:
        key = name.casefold()
        with self._lock:
            for obj in self._items.values():
                if obj.name.casefold() == key:
                    return obj
        return None

    def create(self, obj: SceneObject) -> SceneObject:
        with self._lock:
            self._items[obj.id] = obj
        return obj

    def replace(self, obj: SceneObject) -> SceneObject:
        with self._lock:
            self._items[obj.id] = obj
        return obj

    def delete(self, object_id: str) -> bool:
        with self._lock:
            return self._items.pop(object_id, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_VEC_COLUMNS = ("px", "py", "pz", "rx", "ry", "rz", "sx", "sy", "sz")

_DDL = f"""
CREATE TABLE IF NOT EXISTS objects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    name_key    TEXT NOT NULL UNIQUE,
    model_url   TEXT NOT NULL,
    {", ".join(f"{column} REAL NOT NULL" for column in _VEC_COLUMNS)},
    visible     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
) WITHOUT ROWID;
"""

_SELECT_COLUMNS = (
    "id, name, model_url, "
    + ", ".join(_VEC_COLUMNS)
    + ", visible, created_at, updated_at"
)

_LIKE_ESCAPE = "\\"


def _escape_like(value: str) -> str:
    return (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )


class SqliteObjectRepository:
    """SQLite implementation of the same interface (P1, opt-in via XR_DB_PATH)."""

    def __init__(self, path: str) -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(_DDL)
        self._conn.commit()

    def _row_to_object(self, row: sqlite3.Row) -> SceneObject:
        return SceneObject(
            id=row["id"],
            name=row["name"],
            model_url=row["model_url"],
            position=(row["px"], row["py"], row["pz"]),
            rotation=(row["rx"], row["ry"], row["rz"]),
            scale=(row["sx"], row["sy"], row["sz"]),
            visible=bool(row["visible"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list(
        self, *, limit: int, offset: int, q: str | None
    ) -> tuple[list[SceneObject], int]:
        clause = ""
        params: list[object] = []
        if q:
            clause = f" WHERE name_key LIKE ? ESCAPE '{_LIKE_ESCAPE}'"
            params.append(f"%{_escape_like(q.casefold())}%")
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM objects" + clause, params
            ).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM objects"
                + clause
                + " ORDER BY created_at DESC, id ASC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return [self._row_to_object(row) for row in rows], int(total)

    def get(self, object_id: str) -> SceneObject | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM objects WHERE id = ?", (object_id,)
            ).fetchone()
        return self._row_to_object(row) if row is not None else None

    def find_by_name(self, name: str) -> SceneObject | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM objects WHERE name_key = ?",
                (name.casefold(),),
            ).fetchone()
        return self._row_to_object(row) if row is not None else None

    def create(self, obj: SceneObject) -> SceneObject:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO objects (id, name, name_key, model_url, "
                    + ", ".join(_VEC_COLUMNS)
                    + ", visible, created_at, updated_at) VALUES ("
                    + ", ".join(["?"] * 16)
                    + ")",
                    (
                        obj.id,
                        obj.name,
                        obj.name.casefold(),
                        obj.model_url,
                        *obj.position,
                        *obj.rotation,
                        *obj.scale,
                        int(obj.visible),
                        obj.created_at,
                        obj.updated_at,
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                raise NameConflictError(obj.name) from exc
        return obj

    def replace(self, obj: SceneObject) -> SceneObject:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "UPDATE objects SET name = ?, name_key = ?, model_url = ?, "
                    + ", ".join(f"{column} = ?" for column in _VEC_COLUMNS)
                    + ", visible = ?, updated_at = ? WHERE id = ?",
                    (
                        obj.name,
                        obj.name.casefold(),
                        obj.model_url,
                        *obj.position,
                        *obj.rotation,
                        *obj.scale,
                        int(obj.visible),
                        obj.updated_at,
                        obj.id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # Another writer took this name between the service check and
                # this UPDATE (multi-process); map it to the contract's 409.
                self._conn.rollback()
                raise NameConflictError(obj.name) from exc
            if cursor.rowcount == 0:
                # The row was deleted after the service lookup: no ghost 200.
                self._conn.rollback()
                raise NotFoundError("找不到物件")
            self._conn.commit()
        return obj

    def delete(self, object_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM objects WHERE id = ?", (object_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM objects")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
