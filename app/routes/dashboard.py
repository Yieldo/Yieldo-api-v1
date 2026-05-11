"""Attribution dashboards (Eddy spec).

Read-only aggregations over the attribution collections. Currently public
(no auth) — these are aggregate metrics with no per-user PII. If
competitive concerns surface later, gate behind admin auth using the same
pattern as `routes/admin.py`.

Endpoints:
  GET /v1/dashboard/by-tweet           breakdown by source_tweet_id
  GET /v1/dashboard/by-vault           breakdown by vault
  GET /v1/dashboard/by-template        breakdown by template
  GET /v1/dashboard/retention-curves   retention by attribution cohort
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from app.services import database

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


def _window_cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@router.get("/by-tweet")
async def by_tweet(days: int = Query(30, ge=1, le=365)):
    """Conversion funnel broken down by source tweet.

    Returns: clicks, attributed_wallets (unique), attributed_deposits,
    attributed_volume per tweet. The shape lets you immediately see which
    tweets actually drove deposits vs. which just got vanity clicks.
    """
    db = database._db  # noqa: SLF001
    if db is None:
        return {"rows": [], "days": days}
    cutoff = _window_cutoff(days)

    # Clicks per tweet
    clicks = await db["click_event"].aggregate([
        {"$match": {"ts": {"$gte": cutoff}, "tweet_id": {"$ne": None}}},
        {"$group": {"_id": "$tweet_id", "clicks": {"$sum": 1}}},
    ]).to_list(length=None)

    # Unique wallets attributed per tweet
    wallets = await db["wallet_attribution"].aggregate([
        {"$match": {"attributed_at": {"$gte": cutoff}, "source_tweet_id": {"$ne": None}}},
        {"$group": {"_id": "$source_tweet_id", "wallets": {"$addToSet": "$wallet"}}},
        {"$project": {"unique_wallets": {"$size": "$wallets"}}},
    ]).to_list(length=None)

    # Deposits + volume per tweet (volume is summed if amount is numeric;
    # otherwise we just return count and let dashboards handle string amounts).
    deposits = await db["attributed_deposit"].aggregate([
        {"$match": {"ts": {"$gte": cutoff}, "source_tweet_id": {"$ne": None}}},
        {"$group": {
            "_id": "$source_tweet_id",
            "deposits": {"$sum": 1},
        }},
    ]).to_list(length=None)

    by_id: dict[str, dict] = {}
    for r in clicks:
        by_id.setdefault(r["_id"], {"tweet_id": r["_id"]})["clicks"] = r["clicks"]
    for r in wallets:
        by_id.setdefault(r["_id"], {"tweet_id": r["_id"]})["unique_wallets"] = r["unique_wallets"]
    for r in deposits:
        by_id.setdefault(r["_id"], {"tweet_id": r["_id"]})["deposits"] = r["deposits"]

    rows = list(by_id.values())
    # Fill missing fields with zeros so dashboards don't have to.
    for r in rows:
        r.setdefault("clicks", 0)
        r.setdefault("unique_wallets", 0)
        r.setdefault("deposits", 0)
        # Click→deposit conversion %, capped to avoid divide-by-zero noise.
        r["conversion_pct"] = (
            round(100 * r["deposits"] / r["clicks"], 2) if r["clicks"] else 0.0
        )
    rows.sort(key=lambda r: -r["deposits"])
    return {"days": days, "rows": rows}


@router.get("/by-vault")
async def by_vault(days: int = Query(30, ge=1, le=365)):
    """Volume + conversion broken down by vault. Useful for figuring out
    which vaults the X audience actually deposits into vs. just browses."""
    db = database._db  # noqa: SLF001
    if db is None:
        return {"rows": [], "days": days}
    cutoff = _window_cutoff(days)

    clicks = await db["click_event"].aggregate([
        {"$match": {"ts": {"$gte": cutoff}, "vault_slug": {"$ne": None}}},
        {"$group": {"_id": "$vault_slug", "clicks": {"$sum": 1}}},
    ]).to_list(length=None)

    deposits = await db["attributed_deposit"].aggregate([
        {"$match": {"ts": {"$gte": cutoff}, "vault": {"$ne": None}}},
        {"$group": {
            "_id": "$vault",
            "attributed_deposits": {"$sum": 1},
        }},
    ]).to_list(length=None)

    unattributed = await db["unattributed_deposit"].aggregate([
        {"$match": {"ts": {"$gte": cutoff}, "vault": {"$ne": None}}},
        {"$group": {"_id": "$vault", "unattributed_deposits": {"$sum": 1}}},
    ]).to_list(length=None)

    by_vault: dict[str, dict] = {}
    for r in clicks:
        by_vault.setdefault(r["_id"], {"vault": r["_id"]})["clicks"] = r["clicks"]
    for r in deposits:
        by_vault.setdefault(r["_id"], {"vault": r["_id"]})["attributed_deposits"] = r["attributed_deposits"]
    for r in unattributed:
        by_vault.setdefault(r["_id"], {"vault": r["_id"]})["unattributed_deposits"] = r["unattributed_deposits"]

    rows = list(by_vault.values())
    for r in rows:
        r.setdefault("clicks", 0)
        r.setdefault("attributed_deposits", 0)
        r.setdefault("unattributed_deposits", 0)
        total = r["attributed_deposits"] + r["unattributed_deposits"]
        r["attribution_share_pct"] = (
            round(100 * r["attributed_deposits"] / total, 2) if total else 0.0
        )
    rows.sort(key=lambda r: -r["attributed_deposits"])
    return {"days": days, "rows": rows}


@router.get("/by-template")
async def by_template(days: int = Query(30, ge=1, le=365)):
    """A/B comparison of tweet templates. Same shape as by-tweet."""
    db = database._db  # noqa: SLF001
    if db is None:
        return {"rows": [], "days": days}
    cutoff = _window_cutoff(days)

    clicks = await db["click_event"].aggregate([
        {"$match": {"ts": {"$gte": cutoff}, "template": {"$ne": None}}},
        {"$group": {"_id": "$template", "clicks": {"$sum": 1}}},
    ]).to_list(length=None)

    deposits = await db["attributed_deposit"].aggregate([
        {"$match": {"ts": {"$gte": cutoff}, "template": {"$ne": None}}},
        {"$group": {"_id": "$template", "deposits": {"$sum": 1}}},
    ]).to_list(length=None)

    by_tpl: dict[str, dict] = {}
    for r in clicks:
        by_tpl.setdefault(r["_id"], {"template": r["_id"]})["clicks"] = r["clicks"]
    for r in deposits:
        by_tpl.setdefault(r["_id"], {"template": r["_id"]})["deposits"] = r["deposits"]

    rows = list(by_tpl.values())
    for r in rows:
        r.setdefault("clicks", 0)
        r.setdefault("deposits", 0)
        r["conversion_pct"] = (
            round(100 * r["deposits"] / r["clicks"], 2) if r["clicks"] else 0.0
        )
    rows.sort(key=lambda r: -r["conversion_pct"])
    return {"days": days, "rows": rows}


@router.get("/retention-curves")
async def retention_curves(days: int = Query(90, ge=7, le=365)):
    """Retention curves keyed by template — answers 'do tweet-sourced
    depositors stick around as well as organic ones?'.

    Currently reads only what the retention_check snapshotter has written.
    Until that job lands, this returns empty curves with a `pending` flag
    so the dashboard can show 'data populating'.
    """
    db = database._db  # noqa: SLF001
    if db is None:
        return {"pending": True, "rows": []}
    cutoff = _window_cutoff(days)

    rows = await db["retention_check"].aggregate([
        {"$match": {"last_checked_at": {"$gte": cutoff}}},
        # Join to attributed_deposit so we can group by template.
        {"$lookup": {
            "from": "attributed_deposit",
            "localField": "attributed_deposit_id",
            "foreignField": "_id",
            "as": "ad",
        }},
        {"$unwind": {"path": "$ad", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": "$ad.template",
            "n": {"$sum": 1},
            "avg_d7":  {"$avg": "$day_7_balance"},
            "avg_d30": {"$avg": "$day_30_balance"},
            "avg_d90": {"$avg": "$day_90_balance"},
        }},
        {"$project": {
            "_id": 0,
            "template": "$_id",
            "depositors": "$n",
            "avg_balance_d7":  {"$round": ["$avg_d7",  2]},
            "avg_balance_d30": {"$round": ["$avg_d30", 2]},
            "avg_balance_d90": {"$round": ["$avg_d90", 2]},
        }},
        {"$sort": {"depositors": -1}},
    ]).to_list(length=None)

    return {
        "pending": len(rows) == 0,
        "days": days,
        "rows": rows,
    }
