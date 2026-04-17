import time
from fastapi import APIRouter, HTTPException, Request
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
    DepositStep,
    RouteOption,
)
from app.core.constants import (
    FEE_BPS,
    CROSS_CHAIN_SLIPPAGE_BUFFER,
    NON_COMPOSER_CROSS_CHAIN_BUFFER,
    DEPOSIT_ROUTER_ADDRESSES,
    EIP712_DOMAIN_NAME,
    EIP712_DOMAIN_VERSION,
    EIP712_TYPES,
)
from app.config import get_settings
from app.services.vault import get_vault, get_vault_response
from app.services.rpc import get_nonce, encode_deposit_calldata, get_vault_share_price, sign_intent
from app.services import lifi
from app.services import database
from app.services.pyth import get_price_update, get_pyth_update_fee
from app.routes.partners import get_partner_from_api_key


router = APIRouter(prefix="/v1/quote", tags=["quote"])

PLACEHOLDER_SIGNATURE = b"\x00" * 65

NATIVE_TOKEN_ADDRESSES = {
    "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "0x0000000000000000000000000000000000000000",
}


def _is_native_token(address: str) -> bool:
    return address.lower() in NATIVE_TOKEN_ADDRESSES


def _compute_fee(amount: int, fee_bps: int = FEE_BPS) -> int:
    return (amount * fee_bps) // 10000


def _compute_shares(deposit_amount: int, total_assets: int, total_supply: int) -> int | None:
    if total_supply == 0 or total_assets == 0:
        return None
    shares_per_asset = (total_supply * 10**18) // total_assets
    return (deposit_amount * shares_per_asset) // 10**18


@router.post("", response_model=QuoteResponse)
async def get_quote(req: QuoteRequest, request: Request):
    # Detect partner from API key headers
    partner = await get_partner_from_api_key(request)
    if partner:
        fee_bps = FEE_BPS if partner.get("fee_enabled", True) else 0
        referrer = partner.get("fee_collector_address", partner["address"])
        req.referrer = referrer
        # Enforce enrollment
        enrolled = partner.get("enrolled_vaults", [])
        if enrolled and req.vault_id not in enrolled:
            raise HTTPException(status_code=403, detail=f"Vault {req.vault_id} not in your enrolled vaults")
    elif req.referrer and req.referrer.lower() != "0x0000000000000000000000000000000000000000":
        # Referral flow: if the referrer resolves to a registered KOL, honor their fee_enabled.
        # Regular users without a KOL-linked referrer always pay FEE_BPS (below).
        kol = await database.get_kol_by_referrer(req.referrer)
        if kol and not kol.get("fee_enabled", True):
            fee_bps = 0
        else:
            fee_bps = FEE_BPS
    else:
        fee_bps = FEE_BPS

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
    settings = get_settings()
    deadline = int(time.time()) + settings.intent_deadline_seconds
    nonce = get_nonce(to_chain, req.user_address)

    try:
        total_assets, total_supply = get_vault_share_price(to_chain, vault["address"])
    except Exception:
        total_assets, total_supply = 0, 0

    min_deposit = int(vault["min_deposit"]) if vault.get("min_deposit") else 0

    if is_direct:
        fee = _compute_fee(from_amount_int, fee_bps)
        deposit_amount = from_amount_int - fee
        if min_deposit and deposit_amount < min_deposit:
            raise HTTPException(status_code=400, detail=f"Minimum deposit is {min_deposit / (10 ** vault['asset_decimals']):g} {vault['asset_symbol'].upper()}")
        estimated_shares = _compute_shares(deposit_amount, total_assets, total_supply)
        intent = IntentData(
            user=req.user_address,
            vault=vault["address"],
            asset=to_token,
            amount=req.from_amount,
            nonce=str(nonce),
            deadline=str(deadline),
            fee_bps=str(fee_bps),
        )
        sig = sign_intent(
            to_chain, deposit_router, req.user_address, vault["address"],
            to_token, from_amount_int, nonce, deadline, fee_bps,
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
            signature=sig,
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
                req.from_chain_id, req.from_amount, quote_type, str(fee),
            )
        return response

    # Fetch multiple routes for the user to choose from, plus a single best
    # quote (which includes transactionRequest for the approval target).
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

    fee = _compute_fee(to_amount_int, fee_bps)
    deposit_amount = to_amount_int - fee

    # Reject if worst-case post-bridge amount is below vault minimum — otherwise
    # the user pays bridge fees only to hit InsufficientAmount() on the vault.
    if min_deposit:
        worst_case_deposit = to_amount_min_int - _compute_fee(to_amount_min_int, fee_bps)
        if worst_case_deposit < min_deposit:
            human = min_deposit / (10 ** vault["asset_decimals"])
            raise HTTPException(status_code=400, detail=f"Minimum deposit is {human:g} {vault['asset_symbol'].upper()} — increase your input amount.")

    # Build route options from LiFi's multi-route endpoint (cross-chain only).
    # Same-chain swaps only have one DEX route so route selection isn't useful.
    route_options = None
    if not is_same_chain:
        routes = await lifi.get_routes(
            req.from_chain_id, req.from_token, req.from_amount,
            to_chain, to_token, req.user_address, req.slippage,
        )
        options = []
        if routes:
            best_to_amount = max(int(r.get("toAmount", "0")) for r in routes)
            # Filter out junk routes (output < 50% of best)
            viable = [r for r in routes if int(r.get("toAmount", "0")) > best_to_amount * 0.5]
            for r in viable:
                info = lifi.extract_route_info(r)
                r_to_amount = int(info["to_amount"])
                r_fee = _compute_fee(r_to_amount, fee_bps)
                options.append(RouteOption(
                    bridge=info["bridge"],
                    bridge_name=info["bridge_name"],
                    bridge_logo=info["bridge_logo"],
                    to_amount=info["to_amount"],
                    to_amount_min=info["to_amount_min"],
                    deposit_amount=str(r_to_amount - r_fee),
                    fee_amount=str(r_fee),
                    estimated_time=info["estimated_time"],
                    gas_cost_usd=info["gas_cost_usd"],
                    tags=info["tags"],
                ))

        # Ensure the main quote's bridge is always in route_options — the
        # /quote and /advanced/routes endpoints can return different bridges.
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
                deposit_amount=str(deposit_amount),
                fee_amount=str(fee),
                estimated_time=meta.get("estimated_time"),
                gas_cost_usd=meta.get("gas_cost_usd"),
                tags=["RECOMMENDED", "CHEAPEST"],
            ))

        if options:
            route_options = options

    if not is_same_chain:
        # Use worst-case to_amount_min across all shown routes for the intent.
        # This is safe because the router accepts any amount >= intent_amount.
        worst_min = to_amount_min_int
        if route_options:
            worst_min = min(worst_min, min(int(ro.to_amount_min) for ro in route_options))
        vault_type_for_buffer = vault.get("type", "morpho")
        buffer = NON_COMPOSER_CROSS_CHAIN_BUFFER if vault_type_for_buffer in ("midas", "veda", "custom") else CROSS_CHAIN_SLIPPAGE_BUFFER
        intent_amount = int(worst_min * buffer)
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
        fee_bps=str(fee_bps),
    )

    sig = sign_intent(
        to_chain, deposit_router, req.user_address, vault["address"],
        to_token, intent_amount, nonce, deadline, fee_bps,
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
        signature=sig,
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
            req.from_chain_id, req.from_amount, quote_type, str(fee),
        )
    return response


@router.post("/build", response_model=BuildResponse)
async def build_transaction(req: BuildRequest, request: Request):
    # Detect partner and override referrer
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

    # Use the EXACT values from the signed intent — never recompute these
    nonce = int(req.nonce)
    deadline = int(req.deadline)
    intent_amount = int(req.intent_amount)
    fee_bps = int(req.fee_bps)
    sig_bytes = bytes.fromhex(req.signature.replace("0x", ""))

    vault_type = vault.get("type", "morpho")
    # Router uses depositWithIntentERC4626 for types whose eventual vault.deposit
    # call follows the standard ERC-4626 `deposit(uint256, address)` shape. Lido
    # has its own custom adapter branch in the router — uses the non-ERC4626 path
    # through depositWithIntent so the router can route to the SyncDepositQueue.
    is_erc4626 = vault_type in ("morpho", "ipor", "accountable")
    # Vault types LiFi Composer does NOT support. Listed at docs.li.fi/composer.
    # Anything here is forced to two-step cross-chain routing — NEVER single-step.
    NON_COMPOSER_TYPES = ("midas", "veda", "custom", "ipor", "lido")
    force_two_step = vault_type in NON_COMPOSER_TYPES
    # Midas depositInstant ~= 625-700k; IPOR PlasmaVault ~= 550k; Lido SyncDepositQueue
    # ~= 500k including the handleReport share mint; Morpho/Custom fit in 500k.
    deposit_gas_limit = "900000" if vault_type in ("midas", "veda", "ipor", "lido") else "500000"

    if is_direct:
        fn_name = "depositWithIntentERC4626" if is_erc4626 else "depositWithIntent"
        calldata = encode_deposit_calldata(
            to_chain, fn_name, req.user_address, vault["address"],
            to_token, intent_amount, nonce, deadline, fee_bps,
            sig_bytes, req.referrer,
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
            intent=IntentData(
                user=req.user_address, vault=vault["address"], asset=to_token,
                amount=str(intent_amount), nonce=str(nonce), deadline=str(deadline),
                fee_bps=str(fee_bps),
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
    # If the preferred bridge can't build a tx (e.g. amount too small),
    # fall back to any available bridge.
    if not lifi_quote and allowed_bridges:
        lifi_quote = await lifi.get_quote(
            req.from_chain_id, req.from_token, req.from_amount,
            to_chain, to_token, req.user_address, req.slippage,
        )
    if not lifi_quote:
        raise HTTPException(status_code=400, detail="No route found")

    bridge = lifi.extract_bridge_from_quote(lifi_quote)

    # Decide routing. For protocols not on the LiFi Composer allowlist
    # (see docs.li.fi/composer — IPOR/Midas/Veda/Custom are all excluded),
    # we never attempt single-step: the composer call on destination is
    # prone to partial-fill failures that leave the user with a refunded
    # bridged token in their wallet instead of vault shares.
    cc_quote = None
    if not force_two_step:
        price_update = get_price_update(to_token)
        pyth_fee = get_pyth_update_fee(to_chain, price_update)
        fn_name = "depositWithIntentCrossChainERC4626" if is_erc4626 else "depositWithIntentCrossChain"
        cc_calldata = encode_deposit_calldata(
            to_chain, fn_name, req.user_address, vault["address"],
            to_token, intent_amount, nonce, deadline, fee_bps,
            sig_bytes, req.referrer, price_update,
        )
        cc_quote = await lifi.get_contract_calls_quote(
            req.from_chain_id, req.from_token, req.from_amount,
            to_chain, to_token, req.user_address,
            deposit_router, cc_calldata, str(intent_amount),
            preferred_bridges=[bridge] if bridge else None,
            slippage=req.slippage,
        )
    use_two_step = cc_quote is None

    if use_two_step:
        # Two-step: Step 1 = bridge to user wallet, Step 2 = same-chain deposit
        tx_req = lifi_quote.get("transactionRequest", {})
        if not tx_req:
            raise HTTPException(status_code=400, detail="No bridge route found")
        approval_target = tx_req.get("to", "")

        # Build step-2 deposit calldata (same-chain direct deposit on dest chain)
        dep_fn = "depositWithIntentERC4626" if is_erc4626 else "depositWithIntent"
        dep_calldata = encode_deposit_calldata(
            to_chain, dep_fn, req.user_address, vault["address"],
            to_token, intent_amount, nonce, deadline, fee_bps,
            sig_bytes, req.referrer,
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
            intent=IntentData(
                user=req.user_address, vault=vault["address"], asset=to_token,
                amount=str(intent_amount), nonce=str(nonce), deadline=str(deadline),
                fee_bps=str(fee_bps),
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
                    amount=str(intent_amount),
                ),
            ),
        )
    else:
        # Single-step: cc_quote already built above
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
                fee_bps=str(fee_bps),
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


def _build_eip712(intent: IntentData, chain_id: int, router_address: str) -> EIP712Data:
    return EIP712Data(
        domain=EIP712Domain(
            name=EIP712_DOMAIN_NAME,
            version=EIP712_DOMAIN_VERSION,
            chainId=chain_id,
            verifyingContract=router_address,
        ),
        types={"DepositIntent": EIP712_TYPES["DepositIntent"]},
        message=_intent_eip712_message(intent),
    )


def _intent_eip712_message(intent: IntentData) -> dict:
    """Convert IntentData to EIP-712 message dict with correct field names."""
    return {
        "user": intent.user,
        "vault": intent.vault,
        "asset": intent.asset,
        "amount": intent.amount,
        "nonce": intent.nonce,
        "deadline": intent.deadline,
        "feeBps": intent.fee_bps,
    }
