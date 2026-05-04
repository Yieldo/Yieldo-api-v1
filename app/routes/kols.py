import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Depends, Request
from app.models import (
    KolNonceRequest, KolNonceResponse,
    KolRegisterRequest, KolRegisterResponse,
    KolLoginRequest, KolLoginResponse,
    KolProfile, KolPublicProfile,
    KolSettingsUpdate, KolVaultsUpdate,
    KolDashboardResponse,
    CreatorInviteVerifyRequest, CreatorApplicationRequest,
)
from app.core.auth import (
    generate_nonce, generate_session_token, hash_key,
    verify_signature, build_kol_register_message, build_kol_login_message,
)
from app.services import database

router = APIRouter(tags=["creators"])

SESSION_DURATION_HOURS = 24
HANDLE_RE = re.compile(r"^[a-z0-9_-]{3,32}$")


# ========== Auth Dependencies ==========

async def get_current_kol(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = auth[7:]
    session = await database.get_kol_session(hash_key(token))
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    kol = await database.get_kol_by_address(session["address"])
    if not kol or kol["status"] != "active":
        raise HTTPException(status_code=403, detail="Creator account suspended")
    return kol


# ========== Public Endpoints ==========

@router.get("/public/{handle}", response_model=KolPublicProfile)
async def get_public_profile(handle: str):
    kol = await database.get_kol_by_handle(handle)
    if not kol:
        raise HTTPException(status_code=404, detail="Creator not found")
    return KolPublicProfile(
        handle=kol["handle"],
        name=kol["name"],
        bio=kol.get("bio", ""),
        twitter=kol.get("twitter", ""),
        enrolled_vaults=kol.get("enrolled_vaults", []),
        created_at=kol["created_at"].isoformat() if kol.get("created_at") else "",
        founding_creator=kol.get("founding_creator", False),
    )


@router.get("/resolve/{handle}")
async def resolve_handle(handle: str):
    """Resolve a Creator handle to their referrer address (fee_collector_address)."""
    kol = await database.get_kol_by_handle(handle)
    if not kol:
        raise HTTPException(status_code=404, detail="Creator not found")
    return {
        "handle": kol["handle"],
        "name": kol["name"],
        "address": kol.get("fee_collector_address", kol["address"]),
        "fee_enabled": kol.get("fee_enabled", True),
    }


# ========== Auth Endpoints ==========

@router.post("/nonce", response_model=KolNonceResponse)
async def get_nonce(req: KolNonceRequest):
    # Mutual exclusion: wallet partners cannot register as Creators
    existing_partner = await database.get_partner_by_address(req.address)
    if existing_partner:
        raise HTTPException(
            status_code=409,
            detail="This address is already registered as a wallet partner. A wallet cannot also be a Creator.",
        )
    nonce = generate_nonce()
    await database.save_kol_nonce(req.address, nonce)
    existing = await database.get_kol_by_address(req.address)
    if existing:
        message = build_kol_login_message(req.address, nonce)
    else:
        message = build_kol_register_message(req.address, nonce)
    return KolNonceResponse(nonce=nonce, message=message)


@router.post("/register", response_model=KolRegisterResponse)
async def register(req: KolRegisterRequest):
    # Mutual exclusion: cannot be both a wallet partner and Creator
    existing_partner = await database.get_partner_by_address(req.address)
    if existing_partner:
        raise HTTPException(status_code=409, detail="This address is already registered as a wallet partner.")

    existing_kol = await database.get_kol_by_address(req.address)
    if existing_kol:
        raise HTTPException(status_code=409, detail="Address already registered as a Creator")

    # Gate: require an approved application OR a valid invite code OR tier-2
    # organic unlock (10+ depositing referrals). Application path is the
    # primary flow; invite code is kept for legacy hand-out scenarios.
    invite_code = (req.invite_code or "").strip().upper()
    invite_doc = None

    app_doc = await database.get_application(req.address, "creator")
    has_approved_application = app_doc and app_doc.get("status") == "approved"

    if has_approved_application:
        pass  # approved — allow through
    elif invite_code:
        invite_doc = await database.verify_invite_code(invite_code)
        if not invite_doc:
            raise HTTPException(status_code=400, detail="Invalid or already-used invite code")
    elif app_doc and app_doc.get("status") == "pending":
        raise HTTPException(
            status_code=403,
            detail="Your application is under review. We'll respond within 48 hours.",
        )
    elif app_doc and app_doc.get("status") == "rejected":
        raise HTTPException(status_code=403, detail="Application was rejected.")
    else:
        depositing = await database.count_unique_depositing_referrals(req.address)
        if depositing < 10:
            raise HTTPException(
                status_code=403,
                detail="Creator access is invite-only. Submit an application at /v1/applications/creator, enter an invite code, or refer 10+ depositing users to unlock.",
            )

    # Validate handle
    handle = req.handle.lower().strip()
    if not HANDLE_RE.match(handle):
        raise HTTPException(status_code=400, detail="Handle must be 3-32 characters: letters, numbers, _ or -")
    handle_taken = await database.get_kol_by_handle(handle)
    if handle_taken:
        raise HTTPException(status_code=409, detail="This handle is already taken")

    nonce = await database.get_and_delete_kol_nonce(req.address)
    if not nonce:
        raise HTTPException(status_code=400, detail="No pending nonce. Request /nonce first.")

    message = build_kol_register_message(req.address, nonce)
    if not verify_signature(req.address, message, req.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    kol = await database.create_kol(
        address=req.address,
        handle=handle,
        name=req.name,
        bio=req.bio,
        twitter=req.twitter,
    )

    # Mark as Founding Creator (all early signups get the badge).
    await database.update_kol(req.address, {"founding_creator": True})

    # Consume the invite code if one was used
    if invite_code and invite_doc:
        await database.consume_invite_code(invite_code, req.address)

    return KolRegisterResponse(
        address=kol["address"],
        handle=kol["handle"],
        name=kol["name"],
        created_at=kol["created_at"].isoformat(),
    )


# ========== Invite code + application endpoints ==========

@router.post("/invite/verify")
async def verify_invite(req: CreatorInviteVerifyRequest):
    """Check if an invite code is valid (unused). Does not consume it."""
    code = (req.code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Code required")
    doc = await database.verify_invite_code(code)
    if not doc:
        raise HTTPException(status_code=404, detail="Invalid or already-used code")
    return {"valid": True, "code": code}


@router.post("/apply")
async def apply_for_creator(req: CreatorApplicationRequest):
    """Submit a manual Creator application for review."""
    if not req.twitter:
        raise HTTPException(status_code=400, detail="Twitter handle required")
    # Check if address already has an application
    existing = await database.get_creator_application(req.address)
    if existing:
        return {"ok": True, "status": existing.get("status", "pending"), "message": "Application already submitted"}
    app_id = await database.save_creator_application(req.address, req.twitter, req.audience, req.description)
    return {"ok": True, "application_id": app_id, "status": "pending"}


@router.post("/login", response_model=KolLoginResponse)
async def login(req: KolLoginRequest):
    kol = await database.get_kol_by_address(req.address)
    if not kol:
        raise HTTPException(status_code=404, detail="KOL not found. Register first.")

    nonce = await database.get_and_delete_kol_nonce(req.address)
    if not nonce:
        raise HTTPException(status_code=400, detail="No pending nonce. Request /nonce first.")

    message = build_kol_login_message(req.address, nonce)
    if not verify_signature(req.address, message, req.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    token = generate_session_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)
    await database.save_kol_session(hash_key(token), req.address, expires)

    return KolLoginResponse(
        session_token=token,
        expires_at=expires.isoformat(),
        kol={
            "address": kol["address"],
            "handle": kol["handle"],
            "name": kol["name"],
            "status": kol["status"],
        },
    )


@router.post("/logout")
async def logout(kol: dict = Depends(get_current_kol)):
    await database.delete_kol_sessions(kol["address"])
    return {"success": True}


# ========== Authenticated Portal Endpoints ==========

@router.get("/me", response_model=KolProfile)
async def get_profile(kol: dict = Depends(get_current_kol)):
    return KolProfile(
        address=kol["address"],
        handle=kol["handle"],
        name=kol["name"],
        bio=kol.get("bio", ""),
        twitter=kol.get("twitter", ""),
        fee_enabled=kol.get("fee_enabled", True),
        fee_collector_address=kol.get("fee_collector_address", kol["address"]),
        enrolled_vaults=kol.get("enrolled_vaults", []),
        created_at=kol["created_at"].isoformat() if kol.get("created_at") else "",
        status=kol.get("status", "active"),
    )


@router.put("/settings")
async def update_settings(
    req: KolSettingsUpdate,
    kol: dict = Depends(get_current_kol),
):
    fields = {}
    if req.name is not None:
        fields["name"] = req.name
    if req.bio is not None:
        fields["bio"] = req.bio
    if req.twitter is not None:
        fields["twitter"] = req.twitter
    if req.fee_enabled is not None:
        fields["fee_enabled"] = req.fee_enabled
    if req.fee_collector_address is not None:
        fields["fee_collector_address"] = req.fee_collector_address.lower()
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    await database.update_kol(kol["address"], fields)
    return {"success": True}


@router.put("/vaults")
async def update_vaults(
    req: KolVaultsUpdate,
    kol: dict = Depends(get_current_kol),
):
    await database.update_kol(kol["address"], {"enrolled_vaults": req.enrolled_vaults})
    return {"success": True}


@router.get("/dashboard", response_model=KolDashboardResponse)
async def get_dashboard(kol: dict = Depends(get_current_kol)):
    data = await database.get_kol_dashboard(kol["address"])
    return KolDashboardResponse(**data)


@router.get("/referrals")
async def get_referrals(
    limit: int = 50,
    skip: int = 0,
    kol: dict = Depends(get_current_kol),
):
    refs = await database.get_kol_referrals(kol["address"], limit=limit, skip=skip)
    for r in refs:
        if "created_at" in r and isinstance(r["created_at"], datetime):
            r["created_at"] = r["created_at"].isoformat()
    return refs
