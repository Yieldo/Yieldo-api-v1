"""Open Graph card endpoints.

Serves per-vault preview PNGs so that any link to `app.yieldo.xyz/vault/{id}`
pasted into X/Telegram/Discord/Farcaster renders a branded score card —
turning every share into a marketing impression.

Hot path:
  GET /v1/og/vault/{vault_id}.png

The renderer (`app.services.og_card.render_card`) is pure Python (Pillow) and
takes ~40-80ms per image. We cache aggressively at the edge via Cache-Control
headers so social bot rescrapes don't hammer Pillow.

Frontend integration (next step, NOT done here):
  The Vite SPA's `index.html` serves the same `<meta property="og:image">`
  for every route, so we need either:
    a) A Cloudflare Worker / Vercel rewrite that intercepts `/vault/{id}`
       and rewrites the meta tag to point at this endpoint.
    b) Per-vault static HTML generated at build time.
  Until that's wired, this endpoint is still useful for:
    - Embed badges that link directly to the image
    - Manual sharing where the user pastes the API URL itself
    - Future docs/marketing assets
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Response

from app.services import database
from app.services.og_card import render_card
from app.services.vault import get_vault

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/og", tags=["og"])

# Map indexer-snapshot field names to the renderer's `sub_scores` keys.
_SUBSCORE_MAP = (
    ("capital",     "capital_score"),
    ("performance", "performance_score"),
    ("risk",        "risk_score"),
    ("trust",       "trust_score"),
)


async def _latest_snapshot(vault_id: str) -> Optional[dict]:
    """Most recent score_snapshots doc for this vault — or None if the
    indexer hasn't covered this vault yet (very new listings)."""
    db = database.get_indexer_db()
    if db is None:
        return None
    # 7-day window: if there's nothing newer than that, treat as "no score"
    # rather than serving a stale snapshot from months ago.
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    doc = await db["score_snapshots"].find_one(
        {"vault_id": vault_id, "ts": {"$gte": cutoff}},
        sort=[("ts", -1)],
    )
    return doc


def _int_or_none(v) -> Optional[int]:
    """Round to int, but only if the source value is an actual number.
    Returns None for missing/null so the renderer shows '—' instead of '0'."""
    if isinstance(v, (int, float)):
        return max(0, min(100, int(round(v))))
    return None


@router.get("/vault/{vault_id}.png")
async def og_vault_card(vault_id: str):
    """Render a branded OG card for this vault and return it as a PNG.

    Always 200 with an image — even if the vault has no score yet (placeholder
    rendering). Only 404s if the vault_id isn't in the registry at all.
    """
    v = get_vault(vault_id)
    if not v:
        raise HTTPException(status_code=404, detail=f"Vault {vault_id} not found")

    snap = await _latest_snapshot(vault_id)
    score = _int_or_none(snap.get("yieldo_score")) if snap else None
    sub_scores = {
        ui_key: _int_or_none(snap.get(snap_key)) if snap else None
        for ui_key, snap_key in _SUBSCORE_MAP
    }
    # net_apy is the apy after fees — what the depositor actually earns. Same
    # field the frontend's APY card uses.
    apy = None
    if snap:
        metrics = snap.get("metrics") or {}
        net_apy = metrics.get("net_apy")
        if isinstance(net_apy, (int, float)):
            apy = float(net_apy) * 100  # snapshots store APY as a decimal

    png = render_card(
        vault_name=v.get("name") or vault_id,
        score=score,
        sub_scores=sub_scores,
        curator=v.get("curator_name") or v.get("curator"),
        chain=v.get("chain_name"),
        asset=v.get("asset_symbol"),
        protocol=v.get("protocol"),
        apy=apy,
    )

    # Cache hard at edge + browser. Score changes ~hourly so 1h s-maxage is
    # fine; SWR keeps the previous image visible while a refresh happens
    # behind the scenes so social-bot rescrapes never see a 5xx.
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400",
            "Vary": "Accept-Encoding",
        },
    )
