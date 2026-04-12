from datetime import datetime

from fastapi import APIRouter, Query
from app.services import database
from app.core.constants import CHAIN_CONFIG

router = APIRouter(prefix="/v1/deposits", tags=["deposits"])


@router.get("")
async def get_user_deposits(
    user_address: str = Query(..., description="User wallet address"),
    limit: int = Query(50, le=200),
    skip: int = Query(0, ge=0),
):
    deposits = await database.get_user_deposits(user_address, limit=limit, skip=skip)
    for d in deposits:
        if "created_at" in d and isinstance(d["created_at"], datetime):
            d["created_at"] = d["created_at"].isoformat()
        if "updated_at" in d and isinstance(d["updated_at"], datetime):
            d["updated_at"] = d["updated_at"].isoformat()
        # Clean up status_history datetimes
        for sh in d.get("status_history", []):
            if isinstance(sh.get("timestamp"), datetime):
                sh["timestamp"] = sh["timestamp"].isoformat()
        # Add explorer links
        chain_id = d.get("from_chain_id")
        tx_hash = d.get("tx_hash")
        cfg = CHAIN_CONFIG.get(chain_id, {})
        d["explorer_link"] = f"{cfg['explorer']}/tx/{tx_hash}" if cfg.get("explorer") and tx_hash else None
        to_chain = d.get("to_chain_id")
        to_cfg = CHAIN_CONFIG.get(to_chain, {})
        d["from_chain_name"] = cfg.get("name", "")
        d["to_chain_name"] = to_cfg.get("name", "")
    return deposits


@router.get("/summary")
async def get_user_deposit_summary(
    user_address: str = Query(..., description="User wallet address"),
):
    return await database.get_user_deposit_summary(user_address)
