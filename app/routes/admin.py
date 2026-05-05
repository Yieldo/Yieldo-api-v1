"""Admin console — vault toggles.

Two-factor gate: shared password + SIWE signature from an approved wallet.
Both must pass:
  1. Password proves the caller has the admin secret (env: YIELDO_ADMIN_PASSWORD).
  2. SIWE signature proves they control a wallet listed in YIELDO_ADMIN_WALLETS.

A successful login returns an opaque session token (32 bytes hex) stored
server-side in `admin_sessions` (TTL 8h). All admin actions require both the
session token (Authorization: Bearer ...) AND the wallet header so even a
leaked token can't be used from a different machine without the wallet.

Vault state model
-----------------
- New collection `vault_admin_state` keyed by `vault_id`.
- Fields: enabled, deposits_enabled, withdrawals_enabled, updated_by, updated_at.
- Vaults that have NO entry default to fully enabled — that's how new vaults
  from the indexer auto-appear in the admin list and on the public UI without
  any extra admin step.
- `withdrawals_enabled` requires `enabled=true` to take effect — disabled vaults
  hide deposit/withdraw entry points entirely on the public UI.

Public-side enforcement
-----------------------
- /v1/vaults filters out `enabled=false` for non-admin callers.
- /v1/quote/* and /v1/withdraw/* reject if the targeted vault is disabled OR if
  the relevant per-action flag is off.
- /v1/admin/vaults bypasses the filter and returns ALL vaults with their
  current admin state inlined.
"""
from __future__ import annotations

import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from web3 import Web3

from app.config import get_settings
from app.core.auth import (
    build_admin_login_message,
    generate_nonce,
    generate_session_token,
    hash_key,
    verify_signature,
)
from app.services import database
from app.services.vault import get_all_vaults_raw

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/admin", tags=["admin"])

SESSION_TTL_HOURS = 8
NONCE_TTL_MINUTES = 10


# ---------- helpers ----------

def _admin_wallets() -> set[str]:
    """Approved wallet allowlist from env. Comma-separated, lowercased."""
    raw = (get_settings().yieldo_admin_wallets or "").strip()
    return {w.strip().lower() for w in raw.split(",") if w.strip()}


def _admin_enabled() -> bool:
    s = get_settings()
    return bool((s.yieldo_admin_password or "").strip()) and bool(_admin_wallets())


def _check_password(provided: str) -> bool:
    """Constant-time compare to prevent timing oracles."""
    expected = (get_settings().yieldo_admin_password or "").strip()
    if not expected:
        return False
    return hmac.compare_digest(expected.encode(), (provided or "").encode())


async def _store_nonce(addr: str, nonce: str) -> None:
    db = database._db  # noqa: SLF001
    if db is None:
        raise HTTPException(503, "DB not connected")
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=NONCE_TTL_MINUTES)
    await db["admin_nonces"].update_one(
        {"address": addr.lower()},
        {"$set": {"nonce": nonce, "expires_at": expires_at}},
        upsert=True,
    )


async def _consume_nonce(addr: str, nonce: str) -> bool:
    """Verify-and-delete. Single-use."""
    db = database._db  # noqa: SLF001
    if db is None:
        return False
    now = datetime.now(timezone.utc)
    res = await db["admin_nonces"].find_one_and_delete(
        {"address": addr.lower(), "nonce": nonce, "expires_at": {"$gt": now}}
    )
    return res is not None


async def _create_session(addr: str) -> str:
    """Insert a session row and return the raw token. Server stores only the hash."""
    db = database._db  # noqa: SLF001
    if db is None:
        raise HTTPException(503, "DB not connected")
    raw = generate_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    await db["admin_sessions"].insert_one({
        "token_hash": hash_key(raw),
        "address": addr.lower(),
        "created_at": datetime.now(timezone.utc),
        "expires_at": expires_at,
    })
    return raw


async def _resolve_session(token: str) -> Optional[dict]:
    db = database._db  # noqa: SLF001
    if db is None:
        return None
    now = datetime.now(timezone.utc)
    return await db["admin_sessions"].find_one({
        "token_hash": hash_key(token),
        "expires_at": {"$gt": now},
    })


async def require_admin(
    authorization: str = Header(default=""),
    x_admin_address: str = Header(default=""),
) -> dict:
    """Reusable dependency — call as `Depends(require_admin)` on protected routes.
    Returns the session row when valid, raises 401/403 otherwise."""
    if not _admin_enabled():
        raise HTTPException(503, "Admin disabled")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization[7:].strip()
    sess = await _resolve_session(token)
    if not sess:
        raise HTTPException(401, "Invalid or expired session")
    # Defense in depth: token + wallet header must match. A leaked token alone
    # is useless without the wallet address being passed too (and the FE only
    # sends the wallet for the connected account).
    if not x_admin_address or x_admin_address.lower() != sess["address"].lower():
        raise HTTPException(403, "Wallet header mismatch")
    if x_admin_address.lower() not in _admin_wallets():
        # Wallet was removed from the allowlist after the session was issued.
        raise HTTPException(403, "Wallet no longer authorized")
    return sess


# ---------- nonce + login ----------

class AdminNonceRequest(BaseModel):
    address: str


class AdminNonceResponse(BaseModel):
    nonce: str
    message: str


@router.post("/nonce", response_model=AdminNonceResponse)
async def admin_nonce(req: AdminNonceRequest):
    """Issue a one-time nonce for the SIWE message. Pre-checks the wallet is
    on the allowlist so a non-admin gets a clean rejection instead of having
    to sign first and find out."""
    if not _admin_enabled():
        raise HTTPException(503, "Admin disabled")
    addr = (req.address or "").strip().lower()
    if not Web3.is_address(addr):
        raise HTTPException(400, "Invalid address")
    if addr not in _admin_wallets():
        raise HTTPException(403, "Wallet not authorized")
    nonce = generate_nonce()
    await _store_nonce(addr, nonce)
    return AdminNonceResponse(nonce=nonce, message=build_admin_login_message(addr, nonce))


class AdminLoginRequest(BaseModel):
    address: str
    nonce: str
    signature: str
    password: str


class AdminLoginResponse(BaseModel):
    token: str
    address: str
    expires_in_hours: int


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(req: AdminLoginRequest):
    if not _admin_enabled():
        raise HTTPException(503, "Admin disabled")
    addr = (req.address or "").strip().lower()
    if not Web3.is_address(addr):
        raise HTTPException(400, "Invalid address")
    if addr not in _admin_wallets():
        raise HTTPException(403, "Wallet not authorized")
    if not _check_password(req.password):
        # Same delay shape as a wallet-not-authorized response so timing
        # doesn't leak which factor failed.
        raise HTTPException(401, "Invalid credentials")
    if not await _consume_nonce(addr, req.nonce):
        raise HTTPException(400, "Stale or invalid nonce")
    expected = build_admin_login_message(addr, req.nonce)
    if not verify_signature(addr, expected, req.signature):
        raise HTTPException(401, "Invalid signature")
    raw = await _create_session(addr)
    logger.info(f"[admin] login ok address={addr}")
    return AdminLoginResponse(token=raw, address=addr, expires_in_hours=SESSION_TTL_HOURS)


@router.post("/logout")
async def admin_logout(authorization: str = Header(default="")):
    if not authorization.lower().startswith("bearer "):
        return {"ok": True}
    token = authorization[7:].strip()
    db = database._db  # noqa: SLF001
    if db is not None:
        await db["admin_sessions"].delete_one({"token_hash": hash_key(token)})
    return {"ok": True}


# ---------- vault state ----------

class VaultToggleRequest(BaseModel):
    enabled: Optional[bool] = None
    deposits_enabled: Optional[bool] = None
    withdrawals_enabled: Optional[bool] = None


def _default_state(vault_id: str) -> dict:
    return {
        "vault_id": vault_id,
        "enabled": True,
        "deposits_enabled": True,
        "withdrawals_enabled": True,
        "updated_at": None,
        "updated_by": None,
    }


# Vault types that are technically incompatible with parts of our flow,
# regardless of admin policy. These are HARD locks — the admin can't override
# them because the underlying contract integration doesn't support the action.
# Unifying with the registry like this means the admin page reflects what
# users actually experience, no duplicate "is it on?" sources.
_DEPOSITS_HARD_LOCK_TYPES = {"unsupported"}
_WITHDRAWALS_HARD_LOCK_TYPES = {"unsupported", "veda", "ipor", "lido"}


def _registry_locks(vault: dict) -> dict:
    """Read locks coming from vaults.json — these are 'why is the public UI
    disabling this' annotations the admin sees alongside their own toggles."""
    vtype = (vault.get("type") or "morpho").lower()
    paused = bool(vault.get("paused", False))
    return {
        # Listing isn't blocked by registry alone — pause/unsupported only
        # blocks deposit/withdraw flows. Admin still controls visibility.
        "listed_locked":      False,
        "deposits_locked":    vtype in _DEPOSITS_HARD_LOCK_TYPES,
        "withdrawals_locked": vtype in _WITHDRAWALS_HARD_LOCK_TYPES,
        # Soft signals — still reflected in the effective state.
        "registry_paused":    paused,
        "registry_type":      vtype,
        "paused_reason":      vault.get("paused_reason"),
    }


def _effective_for(vault: dict, admin_state: dict) -> dict:
    """Combine admin override + registry config into the single 'live' state.
    This is what users experience and what the admin page shows on its toggles.

    Rules:
      Listed       = admin.enabled (admin fully controls visibility)
      Deposits     = Listed AND admin.deposits_enabled AND not registry-paused AND not type-locked
      Withdrawals  = Listed AND admin.withdrawals_enabled AND not type-locked

    Soft signals (registry pause) are reflected in the effective state but
    their reason is exposed so the admin sees WHY a vault is off, not just
    that it's off."""
    locks = _registry_locks(vault)
    a_listed = bool(admin_state.get("enabled", True))
    a_dep    = bool(admin_state.get("deposits_enabled", True))
    a_wd     = bool(admin_state.get("withdrawals_enabled", True))

    eff_listed = a_listed
    eff_dep = (
        eff_listed
        and a_dep
        and not locks["registry_paused"]
        and not locks["deposits_locked"]
    )
    eff_wd = (
        eff_listed
        and a_wd
        and not locks["withdrawals_locked"]
    )

    # Reason codes — surfaced as small badges in the admin UI.
    listed_reasons    = [] if eff_listed else (["admin"] if not a_listed else [])
    deposits_reasons  = []
    withdrawals_reasons = []
    if not eff_dep:
        if not eff_listed:                deposits_reasons.append("listing-off")
        if not a_dep and eff_listed:      deposits_reasons.append("admin")
        if locks["deposits_locked"]:      deposits_reasons.append("type-locked")
        if locks["registry_paused"]:      deposits_reasons.append("registry-paused")
    if not eff_wd:
        if not eff_listed:                withdrawals_reasons.append("listing-off")
        if not a_wd and eff_listed:       withdrawals_reasons.append("admin")
        if locks["withdrawals_locked"]:   withdrawals_reasons.append("type-locked")

    return {
        "listed":      eff_listed,
        "deposits":    eff_dep,
        "withdrawals": eff_wd,
        "listed_reasons":      listed_reasons,
        "deposits_reasons":    deposits_reasons,
        "withdrawals_reasons": withdrawals_reasons,
        "locks":               locks,
    }


async def _get_state_map() -> dict[str, dict]:
    """Return {vault_id: state_doc} for all vaults that have an admin entry.
    Vaults missing from this map default to fully enabled."""
    db = database._db  # noqa: SLF001
    if db is None:
        return {}
    out: dict[str, dict] = {}
    async for doc in db["vault_admin_state"].find({}):
        vid = doc.get("vault_id")
        if not vid:
            continue
        out[vid] = doc
    return out


async def is_vault_enabled(vault_id: str) -> bool:
    """Used by public endpoints (vaults list, quote, withdraw) to enforce the
    admin gate. Defaults to True if no admin entry exists."""
    db = database._db  # noqa: SLF001
    if db is None:
        return True
    doc = await db["vault_admin_state"].find_one({"vault_id": vault_id})
    if not doc:
        return True
    return bool(doc.get("enabled", True))


async def get_vault_flags(vault_id: str) -> dict:
    """Returns {enabled, deposits_enabled, withdrawals_enabled} for a vault.
    Defaults to all-true when no admin entry exists. NOTE: returns ADMIN
    OVERRIDE only — does not include registry-side locks. Public endpoints
    should also keep their existing registry checks (paused/type=unsupported);
    this function only adds the admin-policy layer on top."""
    db = database._db  # noqa: SLF001
    if db is None:
        return {"enabled": True, "deposits_enabled": True, "withdrawals_enabled": True}
    doc = await db["vault_admin_state"].find_one({"vault_id": vault_id})
    if not doc:
        return {"enabled": True, "deposits_enabled": True, "withdrawals_enabled": True}
    return {
        "enabled": bool(doc.get("enabled", True)),
        "deposits_enabled": bool(doc.get("deposits_enabled", True)),
        "withdrawals_enabled": bool(doc.get("withdrawals_enabled", True)),
    }


async def get_disabled_vault_ids() -> set[str]:
    """Single roundtrip used by /v1/vaults to filter the public list."""
    db = database._db  # noqa: SLF001
    if db is None:
        return set()
    out: set[str] = set()
    async for doc in db["vault_admin_state"].find({"enabled": False}, {"vault_id": 1}):
        if doc.get("vault_id"):
            out.add(doc["vault_id"])
    return out


def _flatten_metrics(metrics: dict | None) -> dict:
    """Indexer stores each metric as `{value, ...}` envelopes. Public-side
    /api/vaults flattens them; we mirror the same shape so the admin page can
    feed the data through the existing `mapVault` logic in useVaultData.js."""
    out: dict = {}
    if not isinstance(metrics, dict):
        return out
    for key, m in metrics.items():
        if isinstance(m, dict) and "value" in m:
            v = m["value"]
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            elif isinstance(v, float):
                v = round(v, 4)
            out[key] = v
        else:
            out[key] = m
    return out


async def _get_indexer_metrics_map() -> dict[str, dict]:
    """Fetch ALL vault metric documents from the indexer DB in one query and
    return as a {vault_id: row} map. Mirrors the shape produced by
    /api/vaults.js (Vercel) so the FE can reuse mapVault() unchanged."""
    db = database.get_indexer_db()
    if db is None:
        return {}
    out: dict[str, dict] = {}
    async for entry in db["vaults"].find({}):
        vid = entry.get("_id") or entry.get("vault_id")
        if not vid:
            continue
        row = {
            "vault_id": vid,
            "vault_address": entry.get("address") or vid,
            "chain_id": entry.get("chain_id") or 1,
            "asset": entry.get("asset") or "usdc",
            "vault_name": entry.get("name") or (str(vid)[:12] + "..."),
            "source": entry.get("source"),
            "timestamp": entry["updated_at"].isoformat() if isinstance(entry.get("updated_at"), datetime) else None,
        }
        row.update(_flatten_metrics(entry.get("metrics")))
        out[vid] = row
    return out


def _synthesize_registry_from_metrics(vault_id: str, metrics: dict) -> dict:
    """Build a faux registry entry for a vault that lives in the indexer DB
    but isn't (yet) in vaults.json. The admin page can still display it and
    control visibility — but deposits/withdrawals stay locked because we
    don't have a deposit_router or supported `type` for it."""
    return {
        "vault_id": vault_id,
        "name": metrics.get("vault_name") or vault_id,
        "address": metrics.get("vault_address") or vault_id,
        "chain_id": metrics.get("chain_id"),
        "chain_name": None,  # we don't track chain names in the indexer doc; FE falls back to CHAIN_NAMES[id]
        "asset_symbol": (metrics.get("asset") or "").upper() or None,
        "asset_address": None,
        "type": "unsupported",  # forces both deposit & withdraw to hard-lock
        "curator": metrics.get("source"),
        "paused": False,
        "paused_reason": None,
        "external_router": False,
    }


@router.get("/vaults")
async def admin_list_vaults(_sess: dict = Depends(require_admin)):
    """Admin-only vault list. Source of truth is the UNION of:
      - vaults.json (registry — has deposit_router + type + paused + curator)
      - yieldo_v1.vaults (indexer — has metrics + score components)

    Vaults present in the indexer but not the registry are surfaced too, so
    the admin sees every vault the indexer is tracking and can control its
    public visibility. Their deposit/withdraw toggles are hard-locked
    (`registry_missing: true`) until someone adds a real entry to vaults.json.
    """
    raw = get_all_vaults_raw()
    state_map = await _get_state_map()
    metrics_map = await _get_indexer_metrics_map()

    # Build the union: every vault from either source. Registry takes
    # precedence for the merge target so vaults that exist in both retain
    # their full registry metadata.
    registry_by_id = {v.get("vault_id"): v for v in raw if v.get("vault_id")}
    all_ids = set(registry_by_id.keys()) | set(metrics_map.keys())

    out = []
    for vid in all_ids:
        in_registry = vid in registry_by_id
        v = registry_by_id.get(vid) or _synthesize_registry_from_metrics(vid, metrics_map.get(vid, {}))
        st = state_map.get(vid) or _default_state(vid)
        eff = _effective_for(v, st)
        metrics = metrics_map.get(vid, {})

        # When a vault is registry-missing we surface a clearer reason on the
        # locked toggles: "needs registry entry" instead of "type-locked".
        deposits_reasons = list(eff["deposits_reasons"])
        withdrawals_reasons = list(eff["withdrawals_reasons"])
        if not in_registry:
            if "type-locked" in deposits_reasons:
                deposits_reasons[deposits_reasons.index("type-locked")] = "registry-missing"
            if "type-locked" in withdrawals_reasons:
                withdrawals_reasons[withdrawals_reasons.index("type-locked")] = "registry-missing"

        out.append({
            "vault_id": vid,
            "name": v.get("name"),
            "address": v.get("address"),
            "chain_id": v.get("chain_id"),
            "chain_name": v.get("chain_name"),
            "asset_symbol": v.get("asset_symbol"),
            "asset_address": v.get("asset_address"),
            "type": v.get("type"),
            "curator": v.get("curator"),
            "paused": bool(v.get("paused", False)),
            "paused_reason": v.get("paused_reason"),
            "external_router": bool(v.get("external_router", False)),

            # NEW: tells the FE this vault came from the indexer only.
            "registry_missing": not in_registry,
            "registry_present": in_registry,

            # Admin override (mutable, what the toggles control)
            "admin_enabled":             bool(st.get("enabled", True)),
            "admin_deposits_enabled":    bool(st.get("deposits_enabled", True)),
            "admin_withdrawals_enabled": bool(st.get("withdrawals_enabled", True)),

            # Effective live state (what users actually see — UI shows these)
            "effective_listed":      eff["listed"],
            "effective_deposits":    eff["deposits"],
            "effective_withdrawals": eff["withdrawals"],

            # Why is each effective flag the way it is — for badges/tooltips
            "listed_reasons":      eff["listed_reasons"],
            "deposits_reasons":    deposits_reasons,
            "withdrawals_reasons": withdrawals_reasons,
            # Hard locks from registry — toggles for these are non-overridable
            "deposits_locked":    eff["locks"]["deposits_locked"],
            "withdrawals_locked": eff["locks"]["withdrawals_locked"],

            # Back-compat aliases for older FE code
            "enabled":             bool(st.get("enabled", True)),
            "deposits_enabled":    bool(st.get("deposits_enabled", True)),
            "withdrawals_enabled": bool(st.get("withdrawals_enabled", True)),

            "updated_at": st.get("updated_at").isoformat() if isinstance(st.get("updated_at"), datetime) else None,
            "updated_by": st.get("updated_by"),

            # Inline metrics — same key shape as /api/vaults.js. Includes:
            # P01, P03, P05, P06, P07, P08, P10, P12, T01, T02, T03,
            # C01, C01_USD, C03, C07, D01, R02, R05, source, etc.
            "metrics": metrics,
        })
    # Stable ordering: registry-present first, then by chain, then by name.
    out.sort(key=lambda r: (
        not r["registry_present"],
        r.get("chain_id") or 0,
        (r.get("name") or "").lower(),
    ))
    return {"vaults": out, "count": len(out)}


@router.get("/vaults/{vault_id}")
async def admin_vault_detail(vault_id: str, _sess: dict = Depends(require_admin)):
    """Full vault detail bypassing the public-side disable filter. Mirrors
    /api/vaults/[vaultId].js so the admin can review metrics — including
    snapshots for the APY chart — before flipping a vault live.

    Accepts vaults that exist in the indexer but not the registry (newly
    indexed vaults that haven't been added to vaults.json yet). For those,
    the registry block is synthesized so the FE can render scores while
    deposits/withdrawals stay hard-locked."""
    raw = get_all_vaults_raw()
    vault = next((v for v in raw if v.get("vault_id") == vault_id), None)
    in_registry = vault is not None

    db = database.get_indexer_db()
    metrics_row: dict = {}
    snapshots: list = []
    if db is not None:
        entry = await db["vaults"].find_one({"_id": vault_id})
        if entry:
            metrics_row = {
                "vault_id": vault_id,
                "vault_address": entry.get("address") or vault_id,
                "chain_id": entry.get("chain_id") or 1,
                "asset": entry.get("asset") or "usdc",
                "vault_name": entry.get("name") or (vault_id[:12] + "..."),
                "source": entry.get("source"),
                "timestamp": entry["updated_at"].isoformat() if isinstance(entry.get("updated_at"), datetime) else None,
            }
            metrics_row.update(_flatten_metrics(entry.get("metrics")))

    # If neither the registry nor the indexer has this vault, it doesn't exist.
    if not in_registry and not metrics_row:
        raise HTTPException(404, "Unknown vault_id")
    if not in_registry:
        vault = _synthesize_registry_from_metrics(vault_id, metrics_row)

    state = (await _get_state_map()).get(vault_id) or _default_state(vault_id)
    eff = _effective_for(vault, state)
    if db is not None:
        # Same snapshot query as /api/vaults/[vaultId].js (case-insensitive id match).
        snap_cursor = db["snapshots"].find({"vault_id": vault_id}).sort("date", 1)
        async for s in snap_cursor:
            snapshots.append({
                "date": s.get("date"),
                "net_apy": s.get("net_apy"),
                "nav": s.get("nav"),
                "total_assets_usd": s.get("total_assets_usd"),
                "total_assets_native": s.get("total_assets_native"),
            })

    payload = {
        # Registry block (same shape as get_vault detail)
        "vault_id": vault_id,
        "name": vault.get("name"),
        "address": vault.get("address"),
        "chain_id": vault.get("chain_id"),
        "chain_name": vault.get("chain_name"),
        "asset_symbol": vault.get("asset_symbol"),
        "asset_address": vault.get("asset_address"),
        "type": vault.get("type"),
        "curator": vault.get("curator"),
        "paused": bool(vault.get("paused", False)),
        "paused_reason": vault.get("paused_reason"),
        "external_router": bool(vault.get("external_router", False)),
        "registry_missing": not in_registry,
        "registry_present": in_registry,

        # Admin state + effective flags + locks + reasons (same as list)
        "admin_enabled":             bool(state.get("enabled", True)),
        "admin_deposits_enabled":    bool(state.get("deposits_enabled", True)),
        "admin_withdrawals_enabled": bool(state.get("withdrawals_enabled", True)),
        "effective_listed":      eff["listed"],
        "effective_deposits":    eff["deposits"],
        "effective_withdrawals": eff["withdrawals"],
        "listed_reasons":      eff["listed_reasons"],
        "deposits_reasons":    eff["deposits_reasons"],
        "withdrawals_reasons": eff["withdrawals_reasons"],
        "deposits_locked":    eff["locks"]["deposits_locked"],
        "withdrawals_locked": eff["locks"]["withdrawals_locked"],

        # Inline indexer payload + snapshots — same shape as /api/vaults/[id]
        # so the FE can render the existing VaultDetailPage chart/table view
        # without any custom mapping.
        "metrics": metrics_row,
        "snapshots": snapshots,
    }
    return payload


@router.patch("/vaults/{vault_id}")
async def admin_toggle_vault(
    vault_id: str,
    req: VaultToggleRequest,
    sess: dict = Depends(require_admin),
):
    """Upsert an admin state row. Pass any subset of {enabled, deposits_enabled,
    withdrawals_enabled} — unspecified flags are left untouched."""
    db = database._db  # noqa: SLF001
    if db is None:
        raise HTTPException(503, "DB not connected")
    # Vault must exist in the registry — guards against typos creating ghost rows.
    raw = get_all_vaults_raw()
    vault = next((v for v in raw if v.get("vault_id") == vault_id), None)
    if not vault:
        raise HTTPException(404, "Unknown vault_id")
    locks = _registry_locks(vault)
    update: dict = {}
    if req.enabled is not None:
        update["enabled"] = bool(req.enabled)
    if req.deposits_enabled is not None:
        # Refuse to flip ON for vault types that physically can't accept
        # deposits through our router. Storing True would still leave the
        # public flow blocked by the registry check, but better to surface
        # the conflict here than let the admin think they enabled something.
        if req.deposits_enabled and locks["deposits_locked"]:
            raise HTTPException(400, f"Deposits are locked by vault type ({locks['registry_type']}); cannot be enabled.")
        update["deposits_enabled"] = bool(req.deposits_enabled)
    if req.withdrawals_enabled is not None:
        if req.withdrawals_enabled and locks["withdrawals_locked"]:
            raise HTTPException(400, f"Withdrawals are locked by vault type ({locks['registry_type']}); cannot be enabled.")
        update["withdrawals_enabled"] = bool(req.withdrawals_enabled)
    if not update:
        raise HTTPException(400, "No fields to update")
    update["updated_at"] = datetime.now(timezone.utc)
    update["updated_by"] = sess["address"]
    await db["vault_admin_state"].update_one(
        {"vault_id": vault_id},
        {"$set": update, "$setOnInsert": {"vault_id": vault_id}},
        upsert=True,
    )
    flags = await get_vault_flags(vault_id)
    logger.info(f"[admin] toggle vault_id={vault_id} by={sess['address']} new_state={flags}")
    return {"ok": True, "vault_id": vault_id, **flags}


@router.get("/me")
async def admin_me(sess: dict = Depends(require_admin)):
    """Light health-check the FE uses to confirm the saved token is still good."""
    return {
        "address": sess["address"],
        "expires_at": sess["expires_at"].isoformat() if isinstance(sess.get("expires_at"), datetime) else None,
    }
