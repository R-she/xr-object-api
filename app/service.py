"""Business rules: name uniqueness, timestamps, pagination/filtering, PUT reset."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

from .errors import NameConflictError, NotFoundError, ValidationFailedError
from .models import ObjectCreate, ObjectReplace
from .storage import ObjectRepository, SceneObject

Q_MAX_LENGTH = 64


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_z(moment: datetime) -> str:
    """UTC ISO-8601 with millisecond precision and a trailing ``Z``."""
    return (
        moment.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stamp_after(previous: str | None = None) -> str:
    """Current UTC timestamp, forced strictly newer than ``previous``."""
    stamp = isoformat_z(utc_now())
    if previous is not None and stamp <= previous:
        stamp = isoformat_z(_parse_iso(previous) + timedelta(milliseconds=1))
    return stamp


class ObjectService:
    def __init__(self, repository: ObjectRepository) -> None:
        self._repository = repository
        self._lock = threading.Lock()

    # -- reads -----------------------------------------------------------
    def list(
        self, *, limit: int, offset: int, q: str | None
    ) -> tuple[list[SceneObject], int]:
        needle = q.strip() if q is not None else ""
        if not needle:
            needle = None
        elif len(needle) > Q_MAX_LENGTH:
            raise ValidationFailedError(
                details=[
                    {
                        "field": "q",
                        "message": f"q 長度不可超過 {Q_MAX_LENGTH} 個字元",
                    }
                ]
            )
        return self._repository.list(limit=limit, offset=offset, q=needle)

    def get(self, object_id: str) -> SceneObject:
        obj = self._repository.get(object_id)
        if obj is None:
            raise NotFoundError(f"找不到物件：{object_id}")
        return obj

    # -- writes (atomic "check name -> write") ----------------------------
    def create(self, payload: ObjectCreate) -> SceneObject:
        with self._lock:
            if self._repository.find_by_name(payload.name) is not None:
                raise NameConflictError(payload.name)
            stamp = stamp_after()
            obj = SceneObject(
                id=str(uuid.uuid4()),
                name=payload.name,
                model_url=payload.model_url,
                position=(payload.position.x, payload.position.y, payload.position.z),
                rotation=(payload.rotation.x, payload.rotation.y, payload.rotation.z),
                scale=(payload.scale.x, payload.scale.y, payload.scale.z),
                visible=payload.visible,
                created_at=stamp,
                updated_at=stamp,
            )
            return self._repository.create(obj)

    def replace(self, object_id: str, payload: ObjectReplace) -> SceneObject:
        with self._lock:
            existing = self._repository.get(object_id)
            if existing is None:
                raise NotFoundError(f"找不到物件：{object_id}")
            conflict = self._repository.find_by_name(payload.name)
            if conflict is not None and conflict.id != object_id:
                raise NameConflictError(payload.name)
            updated = SceneObject(
                id=existing.id,
                name=payload.name,
                model_url=payload.model_url,
                position=(payload.position.x, payload.position.y, payload.position.z),
                rotation=(payload.rotation.x, payload.rotation.y, payload.rotation.z),
                scale=(payload.scale.x, payload.scale.y, payload.scale.z),
                visible=payload.visible,
                created_at=existing.created_at,
                updated_at=stamp_after(existing.updated_at),
            )
            return self._repository.replace(updated)

    def delete(self, object_id: str) -> None:
        with self._lock:
            if not self._repository.delete(object_id):
                raise NotFoundError(f"找不到物件：{object_id}")
