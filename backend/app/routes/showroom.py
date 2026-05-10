from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.common.auth import get_current_user_sub
from app.models.showroom_models import (
    CreateShowroomCommentRequest,
    CreateShowroomImageUploadRequest,
    CreateShowroomPostRequest,
    CreateShowroomReportRequest,
    ModerateShowroomCommentRequest,
    ModerateShowroomPostRequest,
    ResolveShowroomReportRequest,
    ConfirmShowroomSaleBuyerRequest,
    UpdateShowroomPostRequest,
    UpdateShowroomSellingStatusRequest,
)
from app.services import showroom_service

router = APIRouter()
public_router = APIRouter()


@public_router.get("/showroom")
def list_showroom_posts(
    limit: int = 20,
    offset: int = 0,
    userId: UUID | None = None,
    postType: str | None = None,
    feedMode: str | None = None,
    tagKey: str | None = None,
    carId: UUID | None = None,
    keyword: str | None = None,
    sellerQuery: str | None = None,
    minPrice: float | None = None,
    maxPrice: float | None = None,
    shippingSupported: bool | None = None,
    sellingStatus: str | None = None,
):
    return showroom_service.list_showroom_posts(
        limit=limit,
        offset=offset,
        user_id=str(userId) if userId else None,
        post_type=postType,
        feed_mode=feedMode,
        tag_key=tagKey,
        car_id=str(carId) if carId else None,
        keyword=keyword,
        seller_query=sellerQuery,
        min_price=minPrice,
        max_price=maxPrice,
        shipping_supported=shippingSupported,
        selling_status=sellingStatus,
    )


@public_router.get("/showroom/{post_id}")
def get_showroom_post(post_id: UUID):
    post = showroom_service.get_showroom_post(str(post_id))
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@public_router.get("/showroom/{post_id}/comments")
def list_showroom_comments(
    post_id: UUID,
    limit: int = 30,
    offset: int = 0,
):
    try:
        return showroom_service.list_showroom_comments(str(post_id), limit=limit, offset=offset)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@public_router.get("/showroom/trending-tags")
def list_trending_showroom_tags(limit: int = 12):
    return showroom_service.list_trending_showroom_tags(limit=limit)


@public_router.get("/profiles/{user_id}/showroom")
def list_user_showroom_posts(
    user_id: UUID,
    limit: int = 20,
    offset: int = 0,
    postType: str | None = None,
):
    return showroom_service.list_showroom_posts(
        limit=limit,
        offset=offset,
        user_id=str(user_id),
        post_type=postType,
    )


@router.post("/showroom/images/upload")
def create_showroom_image_upload(request: Request, body: CreateShowroomImageUploadRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.create_showroom_image_upload(sub, body.fileName, body.contentType)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/showroom")
def create_showroom_post(request: Request, body: CreateShowroomPostRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.create_showroom_post(sub, body.dict())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.put("/showroom/{post_id}")
def update_showroom_post(request: Request, post_id: UUID, body: UpdateShowroomPostRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.update_showroom_post(sub, str(post_id), body.dict())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/showroom/{post_id}/selling-status")
def update_showroom_selling_status(request: Request, post_id: UUID, body: UpdateShowroomSellingStatusRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.update_showroom_selling_status(sub, str(post_id), body.sellingStatus)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/showroom/{post_id}/sale-candidates")
def list_showroom_sale_candidates(request: Request, post_id: UUID):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.list_showroom_sale_candidates(sub, str(post_id))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/showroom/{post_id}/sale-transaction")
def confirm_showroom_sale_buyer(request: Request, post_id: UUID, body: ConfirmShowroomSaleBuyerRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.confirm_showroom_sale_buyer(sub, str(post_id), body.buyerUserId)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/showroom/feed/{feed_mode}")
def list_personalized_showroom_feed(
    request: Request,
    feed_mode: str,
    limit: int = 20,
    offset: int = 0,
    postType: str | None = None,
    tagKey: str | None = None,
    carId: UUID | None = None,
    keyword: str | None = None,
    sellerQuery: str | None = None,
    minPrice: float | None = None,
    maxPrice: float | None = None,
    shippingSupported: bool | None = None,
    sellingStatus: str | None = None,
):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.list_showroom_feed(
            actor_sub=sub,
            feed_mode=feed_mode,
            limit=limit,
            offset=offset,
            post_type=postType,
            tag_key=tagKey,
            car_id=str(carId) if carId else None,
            keyword=keyword,
            seller_query=sellerQuery,
            min_price=minPrice,
            max_price=maxPrice,
            shipping_supported=shippingSupported,
            selling_status=sellingStatus,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/showroom/{post_id}/viewer")
def get_showroom_post_viewer_state(request: Request, post_id: UUID):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.get_showroom_post_like_status(sub, str(post_id))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/showroom/{post_id}/comments")
def create_showroom_comment(request: Request, post_id: UUID, body: CreateShowroomCommentRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.create_showroom_comment(sub, str(post_id), body.content)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/showroom/comments/{comment_id}")
def delete_showroom_comment(request: Request, comment_id: UUID):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.delete_showroom_comment(sub, str(comment_id))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/showroom/{post_id}/likes")
def like_showroom_post(request: Request, post_id: UUID):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.like_showroom_post(sub, str(post_id))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.delete("/showroom/{post_id}/likes")
def unlike_showroom_post(request: Request, post_id: UUID):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.unlike_showroom_post(sub, str(post_id))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.delete("/showroom/{post_id}")
def delete_showroom_post(request: Request, post_id: UUID):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.delete_showroom_post(sub, str(post_id))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/showroom/{post_id}/reports")
def create_showroom_post_report(request: Request, post_id: UUID, body: CreateShowroomReportRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.create_showroom_post_report(sub, str(post_id), body.reason, body.details)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/showroom/comments/{comment_id}/reports")
def create_showroom_comment_report(request: Request, comment_id: UUID, body: CreateShowroomReportRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.create_showroom_comment_report(sub, str(comment_id), body.reason, body.details)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/admin/showroom/reports")
def list_admin_showroom_reports(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.list_admin_showroom_reports(sub, limit=limit, offset=offset, status=status)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/admin/showroom/posts/{post_id}/moderate")
def moderate_showroom_post(request: Request, post_id: UUID, body: ModerateShowroomPostRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.moderate_showroom_post(sub, str(post_id), body.status)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/admin/showroom/comments/{comment_id}/moderate")
def moderate_showroom_comment(request: Request, comment_id: UUID, body: ModerateShowroomCommentRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.moderate_showroom_comment(sub, str(comment_id), body.status)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/admin/showroom/reports/{report_id}/resolve")
def resolve_showroom_report(request: Request, report_id: UUID, body: ResolveShowroomReportRequest):
    sub = get_current_user_sub(request)
    try:
        return showroom_service.resolve_showroom_report(sub, str(report_id), body.status, body.reviewNotes)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
