"""Server-side background resolver for pending deposit transactions.

Loops every RESOLVER_INTERVAL_SEC and converges every pending/submitted
transaction to its real terminal status, regardless of whether any frontend
is currently polling /v1/status. This is the single source of truth for
HistoryPage state — without it, a user who closes the tab between sending
and confirmation sees "Pending" forever.

For each pending/submitted record:
  - tx_hash + same-chain: read source-chain receipt -> completed/failed
  - tx_hash + cross-chain: query LiFi -> completed/failed/partial,
    fall back to source receipt (>24h old) for stale records
  - no tx_hash: mark abandoned after ABANDON_HOURS

Idempotent: re-running on a record that's already terminal is a no-op
because update_one's $set/$push only fires on the matched pending state.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from app.core.constants import CHAIN_CONFIG, DEPOSIT_ROUTER_ADDRESSES
from app.services import database

logger = logging.getLogger(__name__)

# Tunables
RESOLVER_INTERVAL_SEC = int(os.environ.get("RESOLVER_INTERVAL_SEC", "60"))
ABANDON_HOURS = 4
STALE_CROSSCHAIN_HOURS = 24
LIFI_STATUS_URL = "https://li.quest/v1/status"

# Don't try to resolve the moment the tx is broadcast — wait for the first
# block confirmation window so we don't hammer RPCs/LiFi with NOT_FOUND.
MIN_AGE_SEC_BEFORE_RESOLVE = 20


def _rpc_url(chain_id: int) -> str | None:
    """Best RPC URL we have for a chain — env override first, then chain config."""
    env_map = {
        1: "ETHEREUM_RPC_URL", 8453: "BASE_RPC_URL", 42161: "ARBITRUM_RPC_URL",
        10: "OPTIMISM_RPC_URL", 43114: "AVALANCHE_RPC_URL", 56: "BSC_RPC_URL",
        999: "HYPEREVM_RPC_URL", 747474: "KATANA_RPC_URL",
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


# ERC-20 Transfer event signature — keccak256("Transfer(address,address,uint256)")
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _verify_share_mint(receipt: dict, share_token: str, user: str) -> bool:
    """Scan receipt logs for a Transfer of `share_token` to `user` with
    non-zero amount. Returns True iff the deposit actually delivered shares.

    Works for any vault type — single source of truth is whether the share
    token's ERC-20 ledger updated for the user. If a swap/bridge succeeded
    but the deposit call reverted silently (composer drop, paused vault,
    etc.), this catches it: there'll be no Transfer event in the receipt."""
    if not share_token or not user:
        return False
    st = share_token.lower()
    user_topic = "0x" + ("000000000000000000000000" + user.lower().lstrip("0x")).rjust(64, "0")[-64:]
    for log in receipt.get("logs") or []:
        try:
            if (log.get("address") or "").lower() != st:
                continue
            topics = log.get("topics") or []
            if len(topics) < 3 or topics[0].lower() != _TRANSFER_TOPIC:
                continue
            if topics[2].lower() != user_topic.lower():
                continue
            amount_hex = log.get("data", "0x0")
            if int(amount_hex, 16) > 0:
                return True
        except Exception:
            continue
    return False


def _share_token_for(doc: dict) -> str | None:
    """Look up the share token for a deposit's vault. Defaults to vault address
    (most ERC-4626 vaults are themselves the share token). Falls back to
    `share_token` override for multi-contract vaults (Lido, Upshift, Mellow)."""
    try:
        from app.services.vault import get_vault
    except Exception:
        return None
    vault = get_vault(doc.get("vault_id") or "")
    if not vault:
        return None
    return vault.get("share_token") or vault.get("address")


async def _lifi_status(client: httpx.AsyncClient, tx_hash: str, from_chain: int, to_chain: int) -> dict | None:
    try:
        r = await client.get(
            LIFI_STATUS_URL,
            params={"txHash": tx_hash, "fromChain": from_chain, "toChain": to_chain},
            timeout=20.0,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _normalise_dt(value) -> datetime | None:
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
    """Return (new_status, extra_fields). new_status is None when we can't yet
    determine the outcome (still in-flight, RPC down, etc) — caller leaves the
    record alone for the next tick."""
    tx_hash = doc.get("tx_hash")
    from_chain = doc.get("from_chain_id")
    to_chain = doc.get("to_chain_id") or from_chain
    created = _normalise_dt(doc.get("created_at"))
    extra: dict = {}

    if not tx_hash:
        if created and created < datetime.now(timezone.utc) - timedelta(hours=ABANDON_HOURS):
            return "abandoned", extra
        return None, extra

    if created and (datetime.now(timezone.utc) - created).total_seconds() < MIN_AGE_SEC_BEFORE_RESOLVE:
        return None, extra

    is_cross = bool(from_chain and to_chain and from_chain != to_chain)

    if is_cross:
        ls = await _lifi_status(client, tx_hash, from_chain, to_chain)
        if ls:
            s = ls.get("status")
            sub = ls.get("substatus")
            rcv = ls.get("receiving") or {}
            if rcv.get("txHash"):
                extra["dest_tx_hash"] = rcv.get("txHash")
                extra["dest_chain_id"] = to_chain
            bridge = ls.get("tool")
            if bridge:
                extra["bridge"] = bridge
            extra["lifi_explorer"] = f"https://explorer.li.fi/tx/{tx_hash}"
            if s == "DONE" and sub == "COMPLETED":
                # LiFi says bridge+composer succeeded. For single-tx (composer)
                # flows, verify the share token actually minted to the user on
                # the dest chain. Catches the "composer call dropped silently
                # on the dest chain" failure mode where LiFi reports DONE but
                # no shares ever arrived. Two-step flows are handled later by
                # mirroring the child record's status — no verification here
                # because the dest tx is just the asset delivery, not the deposit.
                is_two_step = bool((doc.get("response") or {}).get("two_step"))
                if not is_two_step and rcv.get("txHash"):
                    rpc = _rpc_url(to_chain)
                    user = (doc.get("user_address") or "").lower()
                    share_token = _share_token_for(doc)
                    if rpc and user and share_token:
                        dest_receipt = await _rpc_get_receipt(client, rpc, rcv["txHash"])
                        if dest_receipt and not _verify_share_mint(dest_receipt, share_token, user):
                            extra["resolution_note"] = "Bridge+composer DONE per LiFi but no share-mint event on dest — composer call likely dropped"
                            extra["received_token"] = (rcv.get("token") or {}).get("address")
                            extra["received_amount"] = rcv.get("amount")
                            return "partial", extra
                return "completed", extra
            if s == "DONE" and sub in ("PARTIAL", "REFUNDED"):
                extra["received_token"] = (rcv.get("token") or {}).get("address")
                extra["received_amount"] = rcv.get("amount")
                return "partial", extra
            if s == "FAILED":
                return "failed", extra
        # Source-receipt fallback for old cross-chain records LiFi has dropped
        rpc = _rpc_url(from_chain)
        if rpc:
            receipt = await _rpc_get_receipt(client, rpc, tx_hash)
            if receipt:
                if receipt.get("status") == "0x0":
                    return "failed", extra
                if receipt.get("status") == "0x1" and created:
                    age_h = (datetime.now(timezone.utc) - created).total_seconds() / 3600
                    if age_h > STALE_CROSSCHAIN_HOURS:
                        extra["resolution_note"] = "Source confirmed; LiFi data unavailable."
                        return "completed", extra
        return None, extra

    # Same-chain: receipt is authoritative for SINGLE-TX flows. For two-step
    # parents (e.g. Midas/Veda/IPOR/Lido + same-chain swap), the source tx is
    # only the swap — the actual deposit happens in a separate child tx.
    # Marking "completed" on source receipt alone is the bug that made
    # Midas HyperBTC swaps look successful with no real deposit.
    rpc = _rpc_url(from_chain)
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

    # Source confirmed. Two-step parent? Wait for the child deposit.
    is_two_step_parent = (
        bool((doc.get("response") or {}).get("two_step"))
        and not doc.get("parent_tracking_id")
    )
    if not is_two_step_parent:
        # Single-tx flow (direct deposit OR same-chain composer). Receipt
        # status==1 alone isn't enough — the inner deposit call could revert
        # silently (e.g. composer drop, vault rejection). Verify the share
        # token actually minted to the user.
        user = (doc.get("user_address") or "").lower()
        share_token = _share_token_for(doc)
        if user and share_token and not _verify_share_mint(receipt, share_token, user):
            extra["resolution_note"] = (
                "Source tx confirmed but no share-mint event for this user — "
                "swap/bridge succeeded but actual deposit didn't happen"
            )
            return "partial", extra
        return "completed", extra

    # Look up the child by parent_tracking_id and mirror its terminal state.
    db = database._db  # noqa: SLF001
    child = await db["transactions"].find_one(
        {"parent_tracking_id": str(doc["_id"])},
        sort=[("created_at", -1)],
    ) if db is not None else None
    if child:
        cs = child.get("status")
        if cs in ("completed", "failed", "partial"):
            extra["resolution_note"] = f"two-step parent: mirrored child status {cs}"
            return cs, extra
        # Child exists but still pending — keep parent pending too
        return None, extra

    # No child yet. After a grace period assume step-2 was abandoned.
    if created and (datetime.now(timezone.utc) - created).total_seconds() > ABANDON_HOURS * 3600:
        extra["resolution_note"] = "two-step parent: child never created within abandon window"
        return "abandoned", extra
    return None, extra


async def _tick(client: httpx.AsyncClient) -> None:
    db = database._db  # noqa: SLF001 — we own this module
    if db is None:
        return
    cursor = db["transactions"].find({"status": {"$in": ["pending", "submitted"]}})
    n_resolved = 0
    n_left = 0
    async for doc in cursor:
        try:
            new_status, extra = await _resolve_record(client, doc)
        except Exception as e:
            logger.warning(f"resolver: error on {doc.get('_id')}: {e}")
            n_left += 1
            continue
        if not new_status:
            n_left += 1
            continue
        now = datetime.now(timezone.utc)
        update = {
            "$set": {"status": new_status, "updated_at": now, **extra},
            "$push": {"status_history": {"status": new_status, "timestamp": now}},
        }
        # Guard against races with the live /v1/status endpoint — only flip if
        # still pending/submitted, never overwrite a real terminal state.
        await db["transactions"].update_one(
            {"_id": doc["_id"], "status": {"$in": ["pending", "submitted"]}},
            update,
        )
        n_resolved += 1
    if n_resolved:
        logger.info(f"status_resolver tick: resolved={n_resolved} still_pending={n_left}")


async def run_loop() -> None:
    """Run forever; sleep RESOLVER_INTERVAL_SEC between ticks."""
    logger.info(f"status_resolver: starting loop ({RESOLVER_INTERVAL_SEC}s interval)")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await _tick(client)
            except Exception as e:
                logger.warning(f"status_resolver tick failed: {e}")
            await asyncio.sleep(RESOLVER_INTERVAL_SEC)
