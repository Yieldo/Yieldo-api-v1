import time
from fastapi import APIRouter, HTTPException
from app.models import (
    QuoteRequest,
    QuoteResponse,
    QuoteEstimate,
    StepDetail,
    IntentData,
    EIP712Data,
    EIP712Domain,
    ApprovalData,
    BuildRequest,
    BuildResponse,
    TransactionRequest,
    TrackingInfo,
)
from app.core.constants import (
    FEE_BPS,
    CROSS_CHAIN_SLIPPAGE_BUFFER,
    DEPOSIT_ROUTER_ADDRESSES,
    EIP712_DOMAIN_NAME,
    EIP712_DOMAIN_VERSION,
    EIP712_TYPES,
)
from app.config import get_settings
from app.services.vault import get_vault, get_vault_response
from app.services.rpc import get_nonce, encode_deposit_calldata, get_vault_share_price
from app.services import lifi
from app.services import database
from app.services.pyth import get_price_update, get_pyth_update_fee


router = APIRouter(prefix="/v1/quote", tags=["quote"])

PLACEHOLDER_SIGNATURE = b"\x00" * 65

NATIVE_TOKEN_ADDRESSES = {
    "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "0x0000000000000000000000000000000000000000",
}


def _is_native_token(address: str) -> bool:
    return address.lower() in NATIVE_TOKEN_ADDRESSES


def _compute_fee(amount: int) -> int:
    return (amount * FEE_BPS) // 10000


def _compute_shares(deposit_amount: int, total_assets: int, total_supply: int) -> int | None:
    if total_supply == 0 or total_assets == 0:
        return None
    shares_per_asset = (total_supply * 10**18) // total_assets
    return (deposit_amount * shares_per_asset) // 10**18


@router.post("", response_model=QuoteResponse)
async def get_quote(req: QuoteRequest):
    vault = get_vault(req.vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Vault {req.vault_id} not found")

    to_chain = vault["chain_id"]
    to_token = vault["asset_address"]
    deposit_router = vault["deposit_router"]
    is_same_chain = req.from_chain_id == to_chain
    is_same_token = req.from_token.lower() == to_token.lower()
    is_direct = is_same_chain and is_same_token

    if is_direct:
        quote_type = "direct"
    elif is_same_chain:
        quote_type = "same_chain_swap"
    else:
        quote_type = "cross_chain"

    from_amount_int = int(req.from_amount)
    settings = get_settings()
    deadline = int(time.time()) + settings.intent_deadline_seconds
    nonce = get_nonce(to_chain, req.user_address)

    try:
        total_assets, total_supply = get_vault_share_price(to_chain, vault["address"])
    except Exception:
        total_assets, total_supply = 0, 0

    if is_direct:
        fee = _compute_fee(from_amount_int)
        deposit_amount = from_amount_int - fee
        estimated_shares = _compute_shares(deposit_amount, total_assets, total_supply)
        intent = IntentData(
            user=req.user_address,
            vault=vault["address"],
            asset=to_token,
            amount=req.from_amount,
            nonce=str(nonce),
            deadline=str(deadline),
        )
        response = QuoteResponse(
            quote_type=quote_type,
            vault=get_vault_response(req.vault_id),
            estimate=QuoteEstimate(
                from_amount=req.from_amount,
                to_amount=req.from_amount,
                to_amount_min=req.from_amount,
                deposit_amount=str(deposit_amount),
                fee_amount=str(fee),
                estimated_shares=str(estimated_shares) if estimated_shares else None,
            ),
            intent=intent,
            eip712=_build_eip712(intent, to_chain, deposit_router),
            approval=ApprovalData(
                token_address=to_token,
                spender_address=deposit_router,
                amount=req.from_amount,
            ),
        )
        await database.save_quote(req.model_dump(), response.model_dump())
        return response

    lifi_quote = await lifi.get_quote(
        req.from_chain_id,
        req.from_token,
        req.from_amount,
        to_chain,
        to_token,
        req.user_address,
        req.slippage,
    )
    if not lifi_quote:
        raise HTTPException(status_code=400, detail="No route found for this token/chain combination")

    to_amount, to_amount_min = lifi.extract_quote_amounts(lifi_quote)
    to_amount_int = int(to_amount)
    to_amount_min_int = int(to_amount_min)

    if to_amount_int == 0:
        raise HTTPException(status_code=400, detail="LiFi returned zero output amount")

    fee = _compute_fee(to_amount_int)
    deposit_amount = to_amount_int - fee

    if not is_same_chain:
        intent_amount = int(int(to_amount_min) * CROSS_CHAIN_SLIPPAGE_BUFFER)
    else:
        intent_amount = to_amount_min_int

    estimated_shares = _compute_shares(deposit_amount, total_assets, total_supply)
    meta = lifi.extract_quote_metadata(lifi_quote)

    intent = IntentData(
        user=req.user_address,
        vault=vault["address"],
        asset=to_token,
        amount=str(intent_amount),
        nonce=str(nonce),
        deadline=str(deadline),
    )

    steps = [StepDetail(**s) for s in meta.get("steps", [])] if meta.get("steps") else None

    approval_target = lifi_quote.get("transactionRequest", {}).get("to") or deposit_router

    response = QuoteResponse(
        quote_type=quote_type,
        vault=get_vault_response(req.vault_id),
        estimate=QuoteEstimate(
            from_amount=req.from_amount,
            from_amount_usd=meta.get("from_amount_usd"),
            to_amount=to_amount,
            to_amount_min=to_amount_min,
            deposit_amount=str(deposit_amount),
            fee_amount=str(fee),
            estimated_shares=str(estimated_shares) if estimated_shares else None,
            price_impact=meta.get("price_impact"),
            estimated_time=meta.get("estimated_time"),
            gas_cost_usd=meta.get("gas_cost_usd"),
            steps=steps,
        ),
        intent=intent,
        eip712=_build_eip712(intent, to_chain, deposit_router),
        approval=None if _is_native_token(req.from_token) else ApprovalData(
            token_address=req.from_token,
            spender_address=approval_target,
            amount=req.from_amount,
        ),
    )
    await database.save_quote(req.model_dump(), response.model_dump())
    return response


@router.post("/build", response_model=BuildResponse)
async def build_transaction(req: BuildRequest):
    vault = get_vault(req.vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Vault {req.vault_id} not found")

    to_chain = vault["chain_id"]
    to_token = vault["asset_address"]
    deposit_router = vault["deposit_router"]
    is_same_chain = req.from_chain_id == to_chain
    is_same_token = req.from_token.lower() == to_token.lower()
    is_direct = is_same_chain and is_same_token

    # Use the EXACT values the user signed — never recompute these
    nonce = int(req.nonce)
    deadline = int(req.deadline)
    intent_amount = int(req.intent_amount)
    sig_bytes = bytes.fromhex(req.signature.replace("0x", ""))

    if is_direct:
        fn_name = "depositWithIntentERC4626"
        calldata = encode_deposit_calldata(
            to_chain, fn_name, req.user_address, vault["address"],
            to_token, intent_amount, nonce, deadline,
            sig_bytes, req.referrer,
        )
        response = BuildResponse(
            transaction_request=TransactionRequest(
                to=deposit_router,
                data=calldata,
                value="0",
                chain_id=to_chain,
                gas_limit="500000",
            ),
            approval=ApprovalData(
                token_address=to_token,
                spender_address=deposit_router,
                amount=req.from_amount,
            ),
            intent=IntentData(
                user=req.user_address, vault=vault["address"], asset=to_token,
                amount=str(intent_amount), nonce=str(nonce), deadline=str(deadline),
            ),
            tracking=TrackingInfo(from_chain_id=to_chain, to_chain_id=to_chain),
        )
        tracking_id = await database.save_transaction(req.model_dump(), response.model_dump())
        response.tracking_id = tracking_id
        return response

    lifi_quote = await lifi.get_quote(
        req.from_chain_id, req.from_token, req.from_amount,
        to_chain, to_token, req.user_address, req.slippage,
    )
    if not lifi_quote:
        raise HTTPException(status_code=400, detail="No route found")

    price_update = get_price_update(to_token)
    pyth_fee = get_pyth_update_fee(to_chain, price_update)

    fn_name = "depositWithIntentCrossChainERC4626"
    calldata = encode_deposit_calldata(
        to_chain, fn_name, req.user_address, vault["address"],
        to_token, intent_amount, nonce, deadline,
        sig_bytes, req.referrer, price_update,
    )

    contract_call_amount = str(intent_amount)

    bridge = lifi.extract_bridge_from_quote(lifi_quote)
    preferred = [bridge] if bridge else None

    cc_quote = await lifi.get_contract_calls_quote(
        req.from_chain_id, req.from_token, req.from_amount,
        to_chain, to_token, req.user_address,
        deposit_router, calldata, contract_call_amount,
        preferred_bridges=preferred,
        slippage=req.slippage,
    )

    if not cc_quote:
        raise HTTPException(
            status_code=400,
            detail="LiFi contract calls quote unavailable for this route. Use fallback flow.",
        )

    tx_req = cc_quote["transactionRequest"]
    approval_target = tx_req.get("to", deposit_router)
    used_bridge = lifi.extract_bridge_from_quote(cc_quote)

    response = BuildResponse(
        transaction_request=TransactionRequest(
            to=tx_req["to"],
            data=tx_req["data"],
            value=str(tx_req.get("value", "0")),
            chain_id=req.from_chain_id,
            gas_limit=tx_req.get("gasLimit"),
        ),
        approval=None if _is_native_token(req.from_token) else ApprovalData(
            token_address=req.from_token,
            spender_address=approval_target,
            amount=req.from_amount,
        ),
        intent=IntentData(
            user=req.user_address, vault=vault["address"], asset=to_token,
            amount=str(intent_amount), nonce=str(nonce), deadline=str(deadline),
        ),
        tracking=TrackingInfo(
            from_chain_id=req.from_chain_id,
            to_chain_id=to_chain,
            bridge=used_bridge,
            lifi_explorer=f"https://explorer.li.fi",
        ),
    )
    tracking_id = await database.save_transaction(req.model_dump(), response.model_dump())
    response.tracking_id = tracking_id
    return response


def _build_eip712(intent: IntentData, chain_id: int, router_address: str) -> EIP712Data:
    return EIP712Data(
        domain=EIP712Domain(
            name=EIP712_DOMAIN_NAME,
            version=EIP712_DOMAIN_VERSION,
            chainId=chain_id,
            verifyingContract=router_address,
        ),
        types=EIP712_TYPES,
        message=intent,
    )
