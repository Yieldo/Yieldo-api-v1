from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request
from app.models import (
    UserNonceRequest, UserNonceResponse,
    UserLoginRequest, UserLoginResponse,
)
from app.core.auth import (
    generate_nonce, generate_session_token, hash_key,
    verify_signature, build_user_login_message,
)
from app.services import database

router = APIRouter(prefix="/v1/users", tags=["users"])

SESSION_DURATION_HOURS = 2


async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")
    token = auth[7:]
    session = await database.get_user_session(hash_key(token))
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = await database.get_user_by_address(session["address"])
    if not user or user.get("status") != "active":
        raise HTTPException(status_code=403, detail="Account inactive")
    return user


@router.post("/nonce", response_model=UserNonceResponse)
async def get_nonce(req: UserNonceRequest):
    if not req.address or len(req.address) != 42:
        raise HTTPException(status_code=400, detail="Invalid address")
    nonce = generate_nonce()
    await database.save_user_nonce(req.address, nonce)
    message = build_user_login_message(req.address, nonce)
    return UserNonceResponse(nonce=nonce, message=message)


@router.post("/login", response_model=UserLoginResponse)
async def login(req: UserLoginRequest):
    if not req.address or len(req.address) != 42:
        raise HTTPException(status_code=400, detail="Invalid address")

    nonce = await database.get_and_delete_user_nonce(req.address)
    if not nonce:
        raise HTTPException(status_code=400, detail="No nonce found — request /nonce first")

    message = build_user_login_message(req.address, nonce)
    if not verify_signature(req.address, message, req.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Auto-register or update last_login
    user = await database.get_or_create_user(req.address)

    token = generate_session_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)
    await database.save_user_session(hash_key(token), req.address, expires)

    user_safe = {
        "address": user["address"],
        "created_at": user.get("created_at", ""),
        "status": user.get("status", "active"),
    }
    if isinstance(user_safe["created_at"], datetime):
        user_safe["created_at"] = user_safe["created_at"].isoformat()

    return UserLoginResponse(
        session_token=token,
        expires_at=expires.isoformat(),
        user=user_safe,
    )


@router.get("/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return {
        "address": user["address"],
        "status": user.get("status", "active"),
        "created_at": user["created_at"].isoformat() if isinstance(user.get("created_at"), datetime) else str(user.get("created_at", "")),
    }


@router.post("/logout")
async def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        session = await database.get_user_session(hash_key(token))
        if session:
            await database.delete_user_sessions(session["address"])
    return {"ok": True}
