from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.services import database
from app.core.constants import CHAIN_CONFIG

router = APIRouter(prefix="/v1/deposits", tags=["deposits"])


class DepositTxReport(BaseModel):
    tx_hash: str


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


@router.patch("/{tracking_id}/abandon")
async def abandon_deposit(tracking_id: str):
    """Mark a previously-built deposit as abandoned. Called when the user
    rejects the wallet prompt or otherwise never broadcasts. Without this the
    record sits in `pending` for the full 4h abandon timeout."""
    try:
        oid = ObjectId(tracking_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid tracking_id")
    res = await database.set_transaction_status_if_pending(oid, "abandoned")
    return {"ok": True, "updated": res, "tracking_id": tracking_id}


@router.patch("/{tracking_id}/tx")
async def report_deposit_tx(tracking_id: str, body: DepositTxReport):
    """Report the actual on-chain tx hash for a previously-built deposit.
    Closes the loop between /v1/quote/build (which saves the request before the
    tx exists) and /v1/status (which needs a tx_hash to fetch LiFi state).
    Without this, transactions stay `pending` forever in HistoryPage."""
    if not body.tx_hash:
        raise HTTPException(status_code=400, detail="tx_hash required")
    try:
        oid = ObjectId(tracking_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid tracking_id")
    res = await database.set_transaction_tx_hash(oid, body.tx_hash)
    if not res:
        raise HTTPException(status_code=404, detail="Tracking record not found")
    return {"ok": True, "tracking_id": tracking_id, "tx_hash": body.tx_hash}


@router.get("/summary")
async def get_user_deposit_summary(
    user_address: str = Query(..., description="User wallet address"),
):
    return await database.get_user_deposit_summary(user_address)
