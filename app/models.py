"""Pydantic request/response models and the Vec3 value type."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
)

from .storage import SceneObject

MODEL_URL_MAX_LENGTH = 2048

NameStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]


def _check_model_url(value: str) -> str:
    if len(value) > MODEL_URL_MAX_LENGTH:
        raise ValueError(f"model_url 長度不可超過 {MODEL_URL_MAX_LENGTH} 個字元")
    try:
        parts = urlsplit(value)
    except ValueError as exc:  # pragma: no cover - urlsplit rarely raises
        raise ValueError("model_url 必須是有效的絕對 URL") from exc
    if parts.scheme not in {"http", "https"}:
        raise ValueError("model_url 僅允許 http 或 https")
    if not parts.netloc:
        raise ValueError("model_url 必須包含 host")
    return value


ModelUrl = Annotated[str, AfterValidator(_check_model_url)]


class Vec3(BaseModel):
    """A finite 3-component vector."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    z: float = Field(allow_inf_nan=False)


class PositionVec3(Vec3):
    x: float = Field(ge=-1_000_000, le=1_000_000, allow_inf_nan=False)
    y: float = Field(ge=-1_000_000, le=1_000_000, allow_inf_nan=False)
    z: float = Field(ge=-1_000_000, le=1_000_000, allow_inf_nan=False)


class RotationVec3(Vec3):
    x: float = Field(ge=-360_000, le=360_000, allow_inf_nan=False)
    y: float = Field(ge=-360_000, le=360_000, allow_inf_nan=False)
    z: float = Field(ge=-360_000, le=360_000, allow_inf_nan=False)


class ScaleVec3(Vec3):
    x: float = Field(gt=0, le=1000, allow_inf_nan=False)
    y: float = Field(gt=0, le=1000, allow_inf_nan=False)
    z: float = Field(gt=0, le=1000, allow_inf_nan=False)


def _zero_position() -> PositionVec3:
    return PositionVec3(x=0.0, y=0.0, z=0.0)


def _zero_rotation() -> RotationVec3:
    return RotationVec3(x=0.0, y=0.0, z=0.0)


def _unit_scale() -> ScaleVec3:
    return ScaleVec3(x=1.0, y=1.0, z=1.0)


class ObjectWrite(BaseModel):
    """Shared payload for POST (create) and PUT (full replace).

    For PUT, every optional field defaults to the documented reset value, which
    is exactly the "unspecified fields are reset" contract.
    """

    model_config = ConfigDict(extra="forbid")

    name: NameStr
    model_url: ModelUrl
    position: PositionVec3 = Field(default_factory=_zero_position)
    rotation: RotationVec3 = Field(default_factory=_zero_rotation)
    scale: ScaleVec3 = Field(default_factory=_unit_scale)
    visible: StrictBool = True


class ObjectCreate(ObjectWrite):
    pass


class ObjectReplace(ObjectWrite):
    pass


class ObjectResponse(BaseModel):
    id: str
    name: str
    model_url: str
    position: Vec3
    rotation: Vec3
    scale: Vec3
    visible: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, obj: SceneObject) -> ObjectResponse:
        return cls(
            id=obj.id,
            name=obj.name,
            model_url=obj.model_url,
            position=Vec3(x=obj.position[0], y=obj.position[1], z=obj.position[2]),
            rotation=Vec3(x=obj.rotation[0], y=obj.rotation[1], z=obj.rotation[2]),
            scale=Vec3(x=obj.scale[0], y=obj.scale[1], z=obj.scale[2]),
            visible=obj.visible,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class ListResponse(BaseModel):
    items: list[ObjectResponse]
    total: int
    limit: int
    offset: int
