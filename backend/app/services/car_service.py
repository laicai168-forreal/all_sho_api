# app/services/car_service.py

import uuid

from fastapi import HTTPException

from app.repositories import car_repository, user_repository

WEEKLY_CHANGE_REQUEST_LIMIT = 5


def _get_user_by_sub_or_401(sub):
    user = user_repository.get_user_by_sub(sub)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(sub):
    user = _get_user_by_sub_or_401(sub)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _normalize_lookup_name(value):
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _resolve_brand(payload):
    brand_id = payload.get("brand_id")
    brand_name = _normalize_lookup_name(payload.get("brand"))

    if brand_id:
        brand = car_repository.get_brand_by_id(brand_id)
        if not brand:
            raise HTTPException(status_code=400, detail="Selected brand not found")
        return brand

    if not brand_name:
        raise HTTPException(status_code=400, detail="Brand is required")

    return car_repository.get_brand_by_name(brand_name) or car_repository.create_brand(brand_name)


def _resolve_make(payload):
    make_id = payload.get("make_id")
    make_name = _normalize_lookup_name(payload.get("make"))

    if make_id:
        make = car_repository.get_make_by_id(make_id)
        if not make:
            raise HTTPException(status_code=400, detail="Selected make not found")
        return make

    if not make_name:
        return None

    return car_repository.get_make_by_name(make_name) or car_repository.create_make(make_name)


def _resolve_product_line(payload, brand_id):
    product_line_id = payload.get("product_line_id")
    product_line_name = _normalize_lookup_name(payload.get("product_line"))

    if product_line_id:
        product_line = car_repository.get_product_line_by_id(product_line_id)
        if not product_line:
            raise HTTPException(status_code=400, detail="Selected product line not found")
        return product_line

    if not product_line_name:
        return None

    return (
        car_repository.get_product_line_by_name_and_brand(product_line_name, brand_id)
        or car_repository.create_product_line(product_line_name, brand_id)
    )


def _resolve_admin_car_payload(payload):
    resolved = payload.copy()
    brand = _resolve_brand(resolved)
    make = _resolve_make(resolved)
    product_line = _resolve_product_line(resolved, brand["id"])

    resolved["brand_id"] = brand["id"]
    resolved["brand"] = brand["name"]
    resolved["make_id"] = make["id"] if make else None
    resolved["make"] = make["name"] if make else None
    resolved["product_line_id"] = product_line["id"] if product_line else None
    resolved["product_line"] = product_line["name"] if product_line else _normalize_lookup_name(resolved.get("product_line"))
    resolved.pop("release_date_ai", None)

    return resolved


def create_admin_car(sub, payload):
    user = require_admin(sub)
    return car_repository.create_car(_resolve_admin_car_payload(payload), user["id"])


def update_admin_car(sub, car_id, payload):
    user = require_admin(sub)
    updated = car_repository.update_car(car_id, _resolve_admin_car_payload(payload), user["id"])
    if not updated:
        raise HTTPException(status_code=404, detail="Car not found")
    return updated


def delete_admin_car(sub, car_id):
    require_admin(sub)
    deleted_rows = car_repository.delete_car(car_id)
    if not deleted_rows:
        raise HTTPException(status_code=404, detail="Car not found")
    return {"message": "deleted"}


def duplicate_admin_car(sub, source_car_id, payload):
    user = require_admin(sub)
    duplicated = car_repository.duplicate_car(source_car_id, user["id"], _resolve_admin_car_payload(payload))
    if not duplicated:
        raise HTTPException(status_code=404, detail="Source car not found")
    return duplicated


def get_admin_car_form_options(sub):
    require_admin(sub)
    return {
        "brands": car_repository.list_brands(),
        "makes": car_repository.list_makes(),
        "productLines": car_repository.list_product_lines(),
    }


def submit_change_request(sub, body):
    user = _get_user_by_sub_or_401(sub)
    weekly_count = car_repository.count_weekly_change_requests(user["id"])
    if weekly_count >= WEEKLY_CHANGE_REQUEST_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Weekly submission limit reached ({WEEKLY_CHANGE_REQUEST_LIMIT})",
        )

    payload = body.copy()
    if payload.get("car_id"):
        payload["car_id"] = str(uuid.UUID(payload["car_id"]))

    return car_repository.create_change_request(payload, user["id"])


def list_user_change_requests(sub, status=None, limit=20, offset=0):
    user = _get_user_by_sub_or_401(sub)
    return car_repository.list_change_requests(
        status=status,
        submitted_by=user["id"],
        limit=limit,
        offset=offset,
    )


def get_user_change_request_summary(sub):
    user = _get_user_by_sub_or_401(sub)
    summary = car_repository.get_weekly_change_request_summary(user["id"])
    used_count = int(summary["used_count"] or 0)
    oldest_in_window = summary["oldest_in_window"]

    return {
        "weeklyLimit": WEEKLY_CHANGE_REQUEST_LIMIT,
        "usedCount": used_count,
        "remainingCount": max(WEEKLY_CHANGE_REQUEST_LIMIT - used_count, 0),
        "windowDays": 7,
        "resetAt": oldest_in_window.isoformat() if oldest_in_window else None,
    }


def list_admin_change_requests(sub, status=None, limit=20, offset=0):
    require_admin(sub)
    return car_repository.list_change_requests(
        status=status,
        limit=limit,
        offset=offset,
    )


def review_admin_change_request(sub, request_id, status, review_notes):
    admin = require_admin(sub)
    if status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid review status")

    existing = car_repository.get_change_request(request_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Change request not found")

    if existing["status"] != "pending":
        raise HTTPException(status_code=409, detail="Change request already reviewed")

    reviewed = car_repository.review_change_request(
        request_id=request_id,
        status=status,
        review_notes=review_notes,
        reviewed_by=admin["id"],
    )

    return reviewed
