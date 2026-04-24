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


@router.get("/role/{address}")
async def get_role(address: str):
    addr = address.lower()
    kol = await database.get_kol_by_address(addr)
    if kol and kol.get("status") == "active":
        # Return both "creator" (new) and "kol" (legacy) — frontend can check either
        return {"role": "creator", "handle": kol.get("handle", "")}
    partner = await database.get_partner_by_address(addr)
    if partner and partner.get("status") == "active":
        return {"role": "wallet", "name": partner.get("name", "")}
    return {"role": "user"}


# Tier thresholds (depositing referrals)
_TIER1_THRESHOLD = 3   # Active Referrer
_TIER2_THRESHOLD = 10  # Top Referrer (unlocks Creator invite)
_POINTS_PER_DEPOSITING_REFERRAL = 120


@router.get("/referrals/{address}")
async def get_referrals(address: str):
    """Return referral stats + tier for an investor's own referral link.

    Counts UNIQUE user_addresses that deposited where referrer matches this address.
    Also lazily provisions (or returns) the user's random `ref_code`.
    """
    addr = address.lower()

    # Provision ref_code if this user has a row but no code yet. If the user
    # has never logged in, seed a minimal row so they still get a shareable code.
    ref_code = await database.ensure_user_ref_code(addr)
    if not ref_code:
        user = await database.get_user_by_address(addr)
        if not user:
            await database.get_or_create_user(addr)
        ref_code = await database.ensure_user_ref_code(addr)

    depositing = await database.count_unique_depositing_referrals(addr)
    # For clicks/signups we don't track yet — return 0. Frontend can show as 0.
    clicks = 0
    signups = 0

    if depositing >= _TIER2_THRESHOLD:
        tier = 2
        tier_label = "Top Referrer"
    elif depositing >= _TIER1_THRESHOLD:
        tier = 1
        tier_label = "Active Referrer"
    else:
        tier = 0
        tier_label = None

    points = depositing * _POINTS_PER_DEPOSITING_REFERRAL

    return {
        "address": addr,
        "ref_code": ref_code,
        "clicks": clicks,
        "signups": signups,
        "depositing": depositing,
        "points": points,
        "tier": tier,
        "tier_label": tier_label,
        "tier1_threshold": _TIER1_THRESHOLD,
        "tier2_threshold": _TIER2_THRESHOLD,
        "creator_unlocked": depositing >= _TIER2_THRESHOLD,
    }


@router.get("/resolve-ref/{code}")
async def resolve_ref(code: str):
    """Resolve a random user referral code to its owner address.

    Used by the deposit modal to attribute a deposit to the referrer when a
    visitor lands with `?ref=<code>` that is not a registered Creator handle.
    """
    code_norm = code.strip().upper()
    if not code_norm:
        raise HTTPException(status_code=400, detail="Empty code")
    user = await database.get_user_by_ref_code(code_norm)
    if not user:
        raise HTTPException(status_code=404, detail="Referral code not found")
    return {"address": user["address"], "ref_code": user.get("ref_code", code_norm)}


@router.post("/logout")
async def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        session = await database.get_user_session(hash_key(token))
        if session:
            await database.delete_user_sessions(session["address"])
    return {"ok": True}
