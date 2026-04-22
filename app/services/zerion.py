"""Zerion API integration for fast portfolio reads.

Fetches a wallet's positions across all chains/protocols in a single API call,
including USD values and APY where available. Much faster than batching
balanceOf() RPC calls per vault.

Free plan limits: 2000 requests/day AND 10 requests/second.
- Per-wallet cache (60s TTL) handles daily budget
- Token-bucket rate limiter handles the per-second cap

Docs: https://developers.zerion.io/reference/positions
"""
import asyncio
import base64
import logging
import time
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.zerion.io/v1"

# Zerion chain IDs use string keys (ethereum, base, etc) — map to EVM chain IDs
_ZERION_TO_EVM_CHAIN = {
    "ethereum": 1,
    "base": 8453,
    "arbitrum": 42161,
    "optimism": 10,
    "avalanche": 43114,
    "binance-smart-chain": 56,
    "polygon": 137,
    "katana": 747474,
    # Zerion doesn't support Monad / HyperEVM yet — those fall through to RPC
}

# Per-wallet cache: { address_lower: (fetched_at, data) }
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 60.0  # seconds

# Daily counter for observability
_DAILY_COUNT = {"day": "", "count": 0}

# Token-bucket rate limiter: 10 req/sec
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_PERIOD = 1.0  # seconds
_request_timestamps: list[float] = []
_rate_lock = asyncio.Lock()


async def _acquire_rate_token():
    """Block until a request slot is available (10 per second max)."""
    async with _rate_lock:
        now = time.monotonic()
        # Drop timestamps older than the window
        cutoff = now - _RATE_LIMIT_PERIOD
        while _request_timestamps and _request_timestamps[0] < cutoff:
            _request_timestamps.pop(0)
        if len(_request_timestamps) >= _RATE_LIMIT_MAX:
            # Wait until the oldest one falls outside the window
            wait = _request_timestamps[0] + _RATE_LIMIT_PERIOD - now
            if wait > 0:
                await asyncio.sleep(wait)
        _request_timestamps.append(time.monotonic())


def _auth_header(api_key: str) -> str:
    """Zerion uses HTTP Basic auth with api_key as username, blank password."""
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    return f"Basic {token}"


def _bump_counter():
    import datetime as dt
    today = dt.datetime.utcnow().strftime("%Y-%m-%d")
    if _DAILY_COUNT["day"] != today:
        _DAILY_COUNT["day"] = today
        _DAILY_COUNT["count"] = 0
    _DAILY_COUNT["count"] += 1


def get_daily_usage() -> dict:
    """Expose current day's Zerion call count (for observability)."""
    return {"day": _DAILY_COUNT["day"], "count": _DAILY_COUNT["count"], "limit": 2000}


async def fetch_positions(wallet_address: str) -> Optional[list[dict]]:
    """Fetch all positions for a wallet. Returns None if Zerion is unavailable
    or not configured — caller should fall back to RPC.

    Response is a list of simplified position dicts with keys:
      - chain_id (int)
      - protocol (str) — e.g. "morpho", "aave-v3", "lido"
      - token_address (str lowercase) — the position token / vault address
      - token_symbol (str)
      - quantity (float)      — human-readable token amount
      - value_usd (float)
      - apy (float or None)
      - position_type (str)   — "deposit", "loan", "reward", etc.
    """
    settings = get_settings()
    if not settings.zerion_api_key:
        return None

    addr = wallet_address.lower()
    now = time.time()

    # Cache hit
    cached = _CACHE.get(addr)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1].get("positions")

    try:
        await _acquire_rate_token()
        async with httpx.AsyncClient(timeout=5.0) as client:
            # filter[positions]=only_simple limits to non-wrapped positions
            # filter[position_types]=deposit excludes loans/rewards if you only want deposits
            # filter[trash]=only_non_trash drops airdrops/spam tokens.
            # We post-filter server-side to keep only vault-type positions
            # (anything with an `application_metadata.name` — non-empty protocol attribution).
            res = await client.get(
                f"{_BASE_URL}/wallets/{addr}/positions/",
                params={
                    "filter[trash]": "only_non_trash",
                    "currency": "usd",
                    "page[size]": 100,
                },
                headers={
                    "Authorization": _auth_header(settings.zerion_api_key),
                    "accept": "application/json",
                },
            )
        _bump_counter()
        if res.status_code == 429:
            logger.warning("Zerion rate limited — falling back to RPC")
            return None
        if res.status_code != 200:
            logger.warning(f"Zerion returned {res.status_code}: {res.text[:200]}")
            return None

        data = res.json()
        positions = _normalize(data.get("data", []))
        _CACHE[addr] = (now, {"positions": positions})
        return positions
    except httpx.HTTPError as e:
        logger.warning(f"Zerion request failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected Zerion error: {e}")
        return None


def _normalize(items: list[dict]) -> list[dict]:
    """Reduce Zerion's verbose JSON:API response to a flat list of positions.

    Zerion response shape (observed):
      - item["id"] = "<chain>-<asset_id>" e.g. "base-ethereum-asset-asset" or "ethereum-morpho-<vault>"
      - item["attributes"]["position_type"] = "wallet" | "deposit" | "staked" | ...
      - item["attributes"]["protocol"] = protocol slug when it's a DeFi position
      - item["attributes"]["fungible_info"]["implementations"] = per-chain contract addresses
      - item["attributes"]["application_metadata"]["name"] = protocol display name
    """
    out = []
    for item in items:
        attrs = item.get("attributes", {}) or {}
        item_id = item.get("id", "") or ""

        # Derive chain from id's first segment (most reliable)
        zerion_chain = item_id.split("-", 1)[0] if item_id else ""
        evm_chain_id = _ZERION_TO_EVM_CHAIN.get(zerion_chain)
        if not evm_chain_id:
            continue

        # Token contract address for this chain
        fungible_info = attrs.get("fungible_info", {}) or {}
        implementations = fungible_info.get("implementations", []) or []
        token_address = None
        for impl in implementations:
            if impl.get("chain_id") == zerion_chain:
                addr = impl.get("address")
                if addr:
                    token_address = addr.lower()
                break
        if not token_address:
            continue  # native ETH or missing contract — skip, not a vault

        quantity = (attrs.get("quantity") or {}).get("numeric")
        try:
            quantity = float(quantity) if quantity is not None else 0.0
        except (TypeError, ValueError):
            quantity = 0.0
        if quantity <= 0:
            continue

        # Protocol attribution
        protocol_slug = (attrs.get("protocol") or "").lower()
        app_metadata = attrs.get("application_metadata") or {}
        protocol_name = (app_metadata.get("name") or "").lower()
        position_type = attrs.get("position_type", "wallet")

        # Keep only protocol-attributed positions (yield-bearing). Skip raw token holdings.
        is_protocol_position = bool(protocol_slug or protocol_name) and position_type != "wallet"
        if not is_protocol_position:
            continue

        out.append({
            "chain_id": evm_chain_id,
            "protocol": protocol_slug or protocol_name,
            "token_address": token_address,
            "token_symbol": fungible_info.get("symbol", ""),
            "quantity": quantity,
            "value_usd": float(attrs.get("value") or 0.0),
            "apy": _extract_apy(attrs),
            "position_type": position_type,
        })
    return out


def _extract_apy(attrs: dict) -> Optional[float]:
    """Zerion sometimes exposes APY under application_metadata or flags. Return as fraction (0.045 = 4.5%)."""
    meta = attrs.get("application_metadata") or {}
    # Some positions carry an `apy` field; varies. Be tolerant.
    for key in ("apy", "apr"):
        v = meta.get(key)
        if v is None:
            v = attrs.get(key)
        if v is None:
            continue
        try:
            v = float(v)
            # Normalize — sometimes % (e.g. 4.5), sometimes fraction (0.045)
            return v / 100.0 if v > 1.0 else v
        except (TypeError, ValueError):
            pass
    return None


def match_to_vault(position: dict, vault: dict) -> bool:
    """Does this Zerion position correspond to the given Yieldo vault?"""
    return (
        position.get("chain_id") == vault["chain_id"]
        and position.get("token_address", "").lower() == vault["address"].lower()
    )
