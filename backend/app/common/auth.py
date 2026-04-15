# app/common/auth.py

from fastapi import Request, HTTPException


def get_claims(request: Request):
    # Local dev fallback
    if "aws.event" not in request.scope:
        return {"sub": "local-user", "email": "test@test.com"}

    return request.scope["aws.event"]["requestContext"]["authorizer"]["jwt"]["claims"]

def get_current_user_sub(request: Request) -> str:
    try:
        claims = request.scope["aws.event"]["requestContext"]["authorizer"]["jwt"][
            "claims"
        ]
        return claims["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")


def get_claims(request: Request):
    try:
        return request.scope["aws.event"]["requestContext"]["authorizer"]["jwt"][
            "claims"
        ]
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")
