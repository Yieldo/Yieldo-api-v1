"""Withdraw flow — V2.6.1+

Withdrawals go DIRECT to the protocol (no router custody). The API builds
the approval + withdraw calldata targeting the protocol contract itself,
and the user's wallet signs/sends. Backend tracks via event indexing only.

Per-protocol dispatch:
 - morpho / custom / ipor → ERC-4626 redeem(shares, receiver, owner) on the vault
 - midas (sync)            → Midas RV redeemInstant(tokenOut, amt, minOut)
 - midas (async)           → Midas RV redeemRequest(tokenOut, amt)
 - veda                    → reject (send user to Veda UI; AtomicQueue too complex to proxy)
"""
from fastapi import APIRouter, HTTPException
from web3 import Web3

from app.models import (
    WithdrawQuoteRequest, WithdrawQuoteResponse, WithdrawIntentData,
    WithdrawBuildRequest, WithdrawBuildResponse,
    TransactionRequest, ApprovalData,
)
from app.services.rpc import get_vault_convert_to_assets, get_w3
from app.services.vault import get_vault, get_vault_response
from app.services import database

router = APIRouter(prefix="/v1/withdraw", tags=["withdraw"])

# Midas RedemptionVault addresses — keyed by share (mToken) address.
# Found via scripts/verify-midas-rvs.js, all on Ethereum mainnet.
MIDAS_REDEMPTION_VAULTS = {
    "0x238a700ed6165261cf8b2e544ba797bc11e466ba": "0x44b0440e35c596e858cEA433D0d82F5a985fD19C",  # mFONE
    "0xdd629e5241cbc5919847783e6c96b2de4754e438": "0x569D7dccBF6923350521ecBC28A555A500c4f0Ec",  # mTBILL
    "0x9b5528528656dbc094765e2abb79f293c21191b9": "0x6Be2f55816efd0d91f52720f096006d63c366e98",  # mHYPER
    "0xc8495eaff71d3a563b906295fcf2f685b1783085": "0x16d4f955B0aA1b1570Fe3e9bB2f8c19C407cdb67",  # HyperBTC
    "0x7cf9dec92ca9fd46f8d86e7798b72624bc116c05": "0x5aeA6D35ED7B3B7aE78694B7da2Ee880756Af5C0",  # mAPOLLO
    "0x030b69280892c888670edcdcd8b69fd8026a0bf3": "0xac14a14f578C143625Fc8F54218911e8F634184D",  # mMEV
    "0x5a42864b14c0c8241ef5ab62dae975b163a2e0c1": "0x15f724b35A75F0c28F352b952eA9D1b24e348c57",  # mHyperETH
    "0x87c9053c819bb28e0d73d33059e1b3da80afb0cf": "0x5356B8E06589DE894D86B24F4079c629E8565234",  # mRe7YIELD
    # Hyperbeat-on-HyperEVM (chain 999). Same Midas redeemInstant signature.
    "0x5e105266db42f78fa814322bce7f388b4c2e61eb": "0xC898a5cbDb81F260bd5306D9F9B9A893D0FdF042",  # hbUSDT (Hyperbeat USDT)
}

ERC4626_REDEEM_ABI = [{
    "name": "redeem", "type": "function", "stateMutability": "nonpayable",
    "inputs": [
        {"name": "shares", "type": "uint256"},
        {"name": "receiver", "type": "address"},
        {"name": "owner", "type": "address"},
    ],
    "outputs": [{"name": "", "type": "uint256"}],
}]
MIDAS_REDEEM_INSTANT_ABI = [{
    "name": "redeemInstant", "type": "function", "stateMutability": "nonpayable",
    "inputs": [
        {"name": "tokenOut", "type": "address"},
        {"name": "amountMTokenIn", "type": "uint256"},
        {"name": "minReceiveAmount", "type": "uint256"},
    ],
    "outputs": [],
}]
MIDAS_REDEEM_REQUEST_ABI = [{
    "name": "redeemRequest", "type": "function", "stateMutability": "nonpayable",
    "inputs": [
        {"name": "tokenOut", "type": "address"},
        {"name": "amountMTokenIn", "type": "uint256"},
    ],
    "outputs": [{"name": "", "type": "uint256"}],
}]


def _pick_mode(vault_type: str) -> str:
    if vault_type == "midas":
        return "sync"  # default; client may request "async" explicitly
    if vault_type == "veda":
        return "async"
    return "sync"


def _encode_redeem(w3: Web3, vault_addr: str, shares: int, user: str) -> str:
    c = w3.eth.contract(address=Web3.to_checksum_address(vault_addr), abi=ERC4626_REDEEM_ABI)
    return c.encode_abi(abi_element_identifier="redeem", args=[shares, Web3.to_checksum_address(user), Web3.to_checksum_address(user)])


def _encode_midas_instant(w3: Web3, rv_addr: str, token_out: str, shares: int, min_out: int) -> str:
    c = w3.eth.contract(address=Web3.to_checksum_address(rv_addr), abi=MIDAS_REDEEM_INSTANT_ABI)
    return c.encode_abi(abi_element_identifier="redeemInstant", args=[
        Web3.to_checksum_address(token_out), shares, min_out,
    ])


def _encode_midas_request(w3: Web3, rv_addr: str, token_out: str, shares: int) -> str:
    c = w3.eth.contract(address=Web3.to_checksum_address(rv_addr), abi=MIDAS_REDEEM_REQUEST_ABI)
    return c.encode_abi(abi_element_identifier="redeemRequest", args=[
        Web3.to_checksum_address(token_out), shares,
    ])


@router.post("/quote", response_model=WithdrawQuoteResponse)
async def withdraw_quote(req: WithdrawQuoteRequest):
    vault = get_vault(req.vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Vault {req.vault_id} not found")
    if vault.get("type") == "unsupported":
        raise HTTPException(status_code=400, detail=f"{vault['name']}: withdrawals temporarily unavailable.")

    vault_type = vault.get("type", "morpho")
    if vault_type == "veda":
        raise HTTPException(
            status_code=400,
            detail=f"Withdrawals for {vault['name']} must be done via Veda's website.",
        )
    if vault_type == "ipor" or vault_type == "lido":
        # IPOR leveraged Plasma Vaults and Lido Earn vaults have no instant-redeem
        # liquidity for direct ERC-4626 redeem(). They require the protocol's
        # native scheduled-withdraw flow (requestWithdraw + wait + finalizeWithdraw)
        # which we don't yet proxy. Users should use the protocol's own UI.
        brand = "IPOR" if vault_type == "ipor" else "Lido Earn"
        site = "https://app.ipor.io" if vault_type == "ipor" else "https://earn.lido.fi"
        raise HTTPException(
            status_code=400,
            detail=f"Withdrawals for {vault['name']} must be done via {brand}'s website ({site}).",
        )

    shares = int(req.shares)
    if shares <= 0:
        raise HTTPException(status_code=400, detail="shares must be > 0")

    to_chain = vault["chain_id"]
    vault_addr = vault["address"]
    # Some vaults (e.g. Midas HyperBTC: deposit WBTC, redeem cbBTC) settle
    # withdrawals to a different token than the deposit asset. Use the
    # redemption_asset when set; otherwise default to deposit asset.
    asset = vault.get("redemption_asset_address") or vault["asset_address"]

    try:
        est_assets = get_vault_convert_to_assets(to_chain, vault_addr, shares)
    except Exception:
        est_assets = 0
    min_amount_out = int(est_assets * (1 - req.slippage)) if est_assets > 0 else 0

    mode = _pick_mode(vault_type)

    # Direct-to-protocol: no router, no backend signature. Return a plain
    # intent object populated with the parameters the caller is about to use,
    # so the existing UI contract keeps working.
    intent = WithdrawIntentData(
        user=req.user_address, vault=vault_addr, asset=asset,
        shares=str(shares), min_amount_out=str(min_amount_out),
        nonce="0", deadline="0",
    )

    # Approval target: for Morpho/Custom/IPOR, no approval needed (user owns shares;
    # ERC-4626 redeem burns from `owner=msg.sender`). For Midas, approve the RV.
    if vault_type == "midas":
        rv = MIDAS_REDEMPTION_VAULTS.get(vault_addr.lower())
        if not rv:
            raise HTTPException(status_code=400, detail=f"Withdrawals for {vault['name']} are temporarily unavailable.")
        approval = ApprovalData(token_address=vault_addr, spender_address=rv, amount=str(shares))
    else:
        # For ERC-4626 redeem, the caller is the owner — no allowance needed.
        # Return a zero-approval marker so the UI can skip the approve step.
        approval = ApprovalData(token_address=vault_addr, spender_address=vault_addr, amount="0")

    return WithdrawQuoteResponse(
        vault=get_vault_response(req.vault_id),
        mode=mode,
        shares=str(shares),
        estimated_assets=str(est_assets) if est_assets > 0 else None,
        min_amount_out=str(min_amount_out),
        intent=intent,
        eip712=None,  # no signed intent on direct path
        signature="",
        approval=approval,
    )


@router.post("/build", response_model=WithdrawBuildResponse)
async def withdraw_build(req: WithdrawBuildRequest):
    vault = get_vault(req.vault_id)
    if not vault:
        raise HTTPException(status_code=404, detail=f"Vault {req.vault_id} not found")
    vault_type = vault.get("type", "morpho")
    if vault_type in ("veda", "ipor", "lido"):
        brand = {"veda": "Veda", "ipor": "IPOR", "lido": "Lido Earn"}[vault_type]
        raise HTTPException(status_code=400, detail=f"{brand} withdrawals must be done via protocol UI")

    to_chain = vault["chain_id"]
    vault_addr = vault["address"]
    # Some vaults (e.g. Midas HyperBTC: deposit WBTC, redeem cbBTC) settle
    # withdrawals to a different token than the deposit asset. Use the
    # redemption_asset when set; otherwise default to deposit asset.
    asset = vault.get("redemption_asset_address") or vault["asset_address"]
    shares = int(req.shares)
    min_out = int(req.min_amount_out)
    w3 = get_w3(to_chain)

    if req.mode not in ("sync", "async"):
        raise HTTPException(status_code=400, detail="mode must be sync or async")

    if vault_type == "midas":
        rv = MIDAS_REDEMPTION_VAULTS.get(vault_addr.lower())
        if not rv:
            raise HTTPException(status_code=400, detail="Withdrawals temporarily unavailable for this vault.")
        if req.mode == "sync":
            calldata = _encode_midas_instant(w3, rv, asset, shares, min_out)
        else:
            calldata = _encode_midas_request(w3, rv, asset, shares)
        target = rv
        gas_limit = "900000"
        approval = ApprovalData(token_address=vault_addr, spender_address=rv, amount=str(shares))
    else:
        # ERC-4626 redeem — caller owns the shares, no approval needed.
        # Gas headroom: Morpho MetaMorpho + IPOR PlasmaVault redeems cascade through
        # multiple internal markets (Morpho Blue / IPOR Fusion) and can exceed 1M gas
        # for moderately-sized positions. 1.5M covers real observed usage (~1.17M on
        # Hyperithm USDC Apex) with a 28% safety buffer. Unused gas refunds to user.
        calldata = _encode_redeem(w3, vault_addr, shares, req.user_address)
        target = vault_addr
        gas_limit = "1500000"
        approval = ApprovalData(token_address=vault_addr, spender_address=vault_addr, amount="0")

    resp = WithdrawBuildResponse(
        transaction_request=TransactionRequest(
            to=target, data=calldata, value="0",
            chain_id=to_chain, gas_limit=gas_limit,
        ),
        approval=approval,
        mode=req.mode,
    )
    resp.tracking_id = await database.save_withdraw(
        user=req.user_address, vault_id=req.vault_id, vault_name=vault["name"],
        shares=req.shares, asset=asset, mode=req.mode, chain_id=to_chain,
        assets_out=req.min_amount_out,  # vault-asset units; used by portfolio yield calc
    )
    return resp


@router.get("/requests/{user_address}")
async def get_pending_requests(user_address: str):
    """Async withdraw requests submitted through Yieldo. Direct-to-protocol
    means fulfillment tokens land in the user's own wallet — no claim step.
    We just track `status` for dashboard UX."""
    return await database.get_user_withdraw_requests(user_address)
