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
)
from app.core.auth import (
    generate_nonce, generate_session_token, hash_key,
    verify_signature, build_kol_register_message, build_kol_login_message,
)
from app.services import database

router = APIRouter(prefix="/v1/kols", tags=["kols"])

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
        raise HTTPException(status_code=403, detail="KOL account suspended")
    return kol


# ========== Public Endpoints ==========

@router.get("/public/{handle}", response_model=KolPublicProfile)
async def get_public_profile(handle: str):
    kol = await database.get_kol_by_handle(handle)
    if not kol:
        raise HTTPException(status_code=404, detail="KOL not found")
    return KolPublicProfile(
        handle=kol["handle"],
        name=kol["name"],
        bio=kol.get("bio", ""),
        twitter=kol.get("twitter", ""),
        enrolled_vaults=kol.get("enrolled_vaults", []),
        created_at=kol["created_at"].isoformat() if kol.get("created_at") else "",
    )


# ========== Auth Endpoints ==========

@router.post("/nonce", response_model=KolNonceResponse)
async def get_nonce(req: KolNonceRequest):
    # Mutual exclusion: wallet partners cannot register as KOLs
    existing_partner = await database.get_partner_by_address(req.address)
    if existing_partner:
        raise HTTPException(
            status_code=409,
            detail="This address is already registered as a wallet partner. A wallet cannot also be a KOL.",
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
    # Mutual exclusion: cannot be both a wallet partner and KOL
    existing_partner = await database.get_partner_by_address(req.address)
    if existing_partner:
        raise HTTPException(status_code=409, detail="This address is already registered as a wallet partner.")

    existing_kol = await database.get_kol_by_address(req.address)
    if existing_kol:
        raise HTTPException(status_code=409, detail="Address already registered as a KOL")

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

    return KolRegisterResponse(
        address=kol["address"],
        handle=kol["handle"],
        name=kol["name"],
        created_at=kol["created_at"].isoformat(),
    )


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
