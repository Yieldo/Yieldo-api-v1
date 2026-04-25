from fastapi import APIRouter, HTTPException, Query
from app.models import StatusResponse, SendingInfo, ReceivingInfo
from app.core.constants import CHAIN_CONFIG, DEPOSIT_ROUTER_ADDRESSES
from app.services import lifi
from app.services import database
from app.services.rpc import get_w3

_LIFI_STATUS_MAP = {
    "DONE": "completed",
    "FAILED": "failed",
    "PENDING": "submitted",
    "NOT_FOUND": "submitted",
}

# When LiFi reports DONE but with these substatuses, treat as partial — bridge
# delivered but the destination action (swap/deposit) didn't complete and the
# user got refunded the source asset on the destination chain.
_LIFI_PARTIAL_SUBSTATUSES = {"PARTIAL", "REFUNDED"}

router = APIRouter(prefix="/v1", tags=["status"])


def _tx_link(chain_id: int, tx_hash: str) -> str | None:
    cfg = CHAIN_CONFIG.get(chain_id)
    if not cfg:
        return None
    return f"{cfg['explorer']}/tx/{tx_hash}"


def _onchain_status(chain_id: int, tx_hash: str) -> str | None:
    """Read the receipt for a tx and return 'completed' (status 0x1),
    'failed' (0x0), or None if not yet mined / unreachable."""
    try:
        w3 = get_w3(chain_id)
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt is None:
            return None
        # web3.py returns int 0/1 in `status`
        return "completed" if int(receipt.get("status", 0)) == 1 else "failed"
    except Exception:
        return None


@router.get("/status", response_model=StatusResponse)
async def get_transfer_status(
    tx_hash: str = Query(..., description="Source chain transaction hash"),
    from_chain_id: int = Query(..., description="Source chain ID"),
    to_chain_id: int = Query(..., description="Destination chain ID"),
):
    # Same-chain: skip LiFi entirely (it doesn't index non-LiFi same-chain txs
    # and would just return PENDING/NOT_FOUND forever). Read the on-chain receipt.
    if from_chain_id == to_chain_id:
        oc = _onchain_status(from_chain_id, tx_hash)
        cfg = CHAIN_CONFIG.get(from_chain_id, {})
        link = f"{cfg.get('explorer','')}/tx/{tx_hash}" if cfg.get("explorer") else None
        if oc:
            await database.update_transaction_status(tx_hash, from_chain_id, oc,
                extra_fields={"lifi_explorer": None})
            return StatusResponse(
                status="DONE" if oc == "completed" else "FAILED",
                substatus="COMPLETED" if oc == "completed" else None,
                sending=SendingInfo(tx_hash=tx_hash, tx_link=link, chain_id=from_chain_id) if link else None,
                receiving=None, bridge=None, lifi_explorer=None,
            )
        return StatusResponse(status="PENDING", sending=None, receiving=None, bridge=None, lifi_explorer=None)

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
    # Always surface the destination receipt when LiFi knows it — for COMPLETED
    # cross-chain deposits this is the link to the vault deposit / share mint
    # on the dest chain (what the user actually wants to verify), and for
    # PARTIAL/REFUNDED it's the refund tx with the received token/amount.
    if r and r.get("txHash"):
        extra["dest_tx_hash"] = r.get("txHash")
        extra["dest_chain_id"] = to_chain_id
    if status == "DONE" and substatus in _LIFI_PARTIAL_SUBSTATUSES:
        db_status = "partial"
        if r:
            extra["received_token"] = (r.get("token") or {}).get("address")
            extra["received_amount"] = r.get("amount")
    await database.update_transaction_status(tx_hash, from_chain_id, db_status, extra_fields=extra)

    return StatusResponse(
        status=status,
        substatus=substatus,
        sending=sending,
        receiving=receiving,
        bridge=bridge,
        lifi_explorer=lifi_explorer,
    )


