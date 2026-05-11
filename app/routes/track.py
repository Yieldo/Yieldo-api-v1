"""Attribution tracking endpoints (Eddy spec).

Public endpoints, no auth — anyone can record a click. The risk surface is
low because:
  - We never link wallets to PII (X handles etc.). The wallet ↔ tweet_id
    link is the *most* identifying thing we store, and tweet_id is public.
  - Click rows auto-expire after 30d via a Mongo TTL index.
  - The wallet attribution is a no-op unless the caller has the click_id
    cookie that the click endpoint returned — so spam is bounded to inserting
    bogus rows in `click_event`, which nobody downstream reads.

Endpoints:
  POST /v1/track/click       capture URL params, set click cookie, write click_event
  POST /v1/track/attribute   link wallet ↔ recent click (called at SIWE login)
"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.services import database

router = APIRouter(prefix="/v1/track", tags=["track"])

# 7d cookie window matches Eddy's attribution window. After this the cookie
# is dropped client-side and we treat the next deposit as unattributed.
CLICK_COOKIE_NAME = "yieldo_click"
CLICK_COOKIE_MAX_AGE = 7 * 24 * 3600


def _new_click_id() -> str:
    # 22 chars of URL-safe base64-ish entropy. Cheap to generate, not
    # guessable, plenty wide for the volumes we'd see at scale.
    return secrets.token_urlsafe(16)


class ClickIn(BaseModel):
    tweet_id: Optional[str] = None
    vault_slug: Optional[str] = None
    template: Optional[str] = None
    cohort: Optional[str] = None
    src: Optional[str] = None


class ClickOut(BaseModel):
    click_id: str


@router.post("/click", response_model=ClickOut)
async def track_click(payload: ClickIn, request: Request, response: Response):
    """Record a click and return a click_id. The frontend stores this
    server-side as a cookie so future requests on the same browser carry it
    automatically. No auth required — the click_id is the only secret here
    and it's bound to a single visitor.

    Bound any obvious-spam shape (very long template / cohort) silently
    rather than 400ing — a frontend bug or misuse should never break the
    attribution funnel; in the worst case the row is just garbage.
    """
    click_id = _new_click_id()
    ua = (request.headers.get("user-agent") or "")[:512]
    await database.record_click_event(
        click_id=click_id,
        tweet_id=(payload.tweet_id or None) and payload.tweet_id[:128],
        vault_slug=(payload.vault_slug or None) and payload.vault_slug[:128],
        template=(payload.template or None) and payload.template[:64],
        cohort=(payload.cohort or None) and payload.cohort[:64],
        src=(payload.src or None) and payload.src[:64],
        user_agent=ua,
    )
    # We also return the click_id in the response body so a frontend that
    # can't read its own cookies (cross-subdomain / SameSite gotchas) can
    # forward it on the next auth request as a fallback.
    response.set_cookie(
        key=CLICK_COOKIE_NAME,
        value=click_id,
        max_age=CLICK_COOKIE_MAX_AGE,
        httponly=False,           # frontend reads it to send with login
        secure=True,
        samesite="lax",
        path="/",
    )
    return ClickOut(click_id=click_id)


class AttributeIn(BaseModel):
    wallet: str
    click_id: Optional[str] = None    # if frontend has it; else read cookie


@router.post("/attribute")
async def attribute_wallet(payload: AttributeIn, request: Request):
    """Link a wallet to its originating click. Called by the frontend right
    after SIWE login completes. We accept the click_id either in the body
    or as a cookie — the body wins to handle cross-subdomain cases."""
    wallet = (payload.wallet or "").lower()
    if not wallet or len(wallet) != 42:
        return {"ok": False, "reason": "invalid_wallet"}

    click_id = payload.click_id or request.cookies.get(CLICK_COOKIE_NAME)
    if not click_id:
        # No click cookie => visitor didn't come from a tracked URL.
        # Not an error from the frontend's perspective.
        return {"ok": True, "attributed": False, "reason": "no_click"}

    ok = await database.record_wallet_attribution(
        wallet=wallet,
        click_id=click_id,
    )
    return {"ok": ok, "attributed": ok}
