"""Background resolver that converges every pending/submitted withdraw
record to its real terminal status, regardless of frontend polling.

Withdrawals are always SAME-CHAIN (no bridge), so the source receipt is
authoritative. For Midas async (`mode == "async"`), receipt success means
the redemption *request* was accepted — we mark `submitted` and wait for
fulfillment via `claimed` (set by the indexer / mark_withdraw_claimed).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from app.core.constants import CHAIN_CONFIG
from app.services import database

logger = logging.getLogger(__name__)

WITHDRAW_RESOLVER_INTERVAL_SEC = int(os.environ.get("WITHDRAW_RESOLVER_INTERVAL_SEC", "60"))
ABANDON_HOURS = 4
MIN_AGE_SEC_BEFORE_RESOLVE = 20


def _rpc_url(chain_id: int) -> str | None:
    env_map = {
        1: "ETHEREUM_RPC_URL", 8453: "BASE_RPC_URL", 42161: "ARBITRUM_RPC_URL",
        10: "OPTIMISM_RPC_URL", 43114: "AVALANCHE_RPC_URL", 56: "BSC_RPC_URL",
        999: "HYPEREVM_RPC_URL", 747474: "KATANA_RPC_URL", 100: "GNOSIS_RPC_URL",
        143: "MONAD_RPC_URL",
    }
    env_var = env_map.get(chain_id)
    if env_var:
        v = os.environ.get(env_var)
        if v:
            return v
    return (CHAIN_CONFIG.get(chain_id) or {}).get("rpc")


async def _rpc_get_receipt(client: httpx.AsyncClient, rpc: str, tx_hash: str) -> dict | None:
    try:
        r = await client.post(
            rpc,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx_hash]},
            timeout=15.0,
        )
        return (r.json() or {}).get("result")
    except Exception:
        return None


def _normalise_dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


async def _resolve_record(client: httpx.AsyncClient, doc: dict) -> tuple[str | None, dict]:
    tx_hash = doc.get("tx_hash")
    chain_id = doc.get("chain_id")
    created = _normalise_dt(doc.get("created_at"))
    extra: dict = {}

    if not tx_hash:
        if created and created < datetime.now(timezone.utc) - timedelta(hours=ABANDON_HOURS):
            return "abandoned", extra
        return None, extra

    if created and (datetime.now(timezone.utc) - created).total_seconds() < MIN_AGE_SEC_BEFORE_RESOLVE:
        return None, extra

    rpc = _rpc_url(chain_id)
    if not rpc:
        return None, extra
    receipt = await _rpc_get_receipt(client, rpc, tx_hash)
    if not receipt:
        return None, extra
    status = receipt.get("status")
    if status == "0x0":
        return "failed", extra
    if status != "0x1":
        return None, extra

    # Async (Midas redeemRequest): receipt success means the request was
    # accepted on-chain. Final fulfillment is reported by the indexer through
    # mark_withdraw_claimed. Until then, the user's UX state is "submitted".
    if doc.get("mode") == "async":
        return "submitted", extra
    return "completed", extra


async def _tick(client: httpx.AsyncClient) -> None:
    db = database._db  # noqa: SLF001
    if db is None:
        return
    cursor = db["withdrawals"].find({"status": {"$in": ["pending", "submitted"]}})
    n_resolved = 0
    n_left = 0
    async for doc in cursor:
        # Async withdraws that already reached "submitted" don't need re-resolution
        # here — fulfillment moves them to "claimed" via mark_withdraw_claimed.
        if doc.get("mode") == "async" and doc.get("status") == "submitted":
            continue
        try:
            new_status, extra = await _resolve_record(client, doc)
        except Exception as e:
            logger.warning(f"withdraw_resolver: error on {doc.get('_id')}: {e}")
            n_left += 1
            continue
        if not new_status:
            n_left += 1
            continue
        if new_status == doc.get("status"):
            continue
        now = datetime.now(timezone.utc)
        update = {
            "$set": {"status": new_status, "updated_at": now, **extra},
            "$push": {"status_history": {"status": new_status, "timestamp": now}},
        }
        await db["withdrawals"].update_one(
            {"_id": doc["_id"], "status": {"$in": ["pending", "submitted"]}},
            update,
        )
        n_resolved += 1
    if n_resolved:
        logger.info(f"withdraw_resolver tick: resolved={n_resolved} still_pending={n_left}")


async def run_loop() -> None:
    logger.info(f"withdraw_resolver: starting loop ({WITHDRAW_RESOLVER_INTERVAL_SEC}s interval)")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await _tick(client)
            except Exception as e:
                logger.warning(f"withdraw_resolver tick failed: {e}")
            await asyncio.sleep(WITHDRAW_RESOLVER_INTERVAL_SEC)
