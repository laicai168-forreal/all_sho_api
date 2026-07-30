from fastapi import APIRouter, HTTPException, Query, Request

from app.common.auth import get_current_user_sub
from app.models.collection_models import LikeCollectionRequest, UpsertCollectionRequest
from app.services import collection_service

router = APIRouter()


@router.get("/collections")
def get_collection(
    request: Request,
    page: int = 1,
    pageSize: int = 20,
    order: str = "desc",
    q: str | None = None,
    carId: str | None = None,
    metadata: bool = Query(False),
):
    sub = get_current_user_sub(request)

    try:
        return collection_service.list_collection(
            sub,
            page=page,
            page_size=pageSize,
            order=order,
            keyword=q,
            car_id=carId,
            metadata=metadata,
        )
    except ValueError as error:
        detail = str(error)
        status = 404 if detail == "Car not found" else 400
        raise HTTPException(status_code=status, detail=detail)


@router.post("/collections")
def upsert_collection(request: Request, body: UpsertCollectionRequest):
    sub = get_current_user_sub(request)

    try:
        return collection_service.upsert_collection(sub, body.dict())
    except ValueError as error:
        detail = str(error)
        status = 404 if detail == "Item not found" else 400
        raise HTTPException(status_code=status, detail=detail)


@router.delete("/collections")
def delete_collection(
    request: Request,
    carId: str,
    itemId: str | None = None,
    deleteAll: bool = False,
):
    sub = get_current_user_sub(request)

    try:
        return collection_service.delete_collection(
            sub,
            car_id=carId,
            item_id=itemId,
            delete_all=deleteAll,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/likes")
def like_collection(request: Request, body: LikeCollectionRequest):
    sub = get_current_user_sub(request)

    try:
        return collection_service.like_collection(sub, body.carId)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/likes")
def get_liked_cars(
    request: Request,
    page: int = 1,
    pageSize: int = 20,
    q: str | None = None,
):
    sub = get_current_user_sub(request)

    try:
        return collection_service.list_likes(
            sub,
            page=page,
            page_size=pageSize,
            keyword=q,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/likes")
def dislike_collection(request: Request, carId: str):
    sub = get_current_user_sub(request)

    try:
        return collection_service.dislike_collection(sub, carId)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
