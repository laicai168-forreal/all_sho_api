# Car Editor API Notes

This document describes the API surface added for the admin car editor and customer car suggestion workflow.

## Auth and Ownership

- All endpoints in this document are authenticated.
- Admin endpoints require a user with `role = 'admin'`.
- Customer suggestion endpoints create pending review records and do not mutate `cars` directly.

## Recent Backend Changes

### User role support

- `GET /users/me` now returns `role`.
- The frontend uses that value to gate admin UI and maintenance routes.

### Admin car maintenance

These endpoints write directly to the `cars` table:

- `POST /admin/cars`
- `GET /admin/car-form-options`
- `POST /admin/cars/{car_id}`
- `DELETE /admin/cars/{car_id}`
- `POST /admin/cars/{car_id}/duplicate`

#### `POST /admin/cars`

Creates a new car entry immediately.

Body model:

- `CarMutationRequest`

Important fields:

- `brand_id`, `make_id`, `product_line_id`
  Preferred when selecting existing normalized rows.
- `brand`, `make`, `product_line`
  Also accepted so the backend can resolve or create missing lookup rows.
- `release_date_approximate`
  Current editor date field.
- `images`
  Ordered JSON array. The first image is treated as the primary image by the app.

#### `GET /admin/car-form-options`

Returns normalized lookup data used by the admin editor.

Response shape:

- `brands: [{ id, name }]`
- `makes: [{ id, name }]`
- `productLines: [{ id, name, brand_id }]`

Notes:

- `productLines` includes `brand_id` so the frontend can filter product lines by selected brand.
- There is currently no normalized `models` table, so `model` remains text.

#### `POST /admin/cars/{car_id}`

Updates an existing car directly.

Body model:

- `CarMutationRequest`

Notes:

- JSON fields such as `images` and `additional_info` are written as JSONB.
- Admin submit can create missing `brands`, `makes`, and `product_lines` before saving the car.

#### `DELETE /admin/cars/{car_id}`

Deletes a car entry directly.

#### `POST /admin/cars/{car_id}/duplicate`

Duplicates an existing car, then applies payload overrides.

Body model:

- `CarDuplicateRequest`

## Customer change requests

These endpoints back the customer suggestion flow:

- `POST /car-change-requests`
- `GET /car-change-requests`
- `GET /car-change-requests/summary`

#### `POST /car-change-requests`

Creates a pending change request for admin review.

Body model:

- `CarChangeRequestCreate`

Fields:

- `car_id`
  Present when suggesting edits to an existing car.
- `request_type`
  Workflow label such as `create` or `suggest`.
- `payload`
  Proposed field values from the customer form.
- `uploaded_images`
  Currently metadata-only until real customer upload storage is added.

Behavior:

- Enforces the weekly submission limit in the backend.
- Does not update `cars` directly.

#### `GET /car-change-requests`

Returns the authenticated user’s own change requests.

Query params:

- `status`
- `limit`
- `offset`

#### `GET /car-change-requests/summary`

Returns a lightweight quota summary for the authenticated user.

Response fields:

- `weeklyLimit`
- `usedCount`
- `remainingCount`
- `windowDays`
- `resetAt`

Notes:

- This summary is computed from `car_change_requests`.
- No separate quota column is stored on `users`.

## Admin review workflow

These endpoints support the next frontend slice for reviewing customer suggestions:

- `GET /admin/car-change-requests`
- `POST /admin/car-change-requests/{request_id}/review`

#### `GET /admin/car-change-requests`

Lists customer change requests for admins.

Query params:

- `status`
- `limit`
- `offset`

#### `POST /admin/car-change-requests/{request_id}/review`

Approves or rejects a change request.

Body model:

- `CarChangeRequestReview`

Fields:

- `status`
- `reviewNotes`

## Pydantic Models

Defined in [car_models.py](/Users/zhuodiao/workplace/LaicaiApi/backend/app/models/car_models.py):

- `CarMutationRequest`
- `CarDuplicateRequest`
- `CarChangeRequestCreate`
- `CarChangeRequestReview`

Defined in [user_models.py](/Users/zhuodiao/workplace/LaicaiApi/backend/app/models/user_models.py):

- `PromoteUserRequest`

## Related Backend Files

- [cars.py](/Users/zhuodiao/workplace/LaicaiApi/backend/app/routes/cars.py)
- [users.py](/Users/zhuodiao/workplace/LaicaiApi/backend/app/routes/users.py)
- [car_service.py](/Users/zhuodiao/workplace/LaicaiApi/backend/app/services/car_service.py)
- [car_repository.py](/Users/zhuodiao/workplace/LaicaiApi/backend/app/repositories/car_repository.py)
- [user_service.py](/Users/zhuodiao/workplace/LaicaiApi/backend/app/services/user_service.py)

## Frontend Usage Summary

The main frontend consumers are:

- admin car editor
- customer car editor
- admin maintenance list

Frontend wrappers remain documented inline in:

- [carApi.ts](/Users/zhuodiao/workplace/malo/src/api/carApi.ts)
- [userApi.ts](/Users/zhuodiao/workplace/malo/src/api/userApi.ts)
