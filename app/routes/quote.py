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
    lifi_approval_target,
)
from app.services.vault import get_vault, get_vault_response
from app.services.rpc import (
    get_vault_share_price,
    encode_deposit_for_calldata,
    encode_deposit_for_available_calldata,
)
from app.services import lifi
from app.services import database
from app.core.auth import hash_key
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


async def _require_registered_user(request: Request, user_address: str) -> None:
    """Enforce 'sign-in before action'. Accepts either:
      - Valid partner API key (wallet integrations keep working), OR
      - Valid SIWE user session whose address matches `user_address`.
    Without one of these we reject — deposit-only, unregistered users are no
    longer allowed to build transactions.
    """
    if await get_partner_from_api_key(request):
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in required — please sign the wallet message to register before depositing")
    session = await database.get_user_session(hash_key(auth[7:]))
    if not session:
        raise HTTPException(status_code=401, detail="Session expired — please sign in again")
    if session["address"].lower() != user_address.lower():
        raise HTTPException(status_code=403, detail="Session address does not match deposit address")
    user = await database.get_user_by_address(session["address"])
    if not user or user.get("status") != "active":
        raise HTTPException(status_code=403, detail="Account inactive")


@router.post("/build", response_model=BuildResponse)
async def build_transaction(req: BuildRequest, request: Request):
    partner = await get_partner_from_api_key(request)
    if partner:
        req.referrer = partner.get("fee_collector_address", partner["address"])
    else:
        await _require_registered_user(request, req.user_address)

    vault = get_vault(req.vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Vault {req.vault_id} not found")

    if vault.get("type") == "unsupported":
        raise HTTPException(status_code=400, detail=f"Vault {vault['name']} does not support deposits through our router.")
    if vault.get("paused"):
        reason = vault.get("paused_reason") or "Deposits temporarily paused."
        raise HTTPException(status_code=503, detail=f"{vault['name']}: {reason}")

    to_chain = vault["chain_id"]
    to_token = vault["asset_address"]
    deposit_router = vault["deposit_router"]
    # For Mellow/Lido, the router's queue lookup and share forwarding are keyed
    # by the share token, NOT the orchestrator vault address. For ERC-4626 etc.
    # the deposit_target is just the vault address.
    deposit_target = vault.get("share_token") or vault["address"]
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
            to_chain, deposit_target, to_token, from_amount_int,
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
    # HyperEVM (999) — LiFi's same-chain swap aggregator on this chain routes
    # through HyperSwap / native DEX routers that DON'T honor the post-swap
    # contract call. Result: composer swap runs, our DepositRouter is never
    # called, tx looks "completed" but no vault shares are minted. Same on the
    # destination side of cross-chain deposits TO HyperEVM. Force two-step until
    # LiFi's composer support on HyperEVM is reliable.
    HYPEREVM = 999
    if to_chain == HYPEREVM and not is_direct:
        force_two_step = True
    if not force_two_step:
        to_amount, _ = lifi.extract_quote_amounts(lifi_quote)
        # Two layers of safety:
        #
        # 1. depositForAvailable (V3.2.0+) — router pulls min(allowance, balance) from
        #    msg.sender. Eliminates calldata-amount mismatch entirely.
        # 2. contractCalls.fromAmount we hint to LiFi must be <= actual bridge delivery.
        #    LiFi's Executor reverts InsufficientBalance in LibSwap.swap if its accounted
        #    fromAmount exceeds Executor's balance. Across has been observed to underdeliver
        #    by 1 wei vs. LiFi's expectation, so we use a 2% buffer here just to drive the
        #    SwapData.fromAmount safely below any plausible delivery. Whatever LiFi
        #    "leaves on the table" stays as Executor balance and our depositForAvailable
        #    sweeps it via the allowance/balance check.
        SWAP_HINT_BUFFER_BPS = 200  # 2.00%
        cc_amount = int(int(to_amount) * (10000 - SWAP_HINT_BUFFER_BPS) // 10000)
        cc_calldata = encode_deposit_for_available_calldata(
            to_chain, deposit_target, to_token,
            req.user_address, partner_id, partner_type, is_erc4626,
            min_amount=0, min_shares_out=0,
        )
        cc_quote = await lifi.get_contract_calls_quote(
            req.from_chain_id, req.from_token, req.from_amount,
            to_chain, to_token, req.user_address,
            deposit_router, cc_calldata, str(cc_amount),
            preferred_bridges=[bridge] if bridge else None,
            slippage=req.slippage,
        )
    use_two_step = cc_quote is None

    if use_two_step:
        tx_req = lifi_quote.get("transactionRequest", {})
        if not tx_req:
            raise HTTPException(status_code=400, detail="No bridge route found")
        # If LiFi targets the Diamond, allowance goes to Diamond. If LiFi targets
        # an Executor, the user must approve its ERC20Proxy instead — Executor's
        # entry methods all pull via that proxy. lifi_approval_target() handles both.
        approval_target = lifi_approval_target(req.from_chain_id, tx_req.get("to", ""))

        # Approval must cover whatever the Executor will pull. LiFi's
        # `estimate.fromAmount` is normally the gross-with-fee value, but be
        # defensive in case a route omits the field or under-reports — never
        # approve LESS than the user's stated input. (Excess allowance is
        # harmless — Executor only pulls what its swap data says.)
        _est_from = int(lifi_quote.get("estimate", {}).get("fromAmount") or 0)
        approval_amount = str(max(_est_from, int(req.from_amount)))

        to_amount, _ = lifi.extract_quote_amounts(lifi_quote)
        # Same buffer logic as composer: bridge delivery often lands below LiFi's quoted
        # toAmountMin. The user signs step-2 themselves with their own balance, so an
        # optimistic amount would revert their tx. 2% buffer = ~$0.03 dust per $1.50 deposit
        # left in the user's own wallet (they keep it, no loss).
        TWO_STEP_BUFFER_BPS = 200
        dep_amount = int(int(to_amount) * (10000 - TWO_STEP_BUFFER_BPS) // 10000)
        dep_calldata = encode_deposit_for_calldata(
            to_chain, deposit_target, to_token, dep_amount,
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
                amount=approval_amount,
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
                    amount=str(dep_amount),
                ),
            ),
        )
    else:
        tx_req = cc_quote["transactionRequest"]
        # See comment above: same Diamond-vs-Executor distinction applies to the
        # composer path. Most chains will return Executor here; the user must
        # approve the chain's ERC20Proxy. If LiFi response is missing `to`,
        # raise rather than silently using the wrong address.
        lifi_to = tx_req.get("to")
        if not lifi_to:
            raise HTTPException(status_code=502, detail="LiFi quote missing transactionRequest.to")
        approval_target = lifi_approval_target(req.from_chain_id, lifi_to)
        used_bridge = lifi.extract_bridge_from_quote(cc_quote)
        _cc_est_from = int(cc_quote.get("estimate", {}).get("fromAmount") or 0)
        approval_amount = str(max(_cc_est_from, int(req.from_amount)))

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
                amount=approval_amount,
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
