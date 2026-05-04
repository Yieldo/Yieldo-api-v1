from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Depends, Request
from app.models import (
    PartnerNonceRequest, PartnerNonceResponse,
    PartnerRegisterRequest, PartnerRegisterResponse,
    PartnerLoginRequest, PartnerLoginResponse,
    PartnerProfile, PartnerSettingsUpdate,
    PartnerVaultsUpdate, PartnerDashboardResponse,
    PartnerAPIKeyRotateResponse,
)
from app.core.auth import (
    generate_api_key, generate_api_secret, generate_nonce,
    generate_session_token, hash_key, key_prefix,
    verify_signature, build_register_message, build_login_message,
)
from app.services import database

router = APIRouter(prefix="/v1/partners", tags=["partners"])

SESSION_DURATION_HOURS = 24


# ========== Auth Dependencies ==========

async def get_current_partner(request: Request) -> dict:
    """Verify session token from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = auth[7:]
    session = await database.get_session(hash_key(token))
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    partner = await database.get_partner_by_address(session["address"])
    if not partner or partner["status"] != "active":
        raise HTTPException(status_code=403, detail="Partner account suspended")
    return partner


async def get_partner_from_api_key(request: Request):
    """Verify API key + secret from headers. Returns partner or None."""
    api_key = request.headers.get("X-API-Key")
    api_secret = request.headers.get("X-API-Secret")
    if not api_key or not api_secret:
        return None
    partner = await database.get_partner_by_api_key(hash_key(api_key))
    if not partner:
        return None
    if partner["api_secret_hash"] != hash_key(api_secret):
        return None
    return partner


# ========== Auth Endpoints ==========

@router.post("/nonce", response_model=PartnerNonceResponse)
async def get_nonce(req: PartnerNonceRequest):
    """Get a nonce to sign for registration or login."""
    nonce = generate_nonce()
    await database.save_nonce(req.address, nonce)
    # Check if already registered to decide message type
    existing = await database.get_partner_by_address(req.address)
    if existing:
        message = build_login_message(req.address, nonce)
    else:
        message = build_register_message(req.address, nonce)
    return PartnerNonceResponse(nonce=nonce, message=message)


@router.post("/register", response_model=PartnerRegisterResponse)
async def register(req: PartnerRegisterRequest):
    """Register a new wallet partner with signature verification.

    Wallet partner registration is invite-only — the address must have an
    approved application (status='approved' in `applications` collection).
    Apply via /v1/applications/wallet first.
    """
    # Check uniqueness
    existing = await database.get_partner_by_address(req.address)
    if existing:
        raise HTTPException(status_code=409, detail="Address already registered")

    # Application gate
    app_doc = await database.get_application(req.address, "wallet")
    if not app_doc:
        raise HTTPException(
            status_code=403,
            detail="Wallet partner registration is invite-only. Submit an application at /v1/applications/wallet first.",
        )
    if app_doc.get("status") == "pending":
        raise HTTPException(
            status_code=403,
            detail="Your application is under review. We'll respond within 48 hours.",
        )
    if app_doc.get("status") == "rejected":
        raise HTTPException(status_code=403, detail="Application was rejected.")
    if app_doc.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Application not approved.")

    # If client passed an explicit nonce, validate signature against it AND
    # remove that specific nonce from the DB. Otherwise fall back to "use
    # whatever nonce is latest" (legacy behavior, susceptible to races).
    nonce = req.nonce if req.nonce else await database.get_and_delete_nonce(req.address)
    if not nonce:
        raise HTTPException(status_code=400, detail="No pending nonce. Request /nonce first.")

    # Verify signature
    message = build_register_message(req.address, nonce)
    if not verify_signature(req.address, message, req.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # If we used an explicit client-supplied nonce, also clear any other
    # nonces sitting in DB for this address so they can't be replayed.
    if req.nonce:
        await database.delete_nonces_for_address(req.address)

    # Generate API credentials
    raw_key, key_hash = generate_api_key()
    raw_secret, secret_hash = generate_api_secret()
    prefix = key_prefix(raw_key)

    # Pull missing fields from the approved application's form_data so the
    # client doesn't have to re-collect data the user already submitted.
    form_data = (app_doc.get("form_data") or {}) if app_doc else {}
    derived_description = " · ".join(p for p in [
        f"Role: {form_data.get('role')}" if form_data.get("role") else None,
        f"MAU: {form_data.get('mau')}" if form_data.get("mau") else None,
        f"Chains: {', '.join(form_data['chains'])}" if form_data.get("chains") else None,
        f"Telegram: {form_data.get('telegram')}" if form_data.get("telegram") else None,
    ] if p)

    partner = await database.create_partner(
        address=req.address,
        name=req.name or form_data.get("company") or "Wallet Partner",
        website=req.website or form_data.get("website", ""),
        contact_email=req.contact_email or form_data.get("email", ""),
        description=req.description or derived_description,
        api_key_hash=key_hash,
        api_secret_hash=secret_hash,
        api_key_prefix=prefix,
    )

    # Issue a session token alongside registration so the client doesn't
    # need a second signature for /login.
    token = generate_session_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)
    await database.save_session(hash_key(token), req.address, expires)

    return PartnerRegisterResponse(
        address=partner["address"],
        name=partner["name"],
        api_key=raw_key,
        api_secret=raw_secret,
        api_key_prefix=prefix,
        created_at=partner["created_at"].isoformat(),
        session_token=token,
        expires_at=expires.isoformat(),
    )


@router.post("/login", response_model=PartnerLoginResponse)
async def login(req: PartnerLoginRequest):
    """Login with wallet signature. Returns session token."""
    partner = await database.get_partner_by_address(req.address)
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found. Register first.")

    nonce = req.nonce if req.nonce else await database.get_and_delete_nonce(req.address)
    if not nonce:
        raise HTTPException(status_code=400, detail="No pending nonce. Request /nonce first.")

    message = build_login_message(req.address, nonce)
    if not verify_signature(req.address, message, req.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if req.nonce:
        await database.delete_nonces_for_address(req.address)

    # Create session
    token = generate_session_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_DURATION_HOURS)
    await database.save_session(hash_key(token), req.address, expires)

    return PartnerLoginResponse(
        session_token=token,
        expires_at=expires.isoformat(),
        partner={
            "address": partner["address"],
            "name": partner["name"],
            "status": partner["status"],
            "api_key_prefix": partner.get("api_key_prefix", ""),
        },
    )


# ========== Authenticated Portal Endpoints ==========

@router.get("/me", response_model=PartnerProfile)
async def get_profile(partner: dict = Depends(get_current_partner)):
    return PartnerProfile(
        address=partner["address"],
        name=partner["name"],
        website=partner.get("website", ""),
        contact_email=partner.get("contact_email", ""),
        description=partner.get("description", ""),
        fee_enabled=partner.get("fee_enabled", True),
        fee_collector_address=partner.get("fee_collector_address", partner["address"]),
        webhook_url=partner.get("webhook_url", ""),
        enrolled_vaults=partner.get("enrolled_vaults", []),
        api_key_prefix=partner.get("api_key_prefix", ""),
        created_at=partner["created_at"].isoformat() if partner.get("created_at") else "",
        status=partner.get("status", "active"),
    )


@router.put("/settings")
async def update_settings(
    req: PartnerSettingsUpdate,
    partner: dict = Depends(get_current_partner),
):
    fields = {}
    if req.fee_enabled is not None:
        fields["fee_enabled"] = req.fee_enabled
    if req.fee_collector_address is not None:
        fields["fee_collector_address"] = req.fee_collector_address.lower()
    if req.webhook_url is not None:
        fields["webhook_url"] = req.webhook_url
    if req.name is not None:
        fields["name"] = req.name
    if req.website is not None:
        fields["website"] = req.website
    if req.contact_email is not None:
        fields["contact_email"] = req.contact_email
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    await database.update_partner(partner["address"], fields)
    return {"success": True}


@router.put("/vaults")
async def update_vaults(
    req: PartnerVaultsUpdate,
    partner: dict = Depends(get_current_partner),
):
    await database.update_partner(partner["address"], {"enrolled_vaults": req.enrolled_vaults})
    return {"success": True}


@router.get("/dashboard", response_model=PartnerDashboardResponse)
async def get_dashboard(partner: dict = Depends(get_current_partner)):
    data = await database.get_partner_dashboard(partner["address"])
    return PartnerDashboardResponse(**data)


@router.get("/transactions")
async def get_transactions(
    limit: int = 50,
    skip: int = 0,
    partner: dict = Depends(get_current_partner),
):
    txns = await database.get_partner_transactions(partner["address"], limit=limit, skip=skip)
    for t in txns:
        if "created_at" in t and isinstance(t["created_at"], datetime):
            t["created_at"] = t["created_at"].isoformat()
    return txns


@router.post("/api-keys/rotate", response_model=PartnerAPIKeyRotateResponse)
async def rotate_api_keys(partner: dict = Depends(get_current_partner)):
    """Generate new API key + secret. Old ones are immediately invalidated."""
    raw_key, key_hash = generate_api_key()
    raw_secret, secret_hash = generate_api_secret()
    prefix = key_prefix(raw_key)
    await database.rotate_partner_keys(partner["address"], key_hash, secret_hash, prefix)
    return PartnerAPIKeyRotateResponse(
        api_key=raw_key,
        api_secret=raw_secret,
        api_key_prefix=prefix,
    )


@router.post("/logout")
async def logout(partner: dict = Depends(get_current_partner)):
    await database.delete_sessions(partner["address"])
    return {"success": True}
