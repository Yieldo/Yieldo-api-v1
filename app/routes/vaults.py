from fastapi import APIRouter, HTTPException, Query, Request
from app.models import VaultResponse, VaultDetailResponse
from app.services.vault import get_all_vaults, get_vault, get_vault_response, audit_against_registry
from app.services.rpc import get_vault_share_price
from app.services import database
from app.routes.partners import get_partner_from_api_key

router = APIRouter(prefix="/v1/vaults", tags=["vaults"])


@router.get("", response_model=list[VaultResponse])
async def list_vaults(
    request: Request,
    chain_id: int | None = Query(None, description="Filter by chain ID"),
    asset: str | None = Query(None, description="Filter by asset symbol"),
):
    vaults = get_all_vaults()
    if chain_id is not None:
        vaults = [v for v in vaults if v.chain_id == chain_id]
    if asset is not None:
        vaults = [v for v in vaults if v.asset.symbol.lower() == asset.lower()]
    # Filter by enrolled vaults when partner API key is provided
    partner = await get_partner_from_api_key(request)
    if partner:
        enrolled = partner.get("enrolled_vaults", [])
        if enrolled:
            vaults = [v for v in vaults if v.vault_id in enrolled]
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

    from app.services import min_deposit as _min_deposit
    resolved_min, no_min = _min_deposit.resolve(v)
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
        accepted_assets=[
            {"address": a["address"], "symbol": a["symbol"], "decimals": a["decimals"]}
            for a in (v.get("accepted_assets") or [])
        ],
        deposit_router=v["deposit_router"],
        type=v.get("type", "morpho"),
        min_deposit=str(resolved_min) if resolved_min is not None else None,
        no_minimum=no_min,
        curator=v.get("curator"),
        paused=bool(v.get("paused", False)),
        paused_reason=v.get("paused_reason"),
        external_router=bool(v.get("external_router", False)),
        total_assets=str(total_assets) if total_assets is not None else None,
        total_supply=str(total_supply) if total_supply is not None else None,
        share_price=share_price,
    )


@router.get("/integrity")
async def get_vault_registry_integrity():
    """Diff vaults.json against the public/indexer registry. Returns lists of
    vault_ids missing from each side. Use this in CI / monitoring to fail fast
    when the two registries drift apart."""
    return audit_against_registry()


@router.get("/{vault_id}/stats")
async def get_vault_stats(
    vault_id: str,
    days: int = Query(30, ge=1, le=365),
    from_chain_id: int | None = Query(None, description="Filter by source chain"),
    from_token: str | None = Query(None, description="Filter by source token address (case-insensitive)"),
):
    """Real success-rate stats from historical deposits, optionally filtered by
    source chain + token. Returns overall + per-bridge breakdown so the deposit
    UI can tag each route option with its observed success rate."""
    v = get_vault(vault_id)
    if not v:
        raise HTTPException(status_code=404, detail=f"Vault {vault_id} not found")
    return await database.get_vault_success_stats(
        vault_id=vault_id,
        days=days,
        from_chain_id=from_chain_id,
        from_token=from_token,
    )
