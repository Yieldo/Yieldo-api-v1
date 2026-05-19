"""Galxe REST API credential endpoint.

Galxe campaigns can ask "is wallet X eligible for credential Y" by hitting
a public REST endpoint with the wallet address. This route exposes that
check for "did this wallet successfully deposit via Yieldo's DepositRouter"
— the precise definition we can't get from any on-chain read because the
router doesn't expose per-user state.

Backed by the `transactions` collection in the wallets DB, which the
deposit modal writes on every quote/build and the status resolver promotes
to "completed" when the on-chain tx lands. That collection is the source
of truth for "this deposit went through Yieldo end-to-end."

Galxe configuration:
  - Credential type: REST API
  - URL template:    https://api.yieldo.xyz/v1/galxe/eligible?wallet={address}&chain=base
  - JSONPath:        $.eligible           (simple boolean) or
                     $.deposit_count      (numeric, e.g. require >= 1)

Multi-chain campaigns: omit `chain` to count completed deposits across all
chains, or pass a comma-separated list like `chain=base,ethereum`.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services import database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/galxe", tags=["galxe"])


# Map of friendly chain names → chain_id, so campaign URLs can use `chain=base`
# instead of `chain_id=8453`. Add new chains here as Yieldo expands.
_CHAIN_ALIASES: dict[str, int] = {
    "ethereum": 1, "eth": 1, "mainnet": 1,
    "base": 8453,
    "arbitrum": 42161, "arb": 42161,
    "optimism": 10, "op": 10,
    "monad": 143,
    "hyperevm": 999,
    "katana": 747474,
    "gnosis": 100,
}


def _normalize_wallet(wallet: str) -> str:
    """Lowercase + validate basic 0x-prefixed 20-byte hex. Reject anything
    obviously malformed before hitting Mongo so we don't return false
    positives on misformatted input."""
    w = (wallet or "").strip().lower()
    if not w.startswith("0x") or len(w) != 42:
        raise HTTPException(status_code=400, detail="wallet must be a 0x-prefixed 20-byte address")
    try:
        int(w, 16)
    except ValueError:
        raise HTTPException(status_code=400, detail="wallet contains non-hex characters")
    return w


def _resolve_chain_filter(chain: Optional[str]) -> Optional[list[int]]:
    """Parse `chain=base` or `chain=base,ethereum`. Returns None when no
    filter is requested (= count across all chains)."""
    if not chain:
        return None
    parts = [p.strip().lower() for p in chain.split(",") if p.strip()]
    chain_ids: list[int] = []
    for p in parts:
        # Allow raw numeric chain_id (e.g. ?chain=8453) for forward-compat
        # with chains not in the alias map.
        if p.isdigit():
            chain_ids.append(int(p))
            continue
        if p not in _CHAIN_ALIASES:
            raise HTTPException(
                status_code=400,
                detail=f"unknown chain '{p}'; supported: {sorted(_CHAIN_ALIASES.keys())} or numeric chain_id",
            )
        chain_ids.append(_CHAIN_ALIASES[p])
    return chain_ids


@router.get("/eligible")
async def eligible(
    wallet: str = Query(..., description="0x-prefixed wallet address to check"),
    chain: Optional[str] = Query(None, description="Chain name (base, ethereum, ...) or chain_id. Omit for all chains. Comma-separated supported."),
    min_deposits: int = Query(1, ge=1, description="Minimum number of successful Yieldo deposits required to mark eligible."),
):
    """Return whether `wallet` has completed at least `min_deposits` deposits
    via Yieldo's DepositRouter (optionally constrained to one or more chains).

    Galxe-friendly response shape — `eligible` is a top-level boolean for the
    simplest JSONPath expression `$.eligible`; `deposit_count` is exposed
    separately for threshold-based credentials.
    """
    wallet_norm = _normalize_wallet(wallet)
    chain_ids = _resolve_chain_filter(chain)

    db = database.get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Wallets DB not connected")

    # Match the destination chain (where the vault lives), not the source chain
    # of a cross-chain deposit. A user who bridges USDC from Ethereum → Base
    # and deposits into a Base vault should count toward a Base campaign.
    query: dict = {"user_address": wallet_norm, "status": "completed"}
    if chain_ids:
        query["to_chain_id"] = {"$in": chain_ids} if len(chain_ids) > 1 else chain_ids[0]

    deposit_count = await db["transactions"].count_documents(query)
    eligible = deposit_count >= min_deposits

    return {
        "wallet": wallet_norm,
        "chain": chain or "all",
        "chain_ids": chain_ids,
        "deposit_count": deposit_count,
        "min_deposits": min_deposits,
        "eligible": eligible,
    }
