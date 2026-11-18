"""Object endpoints: list, create, read, full replace, delete."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from ..models import (
    ListResponse,
    ObjectCreate,
    ObjectReplace,
    ObjectResponse,
)
from ..service import ObjectService

router = APIRouter(prefix="/api/v1", tags=["objects"])


def get_service(request: Request) -> ObjectService:
    return request.app.state.service


ServiceDep = Annotated[ObjectService, Depends(get_service)]


@router.get("/objects", response_model=ListResponse)
def list_objects(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query()] = None,
) -> ListResponse:
    items, total = service.list(limit=limit, offset=offset, q=q)
    return ListResponse(
        items=[ObjectResponse.from_domain(obj) for obj in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/objects", status_code=201, response_model=ObjectResponse)
def create_object(
    payload: ObjectCreate,
    service: ServiceDep,
    response: Response,
) -> ObjectResponse:
    obj = service.create(payload)
    response.headers["Location"] = f"/api/v1/objects/{obj.id}"
    return ObjectResponse.from_domain(obj)


@router.get("/objects/{object_id}", response_model=ObjectResponse)
def get_object(object_id: str, service: ServiceDep) -> ObjectResponse:
    return ObjectResponse.from_domain(service.get(object_id))


@router.put("/objects/{object_id}", response_model=ObjectResponse)
def replace_object(
    object_id: str,
    payload: ObjectReplace,
    service: ServiceDep,
) -> ObjectResponse:
    return ObjectResponse.from_domain(service.replace(object_id, payload))


@router.delete("/objects/{object_id}", status_code=204)
def delete_object(object_id: str, service: ServiceDep) -> Response:
    service.delete(object_id)
    return Response(status_code=204)
