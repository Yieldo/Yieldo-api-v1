from fastapi import APIRouter, HTTPException, Query
from app.models import Position, PositionsResponse
from app.services.vault import get_all_vaults_raw
from app.services.rpc import get_erc20_balance

router = APIRouter(prefix="/v1/positions", tags=["positions"])


@router.get("/{user_address}", response_model=PositionsResponse)
async def get_positions(user_address: str, chain_id: int | None = Query(None)):
    """Read user's share balances across all known vaults. Optionally filter by chain.
    On-chain read; no DB lookup. Returns only vaults with non-zero balance."""
    if not user_address or len(user_address) != 42:
        raise HTTPException(status_code=400, detail="Invalid address")

    vaults = get_all_vaults_raw()
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
        out.append(Position(
            vault_id=v["vault_id"],
            vault_name=v["name"],
            vault_address=v["address"],
            chain_id=v["chain_id"],
            asset_symbol=v.get("asset_symbol", "").upper(),
            asset_address=v.get("asset_address", ""),
            share_balance=str(bal),
            share_decimals=18,
            vault_type=v.get("type", "morpho"),
        ))

    return PositionsResponse(user_address=user_address, positions=out)
