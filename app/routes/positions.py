from fastapi import APIRouter, HTTPException, Query
from app.models import Position, PositionsResponse
from app.services.vault import get_all_vaults_raw
from app.services.rpc import get_erc20_balance, get_vault_convert_to_assets, get_vault_share_price
from app.services import database

router = APIRouter(prefix="/v1/positions", tags=["positions"])


def _shares_to_assets_fallback(shares: int, total_assets: int, total_supply: int) -> int:
    """Compute asset value from shares using totalAssets/totalSupply ratio.
    Used when the vault doesn't expose convertToAssets."""
    if total_supply == 0:
        return 0
    return (shares * total_assets) // total_supply


@router.get("/{user_address}", response_model=PositionsResponse)
async def get_positions(user_address: str, chain_id: int | None = Query(None)):
    """Read user's share balances + current asset value + historical deposited amount.

    On-chain reads share_balance + converts to asset units.
    DB read sums historical deposit amounts per vault (for yield computation on frontend).
    """
    if not user_address or len(user_address) != 42:
        raise HTTPException(status_code=400, detail="Invalid address")

    vaults = get_all_vaults_raw()
    deposited = await database.get_deposited_per_vault(user_address)

    out: list[Position] = []
    for v in vaults:
        if v.get("type") == "unsupported":
            continue
        if chain_id is not None and v["chain_id"] != chain_id:
            continue

        try:
            bal = get_erc20_balance(v["chain_id"], v["address"], user_address)
        except Exception:
            continue
        if bal <= 0:
            continue

        # Try to convert shares -> asset amount
        current_assets = None
        try:
            current_assets = get_vault_convert_to_assets(v["chain_id"], v["address"], bal)
        except Exception:
            # Fallback: compute from share price ratio
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
        ))

    return PositionsResponse(user_address=user_address, positions=out)
