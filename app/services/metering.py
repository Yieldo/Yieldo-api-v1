"""Backend RPC call metering + paid-RPC budget guard.

Mirrors the indexer's metering: every RPC call (Tatum or public) is counted in
memory and flushed to the shared `rpc_metrics` collection in the indexer DB
(yieldo_v1), so one CLI report (`indexer-v1/scripts/rpc_usage.py`) shows usage
across BOTH services, by chain and provider.

The backend's reads are the urgent user path (deposit/withdraw/quote), so its
budget tier is P0 — it keeps using Tatum until the monthly cap is nearly full.
`record()` is sync (called from the web3 provider); `flush()`/`refresh_budget()`
run on a background loop started in main.py.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SERVICE = "backend"
MONTHLY_CAP = int(os.environ.get("TATUM_MONTHLY_CREDIT_CAP", "4000000"))

_buf: dict = defaultdict(lambda: {"count": 0, "credits": 0})
_mtd_tatum_credits = 0
_budget_loaded = False


def _credit_weight(method: str) -> int:
    m = method or ""
    if m.startswith("debug_") or "trace" in m:
        return 50
    if m == "eth_call":
        return 5
    return 2


def record(chain_id: int, method: str, provider: str) -> None:
    hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    e = _buf[(hour, chain_id, method, provider)]
    e["count"] += 1
    e["credits"] += _credit_weight(method)


def _metrics_db():
    # Write to the indexer DB so all services share one rpc_metrics collection.
    from app.services import database
    return getattr(database, "_indexer_db", None) or getattr(database, "_db", None)


async def flush() -> None:
    if not _buf:
        return
    snapshot = list(_buf.items())
    _buf.clear()
    db = _metrics_db()
    if db is None:
        return
    try:
        from pymongo import UpdateOne
        ops = []
        for (hour, chain_id, method, provider), v in snapshot:
            ops.append(UpdateOne(
                {"hour": hour, "service": SERVICE, "chain_id": chain_id,
                 "method": method, "provider": provider},
                {"$inc": {"count": v["count"], "credits": v["credits"]}},
                upsert=True,
            ))
        if ops:
            await db["rpc_metrics"].bulk_write(ops, ordered=False)
    except Exception as e:
        logger.warning(f"[Metering] flush failed: {e}")


async def refresh_budget() -> None:
    global _mtd_tatum_credits, _budget_loaded
    db = _metrics_db()
    if db is None:
        return
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        cur = db["rpc_metrics"].aggregate([
            {"$match": {"provider": "tatum", "hour": {"$regex": f"^{month}"}}},
            {"$group": {"_id": None, "credits": {"$sum": "$credits"}}},
        ])
        rows = await cur.to_list(length=1)
        _mtd_tatum_credits = int(rows[0]["credits"]) if rows else 0
        _budget_loaded = True
    except Exception as e:
        logger.warning(f"[Metering] budget refresh failed: {e}")


def tatum_allowed(priority: str = "P0") -> bool:
    if not _budget_loaded:
        return True
    frac = _mtd_tatum_credits / MONTHLY_CAP if MONTHLY_CAP else 0
    if priority == "P0":
        return frac < 0.98
    if priority == "P2":
        return frac < 0.70
    return frac < 0.90


async def run_loop(interval_sec: int = 60) -> None:
    logger.info("metering: flush loop started")
    while True:
        try:
            await flush()
            await refresh_budget()
        except Exception as e:
            logger.warning(f"[Metering] loop tick failed: {e}")
        await asyncio.sleep(interval_sec)
