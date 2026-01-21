import os
import boto3
from PIL import Image
import io
import base64

s3 = boto3.client("s3")
IMAGE_BUCKET = os.environ["IMAGE_BUCKET"]
OLD_BUCKET = os.environ["OLD_BUCKET"]


def lambda_handler(event, context):
    print("Event:", event)

    # Get query string and path
    qs = event.get("queryStringParameters") or {}

    width_param = qs.get("width")
    width = int(width_param) if width_param else None

    raw_path = event.get("rawPath", "")
    # if raw_path.startswith("/images/"):
    #     key = raw_path[len("/images/") :]
    # else:
    key = raw_path.lstrip("/")

    # Try new bucket first, fallback to old
    buckets = [IMAGE_BUCKET, OLD_BUCKET]

    obj_body = None
    content_type = None
    for bucket in buckets:
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            obj_body = obj["Body"].read()
            content_type = obj["ContentType"]
            break
        except s3.exceptions.NoSuchKey:
            continue
        except Exception as e:
            return {
                "statusCode": 500,
                "body": f"Error fetching {key} from {bucket}: {str(e)}",
            }

    if not obj_body:
        return {"statusCode": 404, "body": f"{key} not found in either bucket."}

    try:
        # Open image with Pillow
        img = Image.open(io.BytesIO(obj_body))

        if not width:
            encoded = base64.b64encode(obj_body).decode("utf-8")
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": content_type,
                    "Cache-Control": "max-age=31536000",
                },
                "body": encoded,
                "isBase64Encoded": True,
            }

        w_percent = width / float(img.size[0])
        h_size = int((float(img.size[1]) * float(w_percent)))
        img = img.resize((width, h_size), Image.Resampling.LANCZOS)

        # Save to buffer
        buffer = io.BytesIO()
        if img.format == "PNG":
            img.save(buffer, format="PNG", compress_level=9)
        else:
            img.save(buffer, format="JPEG", quality=80)

        encoded_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": content_type,
                "Cache-Control": "max-age=31536000",
            },
            "body": encoded_image,
            "isBase64Encoded": True,
        }

    except Exception as e:
        print(e)
        return {"statusCode": 500, "body": f"Error processing image: {str(e)}"}
