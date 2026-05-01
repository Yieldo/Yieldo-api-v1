"""Intel page endpoints — serves the Yieldo Intel page.

Reads from the indexer's `signals` collection (written by indexer-v1
src/intel.py). Each signal is a fully-formed record with the shape the
frontend expects, so endpoints are thin formatters.

Tiers:
  HIGH    → /v1/intel/high       — hero "What matters today" cards
  MEDIUM  → /v1/intel/notable    — feed rows ("Notable signals")
  LOW     → /v1/intel/activity   — firehose ("All activity")

Filters: dimension (Capital/Performance/Risk/Trust), time window (24h / 7d / 30d).

Plus:
  /v1/intel/rules    — public rule registry for the methodology / docs page
  /v1/intel/feed     — optional combined feed (all tiers in one call)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.services import database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/intel", tags=["intel"])


# --------------------------------------------------------------------------
# Public rule registry — keep in sync with indexer-v1/src/intel.py
# --------------------------------------------------------------------------

RULES: dict[str, dict[str, Any]] = {
    "R-001": {"name": "Top-50 vault: dimension drop ≥20pts/24h",        "tier": "MEDIUM", "channels": ["intel", "telegram"]},
    "R-002": {"name": "Top-50 vault: TVL ≥20%/24h paired with score change", "tier": "MEDIUM", "channels": ["intel", "telegram"]},
    "R-003": {"name": "New vault scores ≥80 at indexing",               "tier": "MEDIUM", "channels": ["intel", "telegram"]},
    "R-004": {"name": "Vault drops from ≥80 to <60",                    "tier": "MEDIUM", "channels": ["intel", "telegram"]},
    "R-005": {"name": "Established vault breaches credibility floor",   "tier": "MEDIUM", "channels": ["intel", "telegram"]},
    "R-006": {"name": "Risk subscore drop ≥25pts/24h (TVL override)",   "tier": "MEDIUM", "channels": ["intel", "telegram"]},
    "R-007": {"name": "Underlying stablecoin depeg",                    "tier": "MEDIUM", "channels": ["intel", "telegram"]},
    "R-008": {"name": "Credible vault: Risk red flag",                  "tier": "HIGH",   "channels": ["intel", "telegram", "x_draft"]},
    "R-009": {"name": "Composite score drop ≥30pts/24h on ≥$25M",       "tier": "HIGH",   "channels": ["intel", "telegram", "x_draft"]},
    "R-010": {"name": "Composite score drop ≥40pts/24h (any TVL)",      "tier": "HIGH",   "channels": ["intel", "telegram", "x_draft"]},
    "R-011": {"name": "APY anomaly: realized vs advertised divergence", "tier": "MEDIUM", "channels": ["intel", "telegram"]},
    "R-012": {"name": "Curator-aggregate downgrades",                   "tier": "MEDIUM", "channels": ["intel", "telegram"]},
    "R-013": {"name": "Cross-vault contagion",                          "tier": "HIGH",   "channels": ["intel", "telegram", "x_draft"]},
    "R-014": {"name": "Real solvency / liquidity event",                "tier": "HIGH",   "channels": ["intel", "telegram", "x_draft"]},
    "R-015": {"name": "Top-N curator vault event",                      "tier": "HIGH",   "channels": ["intel", "telegram", "x_draft"]},
    "R-100": {"name": "Score change ≥10pts in any dimension",           "tier": "LOW",    "channels": ["intel"]},
    "R-101": {"name": "New vault indexed",                              "tier": "LOW",    "channels": ["intel"]},
    "R-102": {"name": "Weekly movers",                                  "tier": "LOW",    "channels": ["intel"]},
    "R-103": {"name": "Curator activity",                               "tier": "LOW",    "channels": ["intel"]},
}

DIMENSIONS = ("capital_score", "performance_score", "risk_score", "trust_score")
DIMENSION_LABELS = {
    "All signals": None,
    "Capital":     "capital_score",
    "Performance": "performance_score",
    "Risk":        "risk_score",
    "Trust":       "trust_score",
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _require_indexer_db():
    db = database.get_indexer_db()
    if db is None:
        raise HTTPException(503, "Indexer DB not connected")
    return db


def _parse_since(since: str) -> timedelta:
    """Accept '24h', '7d', '30d', '1h', etc. Default 24h."""
    s = (since or "24h").strip().lower()
    try:
        if s.endswith("h"):
            return timedelta(hours=int(s[:-1]))
        if s.endswith("d"):
            return timedelta(days=int(s[:-1]))
        if s.endswith("m"):
            return timedelta(minutes=int(s[:-1]))
    except ValueError:
        pass
    return timedelta(hours=24)


def _humanize_time_ago(ts: datetime, now: datetime | None = None) -> str:
    """'2h ago', '3d ago', etc. ts can be naive (treat as UTC) or aware."""
    if not isinstance(ts, datetime):
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    diff = now - ts
    secs = int(diff.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 14:
        return f"{days}d ago"
    return ts.strftime("%d %b %Y")


def _to_high_signal(doc: dict, now: datetime) -> dict:
    """Format a HIGH-tier signal to match the JSX HighSignalCard shape."""
    return {
        "id":              doc.get("rule_id"),
        "signalId":        doc.get("_id"),
        "label":           doc.get("label") or doc.get("rule_name"),
        "tag":             doc.get("tag"),
        "timeAgo":         _humanize_time_ago(doc.get("ts"), now),
        "ts":              _iso(doc.get("ts")),
        "vaultId":         doc.get("vault_id"),
        "vaultName":       doc.get("vault_name"),
        "chainId":         doc.get("chain_id"),
        "chainName":       doc.get("chain_name"),
        "asset":           (doc.get("asset") or "").upper(),
        "source":          doc.get("source"),
        "headline":        doc.get("headline"),
        "summary":         doc.get("summary"),
        "metrics":         _normalize_metrics(doc.get("metrics") or []),
        "affected":        doc.get("affected_vaults") or [],
        "primaryCta":      doc.get("primary_cta") or "View vault",
        "secondaryCta":    doc.get("secondary_cta"),
        "xDraft":          doc.get("x_draft"),
        "tier":            doc.get("tier"),
    }


def _to_notable_signal(doc: dict, now: datetime) -> dict:
    """Format a MEDIUM-tier signal to match the JSX NotableSignalRow shape."""
    return {
        "id":         doc.get("rule_id"),
        "signalId":   doc.get("_id"),
        "tag":        doc.get("tag") or doc.get("rule_id"),
        "title":      doc.get("headline"),
        "desc":       doc.get("summary") or "",
        "timeAgo":    _humanize_time_ago(doc.get("ts"), now),
        "ts":         _iso(doc.get("ts")),
        "vaultId":    doc.get("vault_id"),
        "vaultName":  doc.get("vault_name"),
        "chainName":  doc.get("chain_name"),
        "asset":      (doc.get("asset") or "").upper(),
        "tier":       doc.get("tier"),
    }


def _to_activity_row(doc: dict, now: datetime) -> dict:
    """Format a LOW-tier signal to match the JSX ActivityRow shape."""
    return {
        "id":         doc.get("rule_id"),
        "signalId":   doc.get("_id"),
        "time":       _humanize_time_ago(doc.get("ts"), now),
        "ts":         _iso(doc.get("ts")),
        "desc":       doc.get("headline"),
        "delta":      doc.get("delta_display") or "—",
        "score":      doc.get("score_display"),
        "tone":       doc.get("tone") or "neutral",
        "vaultId":    doc.get("vault_id"),
        "vaultName":  doc.get("vault_name"),
        "tier":       doc.get("tier"),
    }


def _normalize_metrics(items: list[dict]) -> list[dict]:
    """Turn snake_case keys into camelCase for the React UI."""
    out = []
    for m in items or []:
        if not isinstance(m, dict):
            continue
        out.append({
            "label":     m.get("label"),
            "value":     m.get("value"),
            "delta":     m.get("delta"),
            "deltaTone": m.get("deltaTone") or m.get("delta_tone"),
            "isText":    m.get("isText") or m.get("is_text") or False,
        })
    return out


def _iso(dt: Any) -> Optional[str]:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _dimension_filter_query(dimension: Optional[str]) -> dict:
    """Build a Mongo filter for dimension-scoped signals.

    Matches signals whose `rule_data.dimension` equals the dim score key,
    OR whose rule_id is dimension-agnostic (we don't filter those out).
    """
    if not dimension or dimension == "All signals":
        return {}
    key = DIMENSION_LABELS.get(dimension)
    if not key:
        return {}
    # Match signals that explicitly carry this dimension OR rules where the
    # dimension is in the rule_data
    return {"rule_data.dimension": key}


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

@router.get("/high")
async def list_high(
    since: str = Query("24h", description="Time window: '24h', '7d', '30d'"),
    dimension: Optional[str] = Query(None, description="Capital | Performance | Risk | Trust"),
    limit: int = Query(20, ge=1, le=100),
):
    """HIGH-tier signals — hero 'What matters today' cards."""
    db = _require_indexer_db()
    now = datetime.now(timezone.utc)
    cutoff = (now - _parse_since(since)).replace(tzinfo=None)
    q: dict[str, Any] = {"tier": "HIGH", "ts": {"$gte": cutoff}}
    q.update(_dimension_filter_query(dimension))
    docs = await db.signals.find(q).sort("ts", -1).limit(limit).to_list(length=limit)
    return {
        "signals": [_to_high_signal(d, now) for d in docs],
        "count": len(docs),
        "since": since,
        "dimension": dimension,
    }


@router.get("/notable")
async def list_notable(
    since: str = Query("24h"),
    dimension: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """MEDIUM-tier signals — 'Notable signals' feed rows."""
    db = _require_indexer_db()
    now = datetime.now(timezone.utc)
    cutoff = (now - _parse_since(since)).replace(tzinfo=None)
    q: dict[str, Any] = {"tier": "MEDIUM", "ts": {"$gte": cutoff}}
    q.update(_dimension_filter_query(dimension))
    cursor = db.signals.find(q).sort("ts", -1).skip(offset).limit(limit)
    docs = await cursor.to_list(length=limit)
    total = await db.signals.count_documents(q)
    return {
        "signals": [_to_notable_signal(d, now) for d in docs],
        "count":   len(docs),
        "total":   total,
        "since":   since,
        "dimension": dimension,
        "offset": offset,
        "limit":  limit,
    }


@router.get("/activity")
async def list_activity(
    since: str = Query("24h"),
    dimension: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """LOW-tier signals — 'All activity' firehose."""
    db = _require_indexer_db()
    now = datetime.now(timezone.utc)
    cutoff = (now - _parse_since(since)).replace(tzinfo=None)
    q: dict[str, Any] = {"tier": "LOW", "ts": {"$gte": cutoff}}
    q.update(_dimension_filter_query(dimension))
    cursor = db.signals.find(q).sort("ts", -1).skip(offset).limit(limit)
    docs = await cursor.to_list(length=limit)
    total = await db.signals.count_documents(q)
    return {
        "activity": [_to_activity_row(d, now) for d in docs],
        "count":    len(docs),
        "total":    total,
        "since":    since,
        "dimension": dimension,
        "offset":   offset,
        "limit":    limit,
    }


@router.get("/feed")
async def list_feed(
    since: str = Query("24h"),
    dimension: Optional[str] = Query(None),
    high_limit: int = Query(10, ge=1, le=50, alias="highLimit"),
    notable_limit: int = Query(15, ge=1, le=100, alias="notableLimit"),
    activity_limit: int = Query(50, ge=1, le=500, alias="activityLimit"),
):
    """One-shot feed — returns all three tiers in a single call. Convenience for
    the Intel page so it doesn't need three round-trips."""
    db = _require_indexer_db()
    now = datetime.now(timezone.utc)
    cutoff = (now - _parse_since(since)).replace(tzinfo=None)
    base = {"ts": {"$gte": cutoff}}
    base.update(_dimension_filter_query(dimension))

    high_q     = {**base, "tier": "HIGH"}
    notable_q  = {**base, "tier": "MEDIUM"}
    activity_q = {**base, "tier": "LOW"}

    high_docs    = await db.signals.find(high_q).sort("ts", -1).limit(high_limit).to_list(length=high_limit)
    notable_docs = await db.signals.find(notable_q).sort("ts", -1).limit(notable_limit).to_list(length=notable_limit)
    activity_docs = await db.signals.find(activity_q).sort("ts", -1).limit(activity_limit).to_list(length=activity_limit)
    activity_total = await db.signals.count_documents(activity_q)
    notable_total  = await db.signals.count_documents(notable_q)

    # Engine pulse: vault count & last cycle time, for the live header indicator
    vaults_count = await db.vaults.count_documents({})
    last_cycle = await db.cycle_state.find_one({"_id": "current"})
    last_finished = last_cycle.get("finished_at") if last_cycle else None
    last_cycle_iso = _iso(last_finished) if last_finished else None
    if last_finished:
        if isinstance(last_finished, datetime) and last_finished.tzinfo is None:
            last_finished = last_finished.replace(tzinfo=timezone.utc)
        engine_age_seconds = (now - last_finished).total_seconds() if isinstance(last_finished, datetime) else None
    else:
        engine_age_seconds = None

    return {
        "high":     [_to_high_signal(d, now) for d in high_docs],
        "notable":  [_to_notable_signal(d, now) for d in notable_docs],
        "activity": [_to_activity_row(d, now) for d in activity_docs],
        "totals": {
            "high":     len(high_docs),
            "notable":  notable_total,
            "activity": activity_total,
        },
        "engine": {
            "vaults":          vaults_count,
            "lastCycleIso":    last_cycle_iso,
            "lastCycleAgo":    _humanize_time_ago(last_finished, now) if last_finished else None,
            "lastCycleAgeSec": engine_age_seconds,
        },
        "since":     since,
        "dimension": dimension,
        "now":       _iso(now),
    }


@router.get("/rules")
async def list_rules():
    """Public alert-rule registry. Drives the Methodology page and supports
    /R-### permalinks for verifiability ('this fired because of rule R-008')."""
    return {
        "rules": [
            {
                "id":        rule_id,
                "name":      r["name"],
                "tier":      r["tier"],
                "channels":  r["channels"],
            }
            for rule_id, r in sorted(RULES.items())
        ],
        "version": "v1.0",
        "tiers": {
            "HIGH":   {"channels": ["intel", "telegram", "x_draft"], "approval": "x = human-approved; intel/tg autonomous"},
            "MEDIUM": {"channels": ["intel", "telegram"],            "approval": "autonomous, weekly audit"},
            "LOW":    {"channels": ["intel"],                        "approval": "fully autonomous"},
        },
    }


@router.get("/signal/{signal_id:path}")
async def get_signal(signal_id: str):
    """Permalink to a single signal — used for /R-008/<vault> deep-links from
    HIGH cards or X posts."""
    db = _require_indexer_db()
    doc = await db.signals.find_one({"_id": signal_id})
    if not doc:
        raise HTTPException(404, f"signal {signal_id} not found")
    now = datetime.now(timezone.utc)
    tier = doc.get("tier")
    if tier == "HIGH":
        return _to_high_signal(doc, now)
    if tier == "MEDIUM":
        return _to_notable_signal(doc, now)
    return _to_activity_row(doc, now)
