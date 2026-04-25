import json
import logging
import os
import threading
import urllib.request
from app.core.constants import (
    DEPOSIT_ROUTER_ADDRESSES,
    ASSET_TOKEN_CONFIG,
    CHAIN_CONFIG,
)
from app.services.rpc import get_vault_asset, get_token_decimals
from app.models import VaultResponse, AssetInfo

logger = logging.getLogger(__name__)

_vaults: dict[str, dict] = {}

# Public registry the frontend reads (indexer -> MongoDB -> Vercel function).
# We use it to (1) detect drift vs vaults.json on startup and (2) lazily resolve
# vault_ids the frontend sends but vaults.json doesn't list — so users never see
# "Vault not found" when a new vault appears in the indexer ahead of vaults.json.
PUBLIC_REGISTRY_URL = os.environ.get(
    "YIELDO_PUBLIC_VAULT_REGISTRY",
    "https://app.yieldo.xyz/api/vaults",
)


def _resolve_asset(chain_id: int, asset_symbol: str, vault_address: str) -> tuple[str, int] | None:
    chain_assets = ASSET_TOKEN_CONFIG.get(chain_id, {})
    if asset_symbol in chain_assets:
        return chain_assets[asset_symbol]
    try:
        asset_addr = get_vault_asset(chain_id, vault_address)
        decimals = get_token_decimals(chain_id, asset_addr)
        return asset_addr, decimals
    except Exception as e:
        logger.warning(f"Failed to resolve asset for vault {chain_id}:{vault_address}: {e}")
        return None


def load_vaults():
    global _vaults
    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "vaults.json")
    with open(data_path) as f:
        raw = json.load(f)

    for v in raw:
        chain_id = v["chain_id"]
        if chain_id not in DEPOSIT_ROUTER_ADDRESSES:
            continue
        vault_id = f"{chain_id}:{v['address'].lower()}"
        resolved = _resolve_asset(chain_id, v["asset"], v["address"])
        if resolved is None:
            logger.warning(f"Skipping vault {vault_id} ({v['name']}): asset unresolvable")
            continue
        asset_addr, asset_decimals = resolved
        _vaults[vault_id] = {
            "vault_id": vault_id,
            "name": v["name"],
            "address": v["address"],
            "chain_id": chain_id,
            "chain_name": CHAIN_CONFIG.get(chain_id, {}).get("name", "Unknown"),
            "asset_symbol": v["asset"],
            "asset_address": asset_addr,
            "asset_decimals": asset_decimals,
            "deposit_router": DEPOSIT_ROUTER_ADDRESSES[chain_id],
            "type": v.get("type", "morpho"),
            "min_deposit": v.get("min_deposit"),
            "curator": v.get("curator"),
        }


def get_all_vaults() -> list[VaultResponse]:
    return [_to_response(v) for v in _vaults.values()]


def get_all_vaults_raw() -> list[dict]:
    return list(_vaults.values())


def get_vault(vault_id: str) -> dict | None:
    """Find a vault by id, falling back to the public registry if vaults.json
    doesn't list it. The registry is what the frontend reads, so this prevents
    the "vault address differs between sources" failure mode entirely. Resolved
    fallbacks are cached in `_vaults` for the lifetime of the process."""
    key = vault_id.lower()
    v = _vaults.get(key) or _vaults.get(vault_id)
    if v:
        return v
    return _resolve_from_registry(key)


def _resolve_from_registry(vault_id: str) -> dict | None:
    try:
        chain_str, addr = vault_id.split(":", 1)
        chain_id = int(chain_str)
        addr = addr.lower()
    except Exception:
        return None
    if chain_id not in DEPOSIT_ROUTER_ADDRESSES:
        return None
    entry = _fetch_registry_entry(chain_id, addr)
    if not entry:
        return None
    # Synthesise a default config and resolve asset on-chain.
    asset_symbol = (entry.get("asset") or "").lower()
    resolved = _resolve_asset(chain_id, asset_symbol, addr)
    if resolved is None:
        logger.warning(f"registry-fallback: asset unresolvable for {vault_id}")
        return None
    asset_addr, decimals = resolved
    rec = {
        "vault_id": vault_id,
        "name": entry.get("vault_name") or entry.get("name") or vault_id,
        "address": entry.get("vault_address") or addr,
        "chain_id": chain_id,
        "chain_name": CHAIN_CONFIG.get(chain_id, {}).get("name", "Unknown"),
        "asset_symbol": asset_symbol or "usdc",
        "asset_address": asset_addr,
        "asset_decimals": decimals,
        "deposit_router": DEPOSIT_ROUTER_ADDRESSES[chain_id],
        "type": "morpho",  # default; explicit non-morpho types must be in vaults.json
        "min_deposit": None,
        "curator": None,
        "_source": "registry-fallback",
    }
    _vaults[vault_id] = rec
    logger.warning(
        f"registry-fallback resolved {vault_id} ({rec['name']}). "
        f"Add this vault to vaults.json to lock in custom config."
    )
    return rec


_REGISTRY_CACHE: dict[str, dict] = {}
_REGISTRY_FETCHED = [False]


def _fetch_registry_entry(chain_id: int, addr: str) -> dict | None:
    addr = addr.lower()
    cache_key = f"{chain_id}:{addr}"
    if cache_key in _REGISTRY_CACHE:
        return _REGISTRY_CACHE[cache_key]
    if not _REGISTRY_FETCHED[0]:
        _refresh_registry()
    return _REGISTRY_CACHE.get(cache_key)


def _refresh_registry() -> None:
    try:
        with urllib.request.urlopen(PUBLIC_REGISTRY_URL, timeout=8) as resp:
            data = json.load(resp)
        for entry in data:
            vid = (entry.get("vault_id") or "").lower()
            if vid:
                _REGISTRY_CACHE[vid] = entry
        _REGISTRY_FETCHED[0] = True
        logger.info(f"public registry loaded: {len(_REGISTRY_CACHE)} vaults from {PUBLIC_REGISTRY_URL}")
    except Exception as e:
        logger.warning(f"failed to load public registry {PUBLIC_REGISTRY_URL}: {e}")


def audit_against_registry() -> dict:
    """Diff vaults.json (us) vs the public registry (frontend) — log every drift
    so we hear about it BEFORE a user does. Returns a structured report so an
    optional /v1/vaults/integrity endpoint or startup hook can surface it."""
    if not _REGISTRY_FETCHED[0]:
        _refresh_registry()
    in_us = set(_vaults.keys())
    in_registry = set(_REGISTRY_CACHE.keys())
    only_us = sorted(in_us - in_registry)
    only_registry = sorted(in_registry - in_us)
    # Drift signal: same vault id present in both is fine. The user-impacting bug is
    # an id in the registry that we don't have — that's what makes deposits fail.
    if only_registry:
        logger.warning(
            f"VAULT REGISTRY DRIFT — {len(only_registry)} vaults in indexer/MongoDB "
            f"but missing from vaults.json (deposits will fall back to defaults): "
            f"{', '.join(only_registry[:10])}{'...' if len(only_registry) > 10 else ''}"
        )
    if only_us:
        logger.info(
            f"vaults.json has {len(only_us)} vaults not in indexer registry "
            f"(probably newer entries we added manually before indexer caught up): "
            f"{', '.join(only_us[:10])}{'...' if len(only_us) > 10 else ''}"
        )
    return {
        "vaults_json_total": len(in_us),
        "registry_total": len(in_registry),
        "missing_from_vaults_json": only_registry,
        "missing_from_registry": only_us,
    }


def start_registry_audit_thread() -> None:
    """Run the audit in a background thread on app boot so we get loud logs
    about any drift without blocking startup."""
    def run():
        try:
            audit_against_registry()
        except Exception as e:
            logger.warning(f"registry audit failed: {e}")
    threading.Thread(target=run, daemon=True).start()


def get_vault_response(vault_id: str) -> VaultResponse | None:
    v = get_vault(vault_id)
    if not v:
        return None
    return _to_response(v)


def _to_response(v: dict) -> VaultResponse:
    # Local import — keeps import graph acyclic (min_deposit imports rpc which uses constants)
    from app.services import min_deposit as _min_deposit
    resolved_min, no_min = _min_deposit.resolve(v)
    return VaultResponse(
        vault_id=v["vault_id"],
        name=v["name"],
        address=v["address"],
        chain_id=v["chain_id"],
        chain_name=v["chain_name"],
        asset=AssetInfo(
            address=v["asset_address"],
            symbol=v["asset_symbol"],
            decimals=v["asset_decimals"],
        ),
        deposit_router=v["deposit_router"],
        type=v.get("type", "morpho"),
        min_deposit=str(resolved_min) if resolved_min is not None else None,
        no_minimum=no_min,
        curator=v.get("curator"),
    )
