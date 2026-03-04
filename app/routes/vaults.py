from fastapi import APIRouter, HTTPException, Query
from app.models import VaultResponse, VaultDetailResponse
from app.services.vault import get_all_vaults, get_vault, get_vault_response
from app.services.rpc import get_vault_share_price

router = APIRouter(prefix="/v1/vaults", tags=["vaults"])


@router.get("", response_model=list[VaultResponse])
async def list_vaults(
    chain_id: int | None = Query(None, description="Filter by chain ID"),
    asset: str | None = Query(None, description="Filter by asset symbol"),
):
    vaults = get_all_vaults()
    if chain_id is not None:
        vaults = [v for v in vaults if v.chain_id == chain_id]
    if asset is not None:
        vaults = [v for v in vaults if v.asset.symbol.lower() == asset.lower()]
    return vaults


@router.get("/{vault_id}", response_model=VaultDetailResponse)
async def get_vault_detail(vault_id: str):
    v = get_vault(vault_id)
    if not v:
        raise HTTPException(status_code=404, detail=f"Vault {vault_id} not found")
    try:
        total_assets, total_supply = get_vault_share_price(v["chain_id"], v["address"])
        share_price = None
        if total_supply > 0:
            share_price = str((total_assets * 10**18) // total_supply)
    except Exception:
        total_assets = None
        total_supply = None
        share_price = None

    return VaultDetailResponse(
        vault_id=v["vault_id"],
        name=v["name"],
        address=v["address"],
        chain_id=v["chain_id"],
        chain_name=v["chain_name"],
        asset={
            "address": v["asset_address"],
            "symbol": v["asset_symbol"],
            "decimals": v["asset_decimals"],
        },
        deposit_router=v["deposit_router"],
        total_assets=str(total_assets) if total_assets is not None else None,
        total_supply=str(total_supply) if total_supply is not None else None,
        share_price=share_price,
    )
