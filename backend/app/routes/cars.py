# app/routes/cars.py

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.common.auth import get_current_user_sub
from app.models.car_models import (
    CarChangeRequestCreate,
    CarChangeRequestReview,
    CarChangeRequestUpdate,
    CarMutationRequest,
    CarDuplicateRequest,
)
from app.services import car_service

router = APIRouter()


@router.post("/admin/cars")
def create_admin_car(request: Request, body: CarMutationRequest):
    sub = get_current_user_sub(request)
    return car_service.create_admin_car(sub, body.dict(exclude_none=True))


@router.get("/admin/car-form-options")
def get_admin_car_form_options(request: Request):
    sub = get_current_user_sub(request)
    return car_service.get_admin_car_form_options(sub)


@router.post("/admin/cars/{car_id}")
def update_admin_car(request: Request, car_id: UUID, body: CarMutationRequest):
    sub = get_current_user_sub(request)
    return car_service.update_admin_car(sub, str(car_id), body.dict(exclude_none=True))


@router.delete("/admin/cars/{car_id}")
def delete_admin_car(request: Request, car_id: UUID):
    sub = get_current_user_sub(request)
    return car_service.delete_admin_car(sub, str(car_id))


@router.post("/admin/cars/{car_id}/duplicate")
def duplicate_admin_car(request: Request, car_id: UUID, body: CarDuplicateRequest):
    sub = get_current_user_sub(request)
    return car_service.duplicate_admin_car(sub, str(car_id), body.dict(exclude_none=True))


@router.get("/admin/car-change-requests")
def list_admin_change_requests(
    request: Request,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    sub = get_current_user_sub(request)
    return car_service.list_admin_change_requests(sub, status=status, limit=limit, offset=offset)


@router.get("/admin/car-change-requests/{request_id}")
def get_admin_change_request(request: Request, request_id: UUID):
    sub = get_current_user_sub(request)
    return car_service.get_admin_change_request(sub, str(request_id))


@router.post("/admin/car-change-requests/{request_id}/review")
def review_admin_change_request(request: Request, request_id: UUID, body: CarChangeRequestReview):
    sub = get_current_user_sub(request)
    return car_service.review_admin_change_request(
        sub=sub,
        request_id=str(request_id),
        status=body.status,
        review_notes=body.reviewNotes,
        final_payload=body.finalPayload,
    )


@router.post("/car-change-requests")
def submit_change_request(request: Request, body: CarChangeRequestCreate):
    sub = get_current_user_sub(request)
    return car_service.submit_change_request(sub, body.dict(exclude_none=True))


@router.get("/car-change-requests")
def list_my_change_requests(
    request: Request,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    sub = get_current_user_sub(request)
    return car_service.list_user_change_requests(sub, status=status, limit=limit, offset=offset)


@router.get("/car-change-requests/summary")
def get_my_change_request_summary(request: Request):
    sub = get_current_user_sub(request)
    return car_service.get_user_change_request_summary(sub)


@router.get("/car-change-requests/{request_id}")
def get_my_change_request(request: Request, request_id: UUID):
    sub = get_current_user_sub(request)
    return car_service.get_user_change_request(sub, str(request_id))


@router.post("/car-change-requests/{request_id}")
def update_my_change_request(request: Request, request_id: UUID, body: CarChangeRequestUpdate):
    sub = get_current_user_sub(request)
    return car_service.update_user_change_request(sub, str(request_id), body.dict(exclude_none=True))
