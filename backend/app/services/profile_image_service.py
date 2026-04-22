import os
import uuid
from typing import Optional
from urllib.parse import urlparse

import boto3
import hashlib

s3_client = boto3.client("s3")

PROFILE_IMAGE_BUCKET = os.environ["PROFILE_IMAGE_BUCKET"]


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


def create_profile_image_upload(sub: str, file_name: str, content_type: str):
    object_key = f"profile-images/{sub}/{uuid.uuid4()}-{_sanitize_file_name(file_name)}"
    result = _create_presigned_image_upload(object_key, content_type)
    result["fileUrl"] = build_profile_image_url(object_key)
    return result


def create_car_change_request_image_upload(sub: str, file_name: str, content_type: str):
    object_key = f"car-change-requests/{sub}/{uuid.uuid4()}-{_sanitize_file_name(file_name)}"
    return _create_presigned_image_upload(object_key, content_type)


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
        Bucket=PROFILE_IMAGE_BUCKET,
        Key=canonical_key,
        Body=body,
        ContentType=content_type,
    )

    return _build_bucket_file_url(canonical_key)


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

    _delete_object_if_exists(object_key)


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
