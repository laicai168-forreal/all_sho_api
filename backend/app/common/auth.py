# app/common/auth.py

from fastapi import Request, HTTPException

def get_current_user_sub(request: Request) -> str:
    try:
        claims = request.scope["aws.event"]["requestContext"]["authorizer"]["jwt"][
            "claims"
        ]
        return claims["sub"]
    except Exception:
        if "aws.event" not in request.scope:
            return "local-user"
        raise HTTPException(status_code=401, detail="Unauthorized")


def get_claims(request: Request):
    try:
        return request.scope["aws.event"]["requestContext"]["authorizer"]["jwt"][
            "claims"
        ]
    except Exception:
        if "aws.event" not in request.scope:
            return {"sub": "local-user", "email": "test@test.com"}
        raise HTTPException(status_code=401, detail="Unauthorized")
