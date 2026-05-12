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

from fastapi import APIRouter, HTTPException, Query, Response

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
async def og_vault_card(
    vault_id: str,
    # Score values can be passed in via the URL to "freeze" the card at the
    # moment of sharing. This solves the X embed inconsistency where the
    # tweet text was generated at share-time (e.g. "Score 80/100, Risk 29/35")
    # but the OG image was rendered live when Twitter scraped — so by the
    # time the user saw the embed in their feed, the score had drifted (77,
    # Risk 79) and the image visibly disagreed with the text. When the
    # frontend includes these query params in the share URL, Twitter sees a
    # unique URL per share, scrapes a fresh image, and the resulting card
    # mirrors the tweet body byte-for-byte. Doubles as cache-busting: each
    # distinct score combo gets its own cache key.
    score:       Optional[int]   = Query(None, ge=0, le=100),
    capital:     Optional[int]   = Query(None, ge=0, le=100),
    performance: Optional[int]   = Query(None, ge=0, le=100),
    risk:        Optional[int]   = Query(None, ge=0, le=100),
    trust:       Optional[int]   = Query(None, ge=0, le=100),
    apy:         Optional[float] = Query(None),
):
    """Render a branded OG card for this vault and return it as a PNG.

    If score/sub-score/apy query params are provided, they take precedence
    over the latest indexer snapshot — the FE uses this to lock the image
    to the values that appear in the tweet body at share time.

    Always 200 with an image — even if the vault has no score yet (placeholder
    rendering). Only 404s if the vault_id isn't in the registry at all.
    """
    v = get_vault(vault_id)
    if not v:
        raise HTTPException(status_code=404, detail=f"Vault {vault_id} not found")

    # Fetch the live snapshot anyway — it's the fallback for any param the
    # caller didn't supply, so a partial override still renders a complete
    # card. Cheap query against an indexed (vault_id, ts) field.
    snap = await _latest_snapshot(vault_id)

    # Score: caller-provided wins, else latest snapshot, else None.
    final_score = score if score is not None else (_int_or_none(snap.get("yieldo_score")) if snap else None)

    # Sub-scores: each one independently overridable. Caller-provided wins,
    # else snapshot, else None (renderer draws "—" for missing).
    snapshot_sub = {
        ui_key: _int_or_none(snap.get(snap_key)) if snap else None
        for ui_key, snap_key in _SUBSCORE_MAP
    }
    overrides = {
        "capital":     capital,
        "performance": performance,
        "risk":        risk,
        "trust":       trust,
    }
    final_sub = {
        k: (overrides[k] if overrides[k] is not None else snapshot_sub.get(k))
        for k in snapshot_sub.keys()
    }

    # APY: caller passes it as percent (e.g. 4.26 for 4.26%), but snapshot
    # stores it as a decimal (0.0426). Keep their semantics distinct.
    final_apy: Optional[float] = None
    if apy is not None:
        final_apy = float(apy)
    elif snap:
        metrics = snap.get("metrics") or {}
        net_apy = metrics.get("net_apy")
        if isinstance(net_apy, (int, float)):
            final_apy = float(net_apy) * 100

    png = render_card(
        vault_name=v.get("name") or vault_id,
        score=final_score,
        sub_scores=final_sub,
        curator=v.get("curator_name") or v.get("curator"),
        chain=v.get("chain_name"),
        asset=v.get("asset_symbol"),
        protocol=v.get("protocol"),
        apy=final_apy,
    )

    # Cache strategy: when the caller passes locked score params we can
    # cache "forever" (immutable per-URL) because the URL is the source of
    # truth, not the live data. Without the lock we cache short because
    # the underlying snapshot will move. Either way SWR keeps social-bot
    # rescrapes from ever seeing a 5xx during a backend hiccup.
    locked = any(p is not None for p in (score, capital, performance, risk, trust, apy))
    if locked:
        cache_control = "public, max-age=86400, s-maxage=604800, immutable"
    else:
        cache_control = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"

    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": cache_control,
            "Vary": "Accept-Encoding",
        },
    )
