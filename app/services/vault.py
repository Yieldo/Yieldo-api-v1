import json
import logging
import os
from app.core.constants import (
    DEPOSIT_ROUTER_ADDRESSES,
    ASSET_TOKEN_CONFIG,
    CHAIN_CONFIG,
)
from app.services.rpc import get_vault_asset, get_token_decimals
from app.models import VaultResponse, AssetInfo

logger = logging.getLogger(__name__)

_vaults: dict[str, dict] = {}


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
    return _vaults.get(vault_id.lower()) or _vaults.get(vault_id)


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
