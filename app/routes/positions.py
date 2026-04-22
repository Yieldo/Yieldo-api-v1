from fastapi import APIRouter, HTTPException, Query
from app.models import Position, PositionsResponse
from app.services.vault import get_all_vaults_raw
from app.services.rpc import get_erc20_balance, get_vault_convert_to_assets, get_vault_share_price
from app.services import database, zerion

router = APIRouter(prefix="/v1/positions", tags=["positions"])


def _shares_to_assets_fallback(shares: int, total_assets: int, total_supply: int) -> int:
    """Compute asset value from shares using totalAssets/totalSupply ratio.
    Used when the vault doesn't expose convertToAssets."""
    if total_supply == 0:
        return 0
    return (shares * total_assets) // total_supply


def _shares_from_quantity(quantity: float, share_decimals: int = 18) -> int:
    """Convert Zerion's human-readable token quantity to raw smallest-unit int."""
    return int(quantity * (10 ** share_decimals))


@router.get("/{user_address}", response_model=PositionsResponse)
async def get_positions(user_address: str, chain_id: int | None = Query(None)):
    """Read user's vault positions with current value + historical deposited amount.

    Strategy:
    1. Try Zerion API — single call returns positions across all supported chains with USD values
    2. For vaults Zerion doesn't know about (chain unsupported, new protocols), fall back to RPC
    3. For every position, sum historical deposits from our DB for yield computation
    """
    if not user_address or len(user_address) != 42:
        raise HTTPException(status_code=400, detail="Invalid address")

    vaults = get_all_vaults_raw()
    deposited = await database.get_deposited_per_vault(user_address)

    # Step 1: try Zerion
    zerion_positions = await zerion.fetch_positions(user_address)
    zerion_matched_vault_ids: set[str] = set()

    out: list[Position] = []

    if zerion_positions:
        # Build a map for fast lookup
        by_chain_addr = {(p["chain_id"], p["token_address"].lower()): p for p in zerion_positions}
        for v in vaults:
            if v.get("type") == "unsupported":
                continue
            if chain_id is not None and v["chain_id"] != chain_id:
                continue
            key = (v["chain_id"], v["address"].lower())
            zp = by_chain_addr.get(key)
            if not zp:
                continue

            share_balance = str(_shares_from_quantity(zp["quantity"], 18))
            asset_decimals = v.get("asset_decimals", 18)

            # Zerion gives us USD and raw quantity. Convert quantity to asset-unit current_assets
            # by using convertToAssets for precision (single RPC call per matched vault, still
            # much faster than balanceOf for all vaults).
            current_assets = None
            try:
                current_assets = get_vault_convert_to_assets(
                    v["chain_id"], v["address"], int(share_balance)
                )
            except Exception:
                try:
                    ta, ts = get_vault_share_price(v["chain_id"], v["address"])
                    if ts > 0:
                        current_assets = _shares_to_assets_fallback(int(share_balance), ta, ts)
                except Exception:
                    pass

            dep_amt = deposited.get(v["vault_id"])
            yield_amt = None
            if current_assets is not None and dep_amt is not None:
                yield_amt = current_assets - dep_amt

            out.append(Position(
                vault_id=v["vault_id"],
                vault_name=v["name"],
                vault_address=v["address"],
                chain_id=v["chain_id"],
                asset_symbol=v.get("asset_symbol", "").upper(),
                asset_address=v.get("asset_address", ""),
                asset_decimals=asset_decimals,
                share_balance=share_balance,
                share_decimals=18,
                vault_type=v.get("type", "morpho"),
                current_assets=str(current_assets) if current_assets is not None else None,
                deposited_assets=str(dep_amt) if dep_amt is not None else None,
                yield_assets=str(yield_amt) if yield_amt is not None else None,
                value_usd=zp.get("value_usd"),
                apy=zp.get("apy"),
                source="zerion",
            ))
            zerion_matched_vault_ids.add(v["vault_id"])

    # Step 2: RPC fallback for vaults we didn't match via Zerion
    # (new vaults, unsupported chains on Zerion, or when Zerion returned nothing)
    for v in vaults:
        if v.get("type") == "unsupported":
            continue
        if chain_id is not None and v["chain_id"] != chain_id:
            continue
        if v["vault_id"] in zerion_matched_vault_ids:
            continue

        # Only probe via RPC when Zerion doesn't cover this chain, or Zerion returned nothing.
        # Avoids wasting RPC calls on known-zero balances Zerion already told us about.
        zerion_covers_chain = v["chain_id"] in zerion._ZERION_TO_EVM_CHAIN.values() if zerion_positions is not None else False
        if zerion_positions is not None and zerion_covers_chain:
            continue  # Zerion scanned this chain and found no position

        try:
            bal = get_erc20_balance(v["chain_id"], v["address"], user_address)
        except Exception:
            continue
        if bal <= 0:
            continue

        current_assets = None
        try:
            current_assets = get_vault_convert_to_assets(v["chain_id"], v["address"], bal)
        except Exception:
            try:
                ta, ts = get_vault_share_price(v["chain_id"], v["address"])
                if ts > 0:
                    current_assets = _shares_to_assets_fallback(bal, ta, ts)
            except Exception:
                pass

        dep_amt = deposited.get(v["vault_id"])
        yield_amt = None
        if current_assets is not None and dep_amt is not None:
            yield_amt = current_assets - dep_amt

        out.append(Position(
            vault_id=v["vault_id"],
            vault_name=v["name"],
            vault_address=v["address"],
            chain_id=v["chain_id"],
            asset_symbol=v.get("asset_symbol", "").upper(),
            asset_address=v.get("asset_address", ""),
            asset_decimals=v.get("asset_decimals", 18),
            share_balance=str(bal),
            share_decimals=18,
            vault_type=v.get("type", "morpho"),
            current_assets=str(current_assets) if current_assets is not None else None,
            deposited_assets=str(dep_amt) if dep_amt is not None else None,
            yield_assets=str(yield_amt) if yield_amt is not None else None,
            value_usd=None,
            apy=None,
            source="rpc",
        ))

    return PositionsResponse(user_address=user_address, positions=out)


@router.get("/_meta/zerion-usage")
async def zerion_usage():
    """Current day's Zerion API call count (for debugging / monitoring)."""
    return zerion.get_daily_usage()
