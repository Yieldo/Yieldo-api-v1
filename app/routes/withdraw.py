import time
from fastapi import APIRouter, HTTPException

from app.models import (
    WithdrawQuoteRequest, WithdrawQuoteResponse, WithdrawIntentData,
    WithdrawBuildRequest, WithdrawBuildResponse,
    TransactionRequest, ApprovalData, EIP712Data, EIP712Domain,
)
from app.core.constants import EIP712_DOMAIN_NAME, EIP712_DOMAIN_VERSION, EIP712_TYPES
from app.config import get_settings
from app.services.rpc import (
    get_nonce, sign_withdraw_intent, encode_withdraw_calldata,
    encode_claim_calldata, get_erc20_balance,
)
from app.core.constants import DEPOSIT_ROUTER_ADDRESSES
from app.services.vault import get_vault, get_vault_response
from app.services import database

router = APIRouter(prefix="/v1/withdraw", tags=["withdraw"])

ASYNC_TYPES = {"veda"}  # vaults that always use async request (not supported yet — return error)


def _eip712_withdraw(intent: WithdrawIntentData, chain_id: int, router_address: str) -> EIP712Data:
    return EIP712Data(
        domain=EIP712Domain(
            name=EIP712_DOMAIN_NAME, version=EIP712_DOMAIN_VERSION,
            chainId=chain_id, verifyingContract=router_address,
        ),
        types={"WithdrawIntent": EIP712_TYPES["WithdrawIntent"]},
        primaryType="WithdrawIntent",
        message={
            "user": intent.user, "vault": intent.vault, "asset": intent.asset,
            "shares": intent.shares, "minAmountOut": intent.min_amount_out,
            "nonce": intent.nonce, "deadline": intent.deadline,
        },
    )


def _pick_mode(vault_type: str) -> str:
    # Midas: try sync first (redeemInstant); if instant liquidity is exhausted,
    # frontend retries in async mode. For Morpho/Custom: always sync. Veda: async-only.
    if vault_type in ("morpho", "custom"):
        return "sync"
    if vault_type == "midas":
        return "sync"  # default; caller may request async
    if vault_type == "veda":
        return "async"
    return "sync"


@router.post("/quote", response_model=WithdrawQuoteResponse)
async def withdraw_quote(req: WithdrawQuoteRequest):
    vault = get_vault(req.vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Vault {req.vault_id} not found")
    if vault.get("type") == "unsupported":
        raise HTTPException(status_code=400, detail=f"Vault {vault['name']} not supported")

    vault_type = vault.get("type", "morpho")
    if vault_type in ASYNC_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Withdrawals for {vault['name']} must be done via the protocol's website.",
        )

    to_chain = vault["chain_id"]
    asset = vault["asset_address"]
    vault_addr = vault["address"]
    deposit_router = vault["deposit_router"]
    shares = int(req.shares)
    if shares <= 0:
        raise HTTPException(status_code=400, detail="shares must be > 0")

    # Slippage protection: min assets = shares * pricePerShare * (1 - slippage)
    # Pull price-per-share via vault.convertToAssets; fall back to 0 if unavailable (no protection).
    from app.services.rpc import get_vault_convert_to_assets
    try:
        est_assets = get_vault_convert_to_assets(to_chain, vault_addr, shares)
    except Exception:
        est_assets = 0
    min_amount_out = int(est_assets * (1 - req.slippage)) if est_assets > 0 else 0

    settings = get_settings()
    deadline = int(time.time()) + settings.intent_deadline_seconds
    nonce = get_nonce(to_chain, req.user_address)
    mode = _pick_mode(vault_type)

    sig = sign_withdraw_intent(
        to_chain, deposit_router, req.user_address, vault_addr, asset,
        shares, min_amount_out, nonce, deadline,
    )

    intent = WithdrawIntentData(
        user=req.user_address, vault=vault_addr, asset=asset,
        shares=str(shares), min_amount_out=str(min_amount_out),
        nonce=str(nonce), deadline=str(deadline),
    )

    return WithdrawQuoteResponse(
        vault=get_vault_response(req.vault_id),
        mode=mode,
        shares=str(shares),
        estimated_assets=str(est_assets) if est_assets > 0 else None,
        min_amount_out=str(min_amount_out),
        intent=intent,
        eip712=_eip712_withdraw(intent, to_chain, deposit_router),
        signature=sig,
        approval=ApprovalData(
            token_address=vault_addr,
            spender_address=deposit_router,
            amount=str(shares),
        ),
    )


@router.post("/build", response_model=WithdrawBuildResponse)
async def withdraw_build(req: WithdrawBuildRequest):
    vault = get_vault(req.vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Vault {req.vault_id} not found")
    vault_type = vault.get("type", "morpho")
    if vault_type in ASYNC_TYPES:
        raise HTTPException(status_code=400, detail="Async-only vaults not supported via router")

    to_chain = vault["chain_id"]
    asset = vault["asset_address"]
    vault_addr = vault["address"]
    deposit_router = vault["deposit_router"]
    sig_bytes = bytes.fromhex(req.signature.replace("0x", ""))

    if req.mode not in ("sync", "async"):
        raise HTTPException(status_code=400, detail="mode must be sync or async")

    fn = "withdrawWithIntent" if req.mode == "sync" else "withdrawRequestWithIntent"
    calldata = encode_withdraw_calldata(
        to_chain, fn, req.user_address, vault_addr, asset,
        int(req.shares), int(req.min_amount_out), int(req.nonce), int(req.deadline),
        sig_bytes,
    )

    # Midas withdraw path (sync redeemInstant or async request) both touch Midas's RV — budget
    # matches deposit path; others fit in 500k.
    gas_limit = "900000" if vault_type in ("midas", "veda") else "500000"

    resp = WithdrawBuildResponse(
        transaction_request=TransactionRequest(
            to=deposit_router, data=calldata, value="0",
            chain_id=to_chain, gas_limit=gas_limit,
        ),
        approval=ApprovalData(
            token_address=vault_addr,
            spender_address=deposit_router,
            amount=str(req.shares),
        ),
        mode=req.mode,
    )
    resp.tracking_id = await database.save_withdraw(
        user=req.user_address, vault_id=req.vault_id, vault_name=vault["name"],
        shares=req.shares, asset=asset, mode=req.mode, chain_id=to_chain,
    )
    return resp


@router.get("/requests/{user_address}")
async def get_pending_requests(user_address: str):
    """Return async withdraw requests this user has submitted through Yieldo.
    Each entry is decorated with a live `claimable` flag determined by checking
    whether the request's escrow has received the asset from the protocol yet."""
    rows = await database.get_user_withdraw_requests(user_address)
    for r in rows:
        if r.get("status") == "claimed":
            r["claimable"] = False
            continue
        escrow = r.get("escrow_address")
        asset = r.get("asset")
        chain_id = r.get("chain_id")
        if not escrow or not asset or not chain_id:
            r["claimable"] = False
            continue
        try:
            bal = get_erc20_balance(chain_id, asset, escrow)
            r["claimable"] = bal > 0
            r["claimable_amount"] = str(bal)
        except Exception:
            r["claimable"] = False
    return rows


@router.get("/claim-tx/{req_hash}")
async def get_claim_tx(req_hash: str, user_address: str):
    """Build the claim transaction for a ready async request. Returns ready=false
    if the protocol hasn't fulfilled yet, so the UI can keep the Claim button
    disabled rather than let the user send a tx that would revert."""
    row = await database.get_withdraw_by_req_hash(req_hash)
    if not row or row.get("user", "").lower() != user_address.lower():
        raise HTTPException(status_code=404, detail="Request not found")
    if row.get("status") == "claimed":
        return {"ready": False, "reason": "Already claimed"}
    escrow = row.get("escrow_address")
    asset = row.get("asset")
    chain_id = row.get("chain_id")
    if not escrow or not asset:
        return {"ready": False, "reason": "Missing escrow info"}
    bal = get_erc20_balance(chain_id, asset, escrow)
    if bal == 0:
        return {"ready": False, "reason": "Protocol has not fulfilled yet"}
    router_addr = DEPOSIT_ROUTER_ADDRESSES.get(chain_id)
    calldata = encode_claim_calldata(chain_id, bytes.fromhex(req_hash.replace("0x", "")))
    return {
        "ready": True,
        "amount": str(bal),
        "transaction_request": {
            "to": router_addr, "data": calldata, "value": "0",
            "chain_id": chain_id, "gas_limit": "250000",
        },
    }
