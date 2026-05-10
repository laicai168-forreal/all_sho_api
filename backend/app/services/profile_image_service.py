import os
import uuid
from typing import Optional
from urllib.parse import urlparse

import boto3
import hashlib
import requests

s3_client = boto3.client("s3")

PROFILE_IMAGE_BUCKET = os.environ["PROFILE_IMAGE_BUCKET"]
SHOWROOM_IMAGE_BUCKET = os.environ.get("SHOWROOM_IMAGE_BUCKET", PROFILE_IMAGE_BUCKET)
CAR_IMAGE_BUCKET = os.environ.get("CAR_IMAGE_BUCKET", PROFILE_IMAGE_BUCKET)


def _sanitize_file_name(file_name: str) -> str:
    safe = "".join(char for char in file_name if char.isalnum() or char in (".", "-", "_"))
    return safe or "profile-image"


def _get_bucket_region() -> str:
    return os.environ.get("AWS_REGION", "us-east-1")


def build_profile_image_url(object_key: str) -> str:
    region = _get_bucket_region()
    return f"https://{PROFILE_IMAGE_BUCKET}.s3.{region}.amazonaws.com/{object_key}"


def _build_bucket_file_url(object_key: str) -> str:
    region = _get_bucket_region()
    return f"https://{PROFILE_IMAGE_BUCKET}.s3.{region}.amazonaws.com/{object_key}"


def _build_showroom_file_url(object_key: str) -> str:
    region = _get_bucket_region()
    return f"https://{SHOWROOM_IMAGE_BUCKET}.s3.{region}.amazonaws.com/{object_key}"


def _build_car_image_file_url(object_key: str) -> str:
    region = _get_bucket_region()
    return f"https://{CAR_IMAGE_BUCKET}.s3.{region}.amazonaws.com/{object_key}"


def _create_presigned_image_upload(object_key: str, content_type: str):
    upload_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": PROFILE_IMAGE_BUCKET,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=900,
        HttpMethod="PUT",
    )

    return {
        "uploadUrl": upload_url,
        "objectKey": object_key,
        "fileUrl": _build_bucket_file_url(object_key),
    }


def _create_presigned_showroom_image_upload(object_key: str, content_type: str):
    upload_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": SHOWROOM_IMAGE_BUCKET,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=900,
        HttpMethod="PUT",
    )

    return {
        "uploadUrl": upload_url,
        "objectKey": object_key,
        "fileUrl": _build_showroom_file_url(object_key),
    }


def create_profile_image_upload(sub: str, file_name: str, content_type: str):
    object_key = f"profile-images/{sub}/{uuid.uuid4()}-{_sanitize_file_name(file_name)}"
    result = _create_presigned_image_upload(object_key, content_type)
    result["fileUrl"] = build_profile_image_url(object_key)
    return result


def create_car_change_request_image_upload(sub: str, file_name: str, content_type: str):
    object_key = f"car-change-requests/{sub}/{uuid.uuid4()}-{_sanitize_file_name(file_name)}"
    return _create_presigned_image_upload(object_key, content_type)


def create_showroom_image_upload(sub: str, file_name: str, content_type: str):
    object_key = f"showroom-images-temp/{sub}/{uuid.uuid4()}-{_sanitize_file_name(file_name)}"
    return _create_presigned_showroom_image_upload(object_key, content_type)


def confirm_showroom_images(sub: str, post_id: str, images: list[dict]):
    confirmed_images = []
    expected_prefix = f"showroom-images-temp/{sub}/"

    for index, image in enumerate(images):
        pending_key = image.get("objectKey") or image.get("object_key")
        file_name = image.get("fileName") or image.get("file_name") or f"image-{index + 1}.jpg"
        if not pending_key or not pending_key.startswith(expected_prefix):
            raise ValueError("Invalid showroom image key")

        head = s3_client.head_object(Bucket=SHOWROOM_IMAGE_BUCKET, Key=pending_key)
        content_type = head.get("ContentType", "application/octet-stream")
        final_key = f"showroom-images/{post_id}/{uuid.uuid4()}-{_sanitize_file_name(file_name)}"

        s3_client.copy_object(
            Bucket=SHOWROOM_IMAGE_BUCKET,
            CopySource={"Bucket": SHOWROOM_IMAGE_BUCKET, "Key": pending_key},
            Key=final_key,
            ContentType=content_type,
            MetadataDirective="REPLACE",
        )
        s3_client.delete_object(Bucket=SHOWROOM_IMAGE_BUCKET, Key=pending_key)

        confirmed_images.append({
            "objectKey": final_key,
            "fileUrl": _build_showroom_file_url(final_key),
            "sortOrder": image.get("sortOrder", index),
        })

    return confirmed_images


def resolve_showroom_images(sub: str, post_id: str, images: list[dict]):
    resolved_images = []
    temp_prefix = f"showroom-images-temp/{sub}/"
    final_prefix = f"showroom-images/{post_id}/"

    for index, image in enumerate(images):
        object_key = image.get("objectKey") or image.get("object_key")
        file_name = image.get("fileName") or image.get("file_name") or f"image-{index + 1}.jpg"
        sort_order = image.get("sortOrder", index)

        if not object_key:
            raise ValueError("Invalid showroom image key")

        if object_key.startswith(final_prefix):
            resolved_images.append({
                "objectKey": object_key,
                "fileUrl": _build_showroom_file_url(object_key),
                "sortOrder": sort_order,
            })
            continue

        if object_key.startswith(temp_prefix):
            head = s3_client.head_object(Bucket=SHOWROOM_IMAGE_BUCKET, Key=object_key)
            content_type = head.get("ContentType", "application/octet-stream")
            final_key = f"showroom-images/{post_id}/{uuid.uuid4()}-{_sanitize_file_name(file_name)}"

            s3_client.copy_object(
                Bucket=SHOWROOM_IMAGE_BUCKET,
                CopySource={"Bucket": SHOWROOM_IMAGE_BUCKET, "Key": object_key},
                Key=final_key,
                ContentType=content_type,
                MetadataDirective="REPLACE",
            )
            s3_client.delete_object(Bucket=SHOWROOM_IMAGE_BUCKET, Key=object_key)

            resolved_images.append({
                "objectKey": final_key,
                "fileUrl": _build_showroom_file_url(final_key),
                "sortOrder": sort_order,
            })
            continue

        raise ValueError("Invalid showroom image key")

    return resolved_images


def promote_car_change_request_image(file_url: str) -> str:
    object_key = _extract_key_from_url(file_url)
    if not object_key or not object_key.startswith("car-change-requests/"):
        raise ValueError("Invalid car change request image URL")

    response = s3_client.get_object(Bucket=PROFILE_IMAGE_BUCKET, Key=object_key)
    content_type = response.get("ContentType", "application/octet-stream")
    body = response["Body"].read()

    _, ext = os.path.splitext(object_key)
    canonical_key = f"images/{hashlib.sha1(body).hexdigest()}{ext or '.jpg'}"

    s3_client.put_object(
        Bucket=CAR_IMAGE_BUCKET,
        Key=canonical_key,
        Body=body,
        ContentType=content_type,
    )

    return _build_car_image_file_url(canonical_key)


def create_hot_wheels_review_image(
    staging_item_id: str,
    image_url: str,
    *,
    file_stem: str,
    content_type: Optional[str] = None,
) -> dict:
    response = requests.get(image_url, timeout=20)
    response.raise_for_status()

    resolved_content_type = content_type or response.headers.get("Content-Type", "application/octet-stream")
    extension = _infer_extension_from_url_or_content_type(image_url, resolved_content_type)
    object_key = (
        f"hot-wheels-image-review/{staging_item_id}/"
        f"{uuid.uuid4()}-{_sanitize_file_name(file_stem)}{extension}"
    )

    s3_client.put_object(
        Bucket=PROFILE_IMAGE_BUCKET,
        Key=object_key,
        Body=response.content,
        ContentType=resolved_content_type,
    )

    return {
        "objectKey": object_key,
        "fileUrl": _build_bucket_file_url(object_key),
        "contentType": resolved_content_type,
        "size": len(response.content),
    }


def promote_hot_wheels_review_image(file_url: str) -> str:
    object_key = _extract_key_from_url(file_url)
    if not object_key or not object_key.startswith("hot-wheels-image-review/"):
        raise ValueError("Invalid Hot Wheels review image URL")

    response = s3_client.get_object(Bucket=PROFILE_IMAGE_BUCKET, Key=object_key)
    content_type = response.get("ContentType", "application/octet-stream")
    body = response["Body"].read()

    _, ext = os.path.splitext(object_key)
    canonical_key = f"images/{hashlib.sha1(body).hexdigest()}{ext or '.jpg'}"

    s3_client.put_object(
        Bucket=CAR_IMAGE_BUCKET,
        Key=canonical_key,
        Body=body,
        ContentType=content_type,
    )

    return _build_car_image_file_url(canonical_key)


def create_admin_car_image_from_url(image_url: str) -> dict:
    response = requests.get(image_url, timeout=20)
    response.raise_for_status()

    resolved_content_type = response.headers.get("Content-Type", "application/octet-stream")
    extension = _infer_extension_from_url_or_content_type(image_url, resolved_content_type)
    canonical_key = f"images/{hashlib.sha1(response.content).hexdigest()}{extension or '.jpg'}"

    s3_client.put_object(
        Bucket=CAR_IMAGE_BUCKET,
        Key=canonical_key,
        Body=response.content,
        ContentType=resolved_content_type,
    )

    canonical_url = _build_car_image_file_url(canonical_key)
    return {
        "s3_url": canonical_url,
        "original_url": image_url,
    }


def _extract_key_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None

    parsed = urlparse(url)
    return parsed.path.lstrip("/") or None


def extract_object_key_from_url(url: Optional[str]) -> Optional[str]:
    return _extract_key_from_url(url)


def _delete_object_if_exists(object_key: Optional[str]):
    if not object_key:
        return

    try:
        s3_client.delete_object(Bucket=PROFILE_IMAGE_BUCKET, Key=object_key)
    except Exception:
        return


def delete_canonical_car_image(file_url: Optional[str]):
    object_key = _extract_key_from_url(file_url)
    if not object_key or not object_key.startswith("images/"):
        return
    try:
        s3_client.delete_object(Bucket=CAR_IMAGE_BUCKET, Key=object_key)
    except Exception:
        return


def delete_hot_wheels_review_image(file_url: Optional[str]):
    object_key = _extract_key_from_url(file_url)
    if not object_key or not object_key.startswith("hot-wheels-image-review/"):
        return

    _delete_object_if_exists(object_key)


def _infer_extension_from_url_or_content_type(url: str, content_type: str) -> str:
    parsed = urlparse(url)
    _, ext = os.path.splitext(parsed.path or "")
    if ext:
        return ext[:10]

    lowered = (content_type or "").lower()
    if "png" in lowered:
        return ".png"
    if "webp" in lowered:
        return ".webp"
    if "gif" in lowered:
        return ".gif"
    if "jpeg" in lowered or "jpg" in lowered:
        return ".jpg"
    return ".jpg"


def confirm_profile_image(sub: str, pending_key: str, existing_url: Optional[str] = None) -> str:
    expected_prefix = f"profile-images/{sub}/"
    if not pending_key.startswith(expected_prefix):
        raise ValueError("Invalid profile image key")

    s3_client.head_object(Bucket=PROFILE_IMAGE_BUCKET, Key=pending_key)

    existing_key = _extract_key_from_url(existing_url)
    if existing_key and existing_key != pending_key:
        _delete_object_if_exists(existing_key)

    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=PROFILE_IMAGE_BUCKET, Prefix=expected_prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if key != pending_key:
                _delete_object_if_exists(key)

    return build_profile_image_url(pending_key)
