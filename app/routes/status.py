from fastapi import APIRouter, HTTPException, Query
from app.models import StatusResponse, SendingInfo, ReceivingInfo
from app.core.constants import CHAIN_CONFIG, DEPOSIT_ROUTER_ADDRESSES
from app.services import lifi
from app.services import database

_LIFI_STATUS_MAP = {
    "DONE": "completed",
    "FAILED": "failed",
    "PENDING": "submitted",
    "NOT_FOUND": "submitted",
}

router = APIRouter(prefix="/v1", tags=["status"])


def _tx_link(chain_id: int, tx_hash: str) -> str | None:
    cfg = CHAIN_CONFIG.get(chain_id)
    if not cfg:
        return None
    return f"{cfg['explorer']}/tx/{tx_hash}"


@router.get("/status", response_model=StatusResponse)
async def get_transfer_status(
    tx_hash: str = Query(..., description="Source chain transaction hash"),
    from_chain_id: int = Query(..., description="Source chain ID"),
    to_chain_id: int = Query(..., description="Destination chain ID"),
):
    data = await lifi.get_status(tx_hash, from_chain_id, to_chain_id)
    if not data:
        raise HTTPException(status_code=404, detail="Transaction not found")

    status = data.get("status", "NOT_FOUND")
    substatus = data.get("substatus")

    sending = None
    s = data.get("sending", {})
    if s:
        sending = SendingInfo(
            tx_hash=s.get("txHash"),
            tx_link=_tx_link(from_chain_id, s["txHash"]) if s.get("txHash") else None,
            amount=s.get("amount"),
            chain_id=from_chain_id,
        )

    receiving = None
    r = data.get("receiving", {})
    if r:
        receiving = ReceivingInfo(
            tx_hash=r.get("txHash"),
            tx_link=_tx_link(to_chain_id, r["txHash"]) if r.get("txHash") else None,
            amount=r.get("amount"),
            chain_id=to_chain_id,
        )

    bridge = data.get("tool") or lifi.extract_bridge_from_quote(data)
    lifi_explorer = f"https://explorer.li.fi/tx/{tx_hash}" if tx_hash else None

    db_status = _LIFI_STATUS_MAP.get(status, "submitted")
    extra = {"lifi_explorer": lifi_explorer}
    if bridge:
        extra["bridge"] = bridge
    await database.update_transaction_status(tx_hash, from_chain_id, db_status, extra_fields=extra)

    return StatusResponse(
        status=status,
        substatus=substatus,
        sending=sending,
        receiving=receiving,
        bridge=bridge,
        lifi_explorer=lifi_explorer,
    )


