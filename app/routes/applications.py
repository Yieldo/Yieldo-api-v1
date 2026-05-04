"""Unified application queue for wallet partners and creators (KOLs).

Both flows are invite-only — users submit a SIWE-signed application and an
admin manually approves it (creates the actual partner / creator record).

Mutex: an address can hold at most one pending OR approved application across
audiences. So a user can apply for `wallet` OR `creator` but not both.

Endpoints:
  POST /v1/applications/nonce               request a SIWE nonce
  POST /v1/applications/{audience}          submit application (audience: wallet|creator)
  GET  /v1/applications/me/{address}        check my application status (public)
  GET  /v1/applications                     admin: list applications (filter by status/audience)
  POST /v1/applications/{address}/{audience}/approve   admin: approve
  POST /v1/applications/{address}/{audience}/reject    admin: reject
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel, EmailStr, Field

from app.core.auth import generate_nonce, verify_signature
from app.services import database

router = APIRouter(prefix="/v1/applications", tags=["applications"])

ALLOWED_AUDIENCES = {"wallet", "creator"}


def build_application_message(audience: str, address: str, nonce: str) -> str:
    label = "Wallet Partner" if audience == "wallet" else "Creator"
    return (
        f"Sign this message to apply as a Yieldo {label}.\n\n"
        f"Address: {address}\n"
        f"Nonce: {nonce}"
    )


def _admin_guard(x_admin_key: Optional[str]) -> None:
    expected = os.environ.get("YIELDO_ADMIN_KEY")
    if not expected:
        raise HTTPException(503, "Admin operations are not configured (set YIELDO_ADMIN_KEY)")
    if not x_admin_key or x_admin_key != expected:
        raise HTTPException(401, "Invalid admin key")


# --------------------------------------------------------------------------
# Request / response models
# --------------------------------------------------------------------------

class NonceRequest(BaseModel):
    address: str
    audience: str  # "wallet" | "creator"


class NonceResponse(BaseModel):
    nonce: str
    message: str


class WalletApplicationData(BaseModel):
    company: str = Field(..., min_length=1, max_length=120)
    role: str = ""
    mau: str = ""
    chains: list[str] = []
    email: str
    telegram: str = ""


class CreatorApplicationData(BaseModel):
    handle: str = Field(..., min_length=1, max_length=80)
    platform: str = ""
    audience_size: str = ""
    content_types: list[str] = []
    email: str
    telegram: str = ""


class SubmitRequest(BaseModel):
    address: str
    signature: str
    form: dict  # validated per-audience below


# --------------------------------------------------------------------------
# Public — applicant flow
# --------------------------------------------------------------------------

@router.post("/nonce", response_model=NonceResponse)
async def application_nonce(req: NonceRequest):
    if req.audience not in ALLOWED_AUDIENCES:
        raise HTTPException(400, f"audience must be one of {sorted(ALLOWED_AUDIENCES)}")
    addr = req.address.strip()
    if not addr.startswith("0x") or len(addr) != 42:
        raise HTTPException(400, "Invalid address")

    # Mutex pre-check (so the user gets a clear error before signing).
    other = await database.get_any_application(addr)
    if other and other.get("audience") != req.audience:
        raise HTTPException(
            409,
            f"Address already has a {other['status']} application as "
            f"{'wallet partner' if other['audience'] == 'wallet' else 'creator'}. "
            f"Withdraw it before applying for the other role.",
        )
    same = await database.get_application(addr, req.audience)
    if same and same.get("status") in ("pending", "approved"):
        raise HTTPException(
            409,
            f"You already have a {same['status']} application for this role.",
        )

    nonce = generate_nonce()
    await database.save_application_nonce(addr, nonce)
    return NonceResponse(
        nonce=nonce,
        message=build_application_message(req.audience, addr, nonce),
    )


@router.post("/{audience}")
async def submit_application(audience: str, req: SubmitRequest):
    if audience not in ALLOWED_AUDIENCES:
        raise HTTPException(400, f"audience must be one of {sorted(ALLOWED_AUDIENCES)}")

    addr = req.address.strip()
    if not addr.startswith("0x") or len(addr) != 42:
        raise HTTPException(400, "Invalid address")

    # Re-verify mutex at submit time (state may have changed since /nonce).
    other = await database.get_any_application(addr)
    if other and other.get("audience") != audience:
        raise HTTPException(
            409,
            f"Address already has a {other['status']} application as "
            f"{'wallet partner' if other['audience'] == 'wallet' else 'creator'}.",
        )
    same = await database.get_application(addr, audience)
    if same and same.get("status") in ("pending", "approved"):
        raise HTTPException(409, f"Application already {same['status']}.")

    # SIWE — verify the signed nonce
    nonce = await database.get_and_delete_application_nonce(addr)
    if not nonce:
        raise HTTPException(400, "No pending nonce. Request /nonce first.")
    expected_msg = build_application_message(audience, addr, nonce)
    if not verify_signature(addr, expected_msg, req.signature):
        raise HTTPException(401, "Invalid signature")

    # Light per-audience validation (raises if missing required fields).
    form = req.form or {}
    if audience == "wallet":
        try:
            WalletApplicationData(**form)
        except Exception as e:
            raise HTTPException(400, f"Invalid wallet form: {e}")
    else:
        try:
            CreatorApplicationData(**form)
        except Exception as e:
            raise HTTPException(400, f"Invalid creator form: {e}")

    # If there was a previous rejected application, allow re-apply (overwrite).
    if same and same.get("status") == "rejected":
        await database.update_application_status(addr, audience, "pending")
        # also overwrite form_data
        if database._db is not None:
            await database._db["applications"].update_one(
                {"address": addr.lower(), "audience": audience},
                {"$set": {"form_data": form, "updated_at": datetime.now(timezone.utc)}},
            )
        return {"ok": True, "status": "pending", "resubmitted": True}

    app_id = await database.save_application(addr, audience, form)
    return {"ok": True, "application_id": app_id, "status": "pending"}


@router.get("/me/{address}")
async def my_application(address: str):
    """Public — let an applicant poll their own status. No auth needed."""
    addr = address.strip().lower()
    docs = []
    for aud in sorted(ALLOWED_AUDIENCES):
        doc = await database.get_application(addr, aud)
        if doc:
            docs.append({
                "audience": doc.get("audience"),
                "status": doc.get("status"),
                "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                "approved_at": doc.get("approved_at").isoformat() if doc.get("approved_at") else None,
            })
    return {"address": addr, "applications": docs}


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------

@router.get("")
async def list_apps(
    request: Request,
    status: Optional[str] = None,
    audience: Optional[str] = None,
    limit: int = 100,
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    _admin_guard(x_admin_key)
    docs = await database.list_applications(status=status, audience=audience, limit=limit)
    return {
        "applications": [
            {
                "address": d.get("address"),
                "audience": d.get("audience"),
                "status": d.get("status"),
                "form_data": d.get("form_data"),
                "created_at": d.get("created_at").isoformat() if d.get("created_at") else None,
                "approved_at": d.get("approved_at").isoformat() if d.get("approved_at") else None,
                "rejected_at": d.get("rejected_at").isoformat() if d.get("rejected_at") else None,
                "admin_note": d.get("admin_note", ""),
            }
            for d in docs
        ],
        "count": len(docs),
    }


@router.post("/{address}/{audience}/approve")
async def approve_application(
    address: str,
    audience: str,
    request: Request,
    note: str = "",
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    _admin_guard(x_admin_key)
    if audience not in ALLOWED_AUDIENCES:
        raise HTTPException(400, f"audience must be one of {sorted(ALLOWED_AUDIENCES)}")
    addr = address.strip().lower()
    app_doc = await database.get_application(addr, audience)
    if not app_doc:
        raise HTTPException(404, "Application not found")
    if app_doc.get("status") == "approved":
        return {"ok": True, "status": "already_approved"}

    # Flip the application status. The actual partner/creator record is
    # created when the user next signs in via SIWE on /v1/partners/login or
    # /v1/creators/login — we don't need to materialize it eagerly; the
    # approval just unlocks the mutex check there.
    ok = await database.update_application_status(addr, audience, "approved", note=note)
    if not ok:
        raise HTTPException(500, "Failed to update status")
    return {"ok": True, "address": addr, "audience": audience, "status": "approved"}


@router.post("/{address}/{audience}/reject")
async def reject_application(
    address: str,
    audience: str,
    request: Request,
    note: str = "",
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    _admin_guard(x_admin_key)
    if audience not in ALLOWED_AUDIENCES:
        raise HTTPException(400, f"audience must be one of {sorted(ALLOWED_AUDIENCES)}")
    addr = address.strip().lower()
    app_doc = await database.get_application(addr, audience)
    if not app_doc:
        raise HTTPException(404, "Application not found")
    ok = await database.update_application_status(addr, audience, "rejected", note=note)
    if not ok:
        raise HTTPException(500, "Failed to update status")
    return {"ok": True, "address": addr, "audience": audience, "status": "rejected"}
