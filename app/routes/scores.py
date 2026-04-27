"""Score history + anomaly endpoints.

All endpoints read from the indexer's `score_snapshots` and `score_anomalies`
collections (written by indexer-v1 / src/score_history.py). The API connects
to the indexer DB read-only via database.get_indexer_db().

Endpoints:
  GET /v1/scores/history/{vault_id}                  full chart history
  GET /v1/scores/timeseries/{vault_id}/{metric}      single-metric chart
  GET /v1/scores/movers                              biggest score changes
  GET /v1/scores/anomalies                           detected events
  GET /v1/scores/leaderboard                         current rankings
  GET /v1/scores/compare                             multi-vault overlay
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.services import database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/scores", tags=["scores"])


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

# Top-level scalar score fields available on every snapshot doc
_SCORE_FIELDS = (
    "yieldo_score",
    "capital_score",
    "performance_score",
    "risk_score",
    "trust_score",
    "confidence_multiplier",
    "flag_penalties",
    "external_rating_bonus",
)

# Sub-metrics tracked on each snapshot under .metrics.{key}
_TIMESERIES_KEYS = (
    "yieldo_score", "capital_score", "performance_score", "risk_score", "trust_score",
    "C01_USD", "net_apy", "all_time_apy", "fee", "C07",
    "P01_1d", "P01_7d", "P01_30d",
    "P03_7d",
    "P04_30d", "P04_365d",
    "P08_30d", "P08_90d", "P08_365d",
    "C02_1d", "C02_7d", "C02_30d",
    "T01_30d", "T01_365d",
    "T04", "T07", "T11",
    "R09_top1", "R09_top5",
    "P05", "P13",
    "benchmark_apy",
)


def _get_db():
    db = database.get_indexer_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Indexer DB not connected")
    return db


def _strip_id(doc: dict) -> dict:
    doc.pop("_id", None)
    if isinstance(doc.get("ts"), datetime):
        doc["ts"] = doc["ts"].isoformat()
    return doc


def _resolve_metric_value(snapshot: dict, key: str) -> Any:
    """A metric key can be a top-level score (yieldo_score) or a metrics.* sub-field."""
    if key in _SCORE_FIELDS:
        return snapshot.get(key)
    return (snapshot.get("metrics") or {}).get(key)


# --------------------------------------------------------------------------
# /v1/scores/history/{vault_id}
# --------------------------------------------------------------------------

@router.get("/history/{vault_id:path}")
async def history(
    vault_id: str,
    days: int = Query(30, ge=1, le=365, description="History window in days"),
    interval: str = Query("hour", regex="^(hour|day)$"),
):
    """Full score history for charting. Returns hourly or daily resolution."""
    db = _get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    cursor = db["score_snapshots"].find(
        {"vault_id": vault_id, "ts": {"$gte": cutoff}},
        {"_id": 0, "active_flags": 0, "address": 0},
    ).sort("ts", 1)
    rows = await cursor.to_list(length=None)

    # Daily downsample: keep last point of each calendar day
    if interval == "day" and rows:
        by_day: dict[str, dict] = {}
        for r in rows:
            day = (r["ts"] if isinstance(r["ts"], datetime) else datetime.fromisoformat(r["ts"]))
            day_key = day.strftime("%Y-%m-%d")
            by_day[day_key] = r  # last write of day wins
        rows = list(by_day.values())

    return {
        "vault_id": vault_id,
        "days": days,
        "interval": interval,
        "count": len(rows),
        "history": [_strip_id(r) for r in rows],
    }


# --------------------------------------------------------------------------
# /v1/scores/timeseries/{vault_id}/{metric}
# --------------------------------------------------------------------------

@router.get("/timeseries/{vault_id:path}/{metric}")
async def timeseries(
    vault_id: str,
    metric: str,
    days: int = Query(30, ge=1, le=365),
):
    """Single-metric series — returns [{x: ts_iso, y: value}] for chart libs."""
    if metric not in _TIMESERIES_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown metric '{metric}'. Allowed: {sorted(_TIMESERIES_KEYS)}",
        )

    db = _get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    cursor = db["score_snapshots"].find(
        {"vault_id": vault_id, "ts": {"$gte": cutoff}},
        {"ts": 1, metric: 1, "metrics": 1, "_id": 0},
    ).sort("ts", 1)

    points = []
    async for r in cursor:
        ts = r["ts"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        v = _resolve_metric_value(r, metric)
        if v is not None:
            points.append({"x": ts, "y": v})

    return {
        "vault_id": vault_id,
        "metric": metric,
        "days": days,
        "count": len(points),
        "points": points,
    }


# --------------------------------------------------------------------------
# /v1/scores/movers
# --------------------------------------------------------------------------

@router.get("/movers")
async def movers(
    window: str = Query("24h", regex="^(1h|6h|24h|7d|30d)$"),
    direction: str = Query("both", regex="^(up|down|both)$"),
    dimension: str = Query("yieldo_score", regex=r"^(yieldo_score|capital_score|performance_score|risk_score|trust_score)$"),
    limit: int = Query(10, ge=1, le=100),
):
    """Biggest score movers in window — perfect for socials content.

    Compares each vault's current score to its score at the start of the window
    and ranks by absolute delta (signed if direction is up/down).
    """
    db = _get_db()
    hours = {"1h": 1, "6h": 6, "24h": 24, "7d": 24 * 7, "30d": 24 * 30}[window]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    pipeline = [
        {"$match": {"ts": {"$gte": cutoff}}},
        {"$sort": {"vault_id": 1, "ts": 1}},
        {"$group": {
            "_id": "$vault_id",
            "name":     {"$last": "$name"},
            "source":   {"$last": "$source"},
            "chain_id": {"$last": "$chain_id"},
            "asset":    {"$last": "$asset"},
            "first":    {"$first": f"${dimension}"},
            "last":     {"$last":  f"${dimension}"},
            "first_ts": {"$first": "$ts"},
            "last_ts":  {"$last": "$ts"},
            "first_tvl":{"$first": "$metrics.C01_USD"},
            "last_tvl": {"$last":  "$metrics.C01_USD"},
        }},
        {"$match": {"first": {"$ne": None}, "last": {"$ne": None}}},
        {"$project": {
            "_id": 0,
            "vault_id": "$_id",
            "name": 1, "source": 1, "chain_id": 1, "asset": 1,
            "before": "$first", "after": "$last",
            "before_ts": "$first_ts", "after_ts": "$last_ts",
            "delta": {"$subtract": ["$last", "$first"]},
            "tvl_before": "$first_tvl", "tvl_after": "$last_tvl",
        }},
    ]
    rows = await db["score_snapshots"].aggregate(pipeline).to_list(length=None)

    if direction == "up":
        rows = [r for r in rows if (r.get("delta") or 0) > 0]
        rows.sort(key=lambda r: -(r.get("delta") or 0))
    elif direction == "down":
        rows = [r for r in rows if (r.get("delta") or 0) < 0]
        rows.sort(key=lambda r: (r.get("delta") or 0))
    else:
        rows.sort(key=lambda r: -abs(r.get("delta") or 0))

    rows = rows[:limit]
    for r in rows:
        for k in ("before_ts", "after_ts"):
            if isinstance(r.get(k), datetime):
                r[k] = r[k].isoformat()
        # Round for cleaner output
        if isinstance(r.get("delta"), (int, float)):
            r["delta"] = round(r["delta"], 2)
        if isinstance(r.get("before"), (int, float)):
            r["before"] = round(r["before"], 2)
        if isinstance(r.get("after"), (int, float)):
            r["after"] = round(r["after"], 2)

    return {
        "window": window,
        "dimension": dimension,
        "direction": direction,
        "count": len(rows),
        "movers": rows,
    }


# --------------------------------------------------------------------------
# /v1/scores/anomalies
# --------------------------------------------------------------------------

@router.get("/anomalies")
async def anomalies(
    window: str = Query("24h", regex="^(1h|6h|24h|7d|30d)$"),
    severity: Optional[str] = Query(None, regex="^(critical|warning|info)$"),
    vault_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Detected anomalies — for the alerts feed and socials content."""
    db = _get_db()
    hours = {"1h": 1, "6h": 6, "24h": 24, "7d": 24 * 7, "30d": 24 * 30}[window]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    q: dict = {"ts": {"$gte": cutoff}}
    if severity:
        q["severity"] = severity
    if vault_id:
        q["vault_id"] = vault_id

    cursor = db["score_anomalies"].find(q, {"_id": 0}).sort("ts", -1).limit(limit)
    rows = await cursor.to_list(length=limit)
    for r in rows:
        if isinstance(r.get("ts"), datetime):
            r["ts"] = r["ts"].isoformat()

    return {
        "window": window,
        "severity": severity,
        "count": len(rows),
        "anomalies": rows,
    }


# --------------------------------------------------------------------------
# /v1/scores/leaderboard
# --------------------------------------------------------------------------

@router.get("/leaderboard")
async def leaderboard(
    dimension: str = Query("yieldo_score", regex=r"^(yieldo_score|capital_score|performance_score|risk_score|trust_score)$"),
    limit: int = Query(20, ge=1, le=200),
    asset: Optional[str] = None,
    chain_id: Optional[int] = None,
    source: Optional[str] = None,
):
    """Current ranking — latest snapshot per vault, sorted by the chosen dimension."""
    db = _get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)  # last 2h = "current"

    pipeline = [
        {"$match": {"ts": {"$gte": cutoff}}},
        {"$sort": {"vault_id": 1, "ts": -1}},
        {"$group": {
            "_id": "$vault_id",
            "name":     {"$first": "$name"},
            "source":   {"$first": "$source"},
            "chain_id": {"$first": "$chain_id"},
            "asset":    {"$first": "$asset"},
            "score":    {"$first": f"${dimension}"},
            "yieldo":   {"$first": "$yieldo_score"},
            "tvl":      {"$first": "$metrics.C01_USD"},
            "apy":      {"$first": "$metrics.net_apy"},
            "ts":       {"$first": "$ts"},
        }},
        {"$match": {"score": {"$ne": None}}},
    ]
    rows = await db["score_snapshots"].aggregate(pipeline).to_list(length=None)

    # Apply optional filters
    if asset:
        rows = [r for r in rows if (r.get("asset") or "").lower() == asset.lower()]
    if chain_id:
        rows = [r for r in rows if r.get("chain_id") == chain_id]
    if source:
        rows = [r for r in rows if r.get("source") == source]

    rows.sort(key=lambda r: -(r.get("score") or 0))
    rows = rows[:limit]
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["vault_id"] = r.pop("_id")
        if isinstance(r.get("ts"), datetime):
            r["ts"] = r["ts"].isoformat()
        if isinstance(r.get("score"), (int, float)):
            r["score"] = round(r["score"], 2)

    return {
        "dimension": dimension,
        "filters": {"asset": asset, "chain_id": chain_id, "source": source},
        "count": len(rows),
        "leaderboard": rows,
    }


# --------------------------------------------------------------------------
# /v1/scores/compare
# --------------------------------------------------------------------------

@router.get("/compare")
async def compare(
    vault_ids: str = Query(..., description="Comma-separated vault_ids"),
    days: int = Query(30, ge=1, le=365),
    dimension: str = Query("yieldo_score", regex=r"^(yieldo_score|capital_score|performance_score|risk_score|trust_score)$"),
):
    """Compare 2-5 vaults on the same metric over the same time window — for overlay charts."""
    ids = [v.strip() for v in vault_ids.split(",") if v.strip()]
    if not 2 <= len(ids) <= 5:
        raise HTTPException(status_code=400, detail="Provide 2-5 vault_ids")

    db = _get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    series: list[dict] = []
    for vid in ids:
        cursor = db["score_snapshots"].find(
            {"vault_id": vid, "ts": {"$gte": cutoff}},
            {"ts": 1, dimension: 1, "name": 1, "_id": 0},
        ).sort("ts", 1)
        rows = await cursor.to_list(length=None)
        if not rows:
            continue
        name = rows[0].get("name") or vid
        series.append({
            "vault_id": vid,
            "name": name,
            "points": [
                {"x": (r["ts"].isoformat() if isinstance(r["ts"], datetime) else r["ts"]),
                 "y": r.get(dimension)}
                for r in rows if r.get(dimension) is not None
            ],
        })

    return {"dimension": dimension, "days": days, "series": series}
