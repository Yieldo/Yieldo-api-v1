from web3 import Web3
from fastapi import APIRouter, HTTPException, Request
from app.models import (
    QuoteRequest,
    QuoteResponse,
    QuoteEstimate,
    StepDetail,
    ApprovalData,
    BuildRequest,
    BuildResponse,
    TransactionRequest,
    TrackingInfo,
    DepositStep,
    RouteOption,
)
from app.core.constants import (
    CROSS_CHAIN_SLIPPAGE_BUFFER,
    NON_COMPOSER_CROSS_CHAIN_BUFFER,
    DEPOSIT_ROUTER_ADDRESSES,
)
from app.services.vault import get_vault, get_vault_response
from app.services.rpc import get_vault_share_price, encode_deposit_for_calldata
from app.services import lifi
from app.services import database
from app.routes.partners import get_partner_from_api_key


router = APIRouter(prefix="/v1/quote", tags=["quote"])

NATIVE_TOKEN_ADDRESSES = {
    "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "0x0000000000000000000000000000000000000000",
}


def _is_native_token(address: str) -> bool:
    return address.lower() in NATIVE_TOKEN_ADDRESSES


def _compute_shares(deposit_amount: int, total_assets: int, total_supply: int) -> int | None:
    if total_supply == 0 or total_assets == 0:
        return None
    shares_per_asset = (total_supply * 10**18) // total_assets
    return (deposit_amount * shares_per_asset) // 10**18


def _partner_id_bytes(partner_id: str) -> bytes:
    if not partner_id:
        return b"\x00" * 32
    return Web3.keccak(text=partner_id)


@router.post("", response_model=QuoteResponse)
async def get_quote(req: QuoteRequest, request: Request):
    partner = await get_partner_from_api_key(request)
    if partner:
        referrer = partner.get("fee_collector_address", partner["address"])
        req.referrer = referrer
        enrolled = partner.get("enrolled_vaults", [])
        if enrolled and req.vault_id not in enrolled:
            raise HTTPException(status_code=403, detail=f"Vault {req.vault_id} not in your enrolled vaults")

    vault = get_vault(req.vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Vault {req.vault_id} not found")

    if vault.get("type") == "unsupported":
        raise HTTPException(status_code=400, detail=f"Vault {vault['name']} does not support deposits through our router. Please deposit directly on the protocol's website.")

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

    try:
        total_assets, total_supply = get_vault_share_price(to_chain, vault["address"])
    except Exception:
        total_assets, total_supply = 0, 0

    min_deposit = int(vault["min_deposit"]) if vault.get("min_deposit") else 0

    if is_direct:
        if min_deposit and from_amount_int < min_deposit:
            raise HTTPException(status_code=400, detail=f"Minimum deposit is {min_deposit / (10 ** vault['asset_decimals']):g} {vault['asset_symbol'].upper()}")
        estimated_shares = _compute_shares(from_amount_int, total_assets, total_supply)
        response = QuoteResponse(
            quote_type=quote_type,
            vault=get_vault_response(req.vault_id),
            estimate=QuoteEstimate(
                from_amount=req.from_amount,
                to_amount=req.from_amount,
                to_amount_min=req.from_amount,
                deposit_amount=req.from_amount,
                estimated_shares=str(estimated_shares) if estimated_shares else None,
            ),
            approval=ApprovalData(
                token_address=to_token,
                spender_address=deposit_router,
                amount=req.from_amount,
            ),
        )
        await database.save_quote(req.model_dump(), response.model_dump())
        if partner:
            await database.save_partner_transaction(
                partner["address"], req.user_address, req.vault_id,
                req.from_chain_id, req.from_amount, quote_type, "0",
            )
        return response

    lifi_quote = await lifi.get_quote(
        req.from_chain_id, req.from_token, req.from_amount,
        to_chain, to_token, req.user_address, req.slippage,
    )
    if not lifi_quote:
        raise HTTPException(status_code=400, detail="No route found for this token/chain combination")

    to_amount, to_amount_min = lifi.extract_quote_amounts(lifi_quote)
    to_amount_int = int(to_amount)
    to_amount_min_int = int(to_amount_min)

    if to_amount_int == 0:
        raise HTTPException(status_code=400, detail="LiFi returned zero output amount")

    if min_deposit and to_amount_min_int < min_deposit:
        human = min_deposit / (10 ** vault["asset_decimals"])
        raise HTTPException(status_code=400, detail=f"Minimum deposit is {human:g} {vault['asset_symbol'].upper()} — increase your input amount.")

    route_options = None
    if not is_same_chain:
        routes = await lifi.get_routes(
            req.from_chain_id, req.from_token, req.from_amount,
            to_chain, to_token, req.user_address, req.slippage,
        )
        options = []
        if routes:
            best_to_amount = max(int(r.get("toAmount", "0")) for r in routes)
            viable = [r for r in routes if int(r.get("toAmount", "0")) > best_to_amount * 0.5]
            for r in viable:
                info = lifi.extract_route_info(r)
                r_to_amount = int(info["to_amount"])
                options.append(RouteOption(
                    bridge=info["bridge"],
                    bridge_name=info["bridge_name"],
                    bridge_logo=info["bridge_logo"],
                    to_amount=info["to_amount"],
                    to_amount_min=info["to_amount_min"],
                    deposit_amount=info["to_amount"],
                    estimated_time=info["estimated_time"],
                    gas_cost_usd=info["gas_cost_usd"],
                    tags=info["tags"],
                ))

        main_bridge = lifi.extract_bridge_from_quote(lifi_quote)
        if main_bridge and not any(o.bridge == main_bridge for o in options):
            meta = lifi.extract_quote_metadata(lifi_quote)
            main_td = lifi_quote.get("toolDetails", {})
            options.insert(0, RouteOption(
                bridge=main_bridge,
                bridge_name=main_td.get("name") or main_bridge,
                bridge_logo=main_td.get("logoURI"),
                to_amount=to_amount,
                to_amount_min=to_amount_min,
                deposit_amount=to_amount,
                estimated_time=meta.get("estimated_time"),
                gas_cost_usd=meta.get("gas_cost_usd"),
                tags=["RECOMMENDED", "CHEAPEST"],
            ))

        if options:
            route_options = options

    estimated_shares = _compute_shares(to_amount_int, total_assets, total_supply)
    meta = lifi.extract_quote_metadata(lifi_quote)
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
            deposit_amount=str(to_amount_int),
            estimated_shares=str(estimated_shares) if estimated_shares else None,
            price_impact=meta.get("price_impact"),
            estimated_time=meta.get("estimated_time"),
            gas_cost_usd=meta.get("gas_cost_usd"),
            steps=steps,
        ),
        approval=None if _is_native_token(req.from_token) else ApprovalData(
            token_address=req.from_token,
            spender_address=approval_target,
            amount=req.from_amount,
        ),
        route_options=route_options,
    )
    await database.save_quote(req.model_dump(), response.model_dump())
    if partner:
        await database.save_partner_transaction(
            partner["address"], req.user_address, req.vault_id,
            req.from_chain_id, req.from_amount, quote_type, "0",
        )
    return response


@router.post("/build", response_model=BuildResponse)
async def build_transaction(req: BuildRequest, request: Request):
    partner = await get_partner_from_api_key(request)
    if partner:
        req.referrer = partner.get("fee_collector_address", partner["address"])

    vault = get_vault(req.vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Vault {req.vault_id} not found")

    if vault.get("type") == "unsupported":
        raise HTTPException(status_code=400, detail=f"Vault {vault['name']} does not support deposits through our router.")

    to_chain = vault["chain_id"]
    to_token = vault["asset_address"]
    deposit_router = vault["deposit_router"]
    is_same_chain = req.from_chain_id == to_chain
    is_same_token = req.from_token.lower() == to_token.lower()
    is_direct = is_same_chain and is_same_token
    from_amount_int = int(req.from_amount)

    vault_type = vault.get("type", "morpho")
    is_erc4626 = vault_type in ("morpho", "ipor", "accountable")
    NON_COMPOSER_TYPES = ("midas", "veda", "custom", "ipor", "lido")
    force_two_step = vault_type in NON_COMPOSER_TYPES
    deposit_gas_limit = "900000" if vault_type in ("midas", "veda", "ipor", "lido") else "500000"

    partner_id = _partner_id_bytes(req.partner_id)
    partner_type = req.partner_type

    if is_direct:
        calldata = encode_deposit_for_calldata(
            to_chain, vault["address"], to_token, from_amount_int,
            req.user_address, partner_id, partner_type, is_erc4626,
        )
        response = BuildResponse(
            transaction_request=TransactionRequest(
                to=deposit_router,
                data=calldata,
                value="0",
                chain_id=to_chain,
                gas_limit=deposit_gas_limit,
            ),
            approval=ApprovalData(
                token_address=to_token,
                spender_address=deposit_router,
                amount=req.from_amount,
            ),
            tracking=TrackingInfo(from_chain_id=to_chain, to_chain_id=to_chain),
        )
        tracking_id = await database.save_transaction(
            req.model_dump(), response.model_dump(),
            vault_name=vault["name"],
            referrer=req.referrer,
            referrer_handle=req.referrer_handle,
            quote_type="direct",
        )
        response.tracking_id = tracking_id
        return response

    allowed_bridges = [req.preferred_bridge] if req.preferred_bridge else None
    lifi_quote = await lifi.get_quote(
        req.from_chain_id, req.from_token, req.from_amount,
        to_chain, to_token, req.user_address, req.slippage,
        allowed_bridges=allowed_bridges,
    )
    if not lifi_quote and allowed_bridges:
        lifi_quote = await lifi.get_quote(
            req.from_chain_id, req.from_token, req.from_amount,
            to_chain, to_token, req.user_address, req.slippage,
        )
    if not lifi_quote:
        raise HTTPException(status_code=400, detail="No route found")

    bridge = lifi.extract_bridge_from_quote(lifi_quote)

    cc_quote = None
    if not force_two_step:
        to_amount, to_amount_min = lifi.extract_quote_amounts(lifi_quote)
        # CRITICAL: LiFi's Executor sets `_swapData.fromAmount` to the *actual* bridge delivery
        # but does NOT patch our calldata's `amount` parameter. Our depositFor calls
        # transferFrom(Executor, Router, amount) — if amount > actual delivery the call
        # reverts and LiFi refunds as PARTIAL. LiFi's quoted `toAmountMin` is unreliable for
        # this — Across in particular often reports toAmountMin == toAmount even though actual
        # delivery is 0.3-0.7% lower due to relayer fees. We apply a fixed 2% buffer below
        # LiFi's optimistic to_amount; any dust left on Executor is swept back to the user
        # by LiFi's tx-end refund logic.
        COMPOSER_BUFFER_BPS = 200  # 2.00% — covers Across LP + relayer fee + small slip
        safe_amount = int(int(to_amount) * (10000 - COMPOSER_BUFFER_BPS) // 10000)
        cc_amount = str(safe_amount)
        cc_calldata = encode_deposit_for_calldata(
            to_chain, vault["address"], to_token, safe_amount,
            req.user_address, partner_id, partner_type, is_erc4626,
        )
        cc_quote = await lifi.get_contract_calls_quote(
            req.from_chain_id, req.from_token, req.from_amount,
            to_chain, to_token, req.user_address,
            deposit_router, cc_calldata, cc_amount,
            preferred_bridges=[bridge] if bridge else None,
            slippage=req.slippage,
        )
    use_two_step = cc_quote is None

    if use_two_step:
        tx_req = lifi_quote.get("transactionRequest", {})
        if not tx_req:
            raise HTTPException(status_code=400, detail="No bridge route found")
        approval_target = tx_req.get("to", "")

        to_amount, to_amount_min = lifi.extract_quote_amounts(lifi_quote)
        # Conservative amount so the user's step-2 transferFrom succeeds even if the bridge
        # delivered less than the optimistic to_amount.
        dep_amount = to_amount_min if to_amount_min and int(to_amount_min) > 0 else to_amount
        dep_calldata = encode_deposit_for_calldata(
            to_chain, vault["address"], to_token, int(dep_amount),
            req.user_address, partner_id, partner_type, is_erc4626,
        )

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
            tracking=TrackingInfo(
                from_chain_id=req.from_chain_id,
                to_chain_id=to_chain,
                bridge=bridge,
                lifi_explorer="https://explorer.li.fi",
            ),
            two_step=True,
            deposit_tx=DepositStep(
                transaction_request=TransactionRequest(
                    to=deposit_router,
                    data=dep_calldata,
                    value="0",
                    chain_id=to_chain,
                    gas_limit=deposit_gas_limit,
                ),
                approval=ApprovalData(
                    token_address=to_token,
                    spender_address=deposit_router,
                    amount=str(int(dep_amount)),
                ),
            ),
        )
    else:
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
            tracking=TrackingInfo(
                from_chain_id=req.from_chain_id,
                to_chain_id=to_chain,
                bridge=used_bridge,
                lifi_explorer="https://explorer.li.fi",
            ),
        )
    quote_type = "cross_chain" if req.from_chain_id != to_chain else "same_chain_swap"
    tracking_id = await database.save_transaction(
        req.model_dump(), response.model_dump(),
        vault_name=vault["name"],
        referrer=req.referrer,
        referrer_handle=req.referrer_handle,
        quote_type=quote_type,
    )
    response.tracking_id = tracking_id
    return response
