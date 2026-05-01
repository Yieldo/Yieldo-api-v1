from web3 import Web3
from web3.contract import Contract
from eth_account import Account
from eth_account.messages import encode_typed_data
from app.config import get_settings
from app.core.abi import DEPOSIT_ROUTER_ABI, ERC4626_ABI, ERC20_ABI
from app.core.constants import (
    DEPOSIT_ROUTER_ADDRESSES,
    EIP712_DOMAIN_NAME,
    EIP712_DOMAIN_VERSION,
    EIP712_TYPES,
)

_providers: dict[int, Web3] = {}


def get_w3(chain_id: int) -> Web3:
    if chain_id in _providers:
        return _providers[chain_id]
    settings = get_settings()
    rpc_map = {
        1: settings.ethereum_rpc_url,
        8453: settings.base_rpc_url,
        42161: settings.arbitrum_rpc_url,
        10: settings.optimism_rpc_url,
        143: settings.monad_rpc_url,
        999: settings.hyperliquid_rpc_url,
        747474: settings.katana_rpc_url,
    }
    url = rpc_map.get(chain_id)
    if not url:
        raise ValueError(f"No RPC configured for chain {chain_id}")
    w3 = Web3(Web3.HTTPProvider(url))
    _providers[chain_id] = w3
    return w3


def get_deposit_router(chain_id: int) -> Contract:
    w3 = get_w3(chain_id)
    addr = DEPOSIT_ROUTER_ADDRESSES.get(chain_id)
    if not addr:
        raise ValueError(f"No deposit router on chain {chain_id}")
    return w3.eth.contract(address=Web3.to_checksum_address(addr), abi=DEPOSIT_ROUTER_ABI)


def get_vault_contract(chain_id: int, vault_address: str) -> Contract:
    w3 = get_w3(chain_id)
    return w3.eth.contract(address=Web3.to_checksum_address(vault_address), abi=ERC4626_ABI)


def get_erc20_contract(chain_id: int, token_address: str) -> Contract:
    w3 = get_w3(chain_id)
    return w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)


def get_vault_asset(chain_id: int, vault_address: str) -> str:
    vault = get_vault_contract(chain_id, vault_address)
    return vault.functions.asset().call()


def get_vault_total_assets(chain_id: int, vault_address: str) -> int:
    vault = get_vault_contract(chain_id, vault_address)
    return vault.functions.totalAssets().call()


def get_vault_total_supply(chain_id: int, vault_address: str) -> int:
    vault = get_vault_contract(chain_id, vault_address)
    return vault.functions.totalSupply().call()


def get_token_decimals(chain_id: int, token_address: str) -> int:
    token = get_erc20_contract(chain_id, token_address)
    return token.functions.decimals().call()


# Per-process cache — share decimals for a given (chain, address) never change
# at runtime, but reading them every portfolio fetch would be 1 RPC per position.
_SHARE_DECIMALS_CACHE: dict[tuple[int, str], int] = {}

def get_share_decimals_cached(chain_id: int, share_token_address: str) -> int | None:
    """Read & cache the share token's decimals(). Returns None on RPC failure
    so callers can fall back to a sensible default rather than crash."""
    key = (chain_id, share_token_address.lower())
    if key in _SHARE_DECIMALS_CACHE:
        return _SHARE_DECIMALS_CACHE[key]
    try:
        d = get_token_decimals(chain_id, share_token_address)
        _SHARE_DECIMALS_CACHE[key] = int(d)
        return int(d)
    except Exception:
        return None


def get_vault_share_price(chain_id: int, vault_address: str) -> tuple[int, int]:
    vault = get_vault_contract(chain_id, vault_address)
    total_assets = vault.functions.totalAssets().call()
    total_supply = vault.functions.totalSupply().call()
    return total_assets, total_supply


def get_nonce(chain_id: int, user_address: str) -> int:
    """Get withdraw nonce from the deposit router (still needed for withdraw flow)."""
    w3 = get_w3(chain_id)
    addr = DEPOSIT_ROUTER_ADDRESSES.get(chain_id)
    if not addr:
        raise ValueError(f"No deposit router on chain {chain_id}")
    # Call getNonce on the old router ABI — withdraw router still has this
    abi = [{"inputs": [{"internalType": "address", "name": "user", "type": "address"}], "name": "getNonce", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
    c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)
    return c.functions.getNonce(Web3.to_checksum_address(user_address)).call()


def encode_deposit_for_calldata(
    chain_id: int,
    vault: str,
    asset: str,
    amount: int,
    user: str,
    partner_id: bytes,
    partner_type: int,
    is_erc4626: bool,
    min_shares_out: int | None = None,
    deadline: int | None = None,
) -> str:
    """Build depositFor calldata. ABI shape is picked by arg count:
      - 7-arg = V3.0 shim (no slippage, no expiration)
      - 8-arg = V3.1 shim (slippage; deadline forwarded as 0)
      - 9-arg = V3.3 primary (slippage + expiration — audit M-04)

    Pass `deadline` (unix seconds) to enable stale-mempool protection on V3.3+.
    Pass None (default) for backward-compat with pre-V3.3 routers."""
    router = get_deposit_router(chain_id)
    base_args = [
        Web3.to_checksum_address(vault),
        Web3.to_checksum_address(asset),
        amount,
        Web3.to_checksum_address(user),
        partner_id,
        partner_type,
        is_erc4626,
    ]
    if deadline is not None:
        # 9-arg V3.3+ primary
        args = base_args + [min_shares_out or 0, deadline]
    elif min_shares_out is not None:
        args = base_args + [min_shares_out]
    else:
        args = base_args
    return router.encode_abi(abi_element_identifier="depositFor", args=args)


def encode_deposit_for_available_calldata(
    chain_id: int,
    vault: str,
    asset: str,
    user: str,
    partner_id: bytes,
    partner_type: int,
    is_erc4626: bool,
    min_amount: int = 0,
    min_shares_out: int = 0,
    deadline: int | None = None,
) -> str:
    """V3.2.0+ composer-friendly entry: pulls min(allowance, balance) from msg.sender,
    so cross-chain composer flows don't need a hardcoded amount that bridge fees might
    underflow. The caller (e.g. LiFi Executor) approves the router for the exact
    post-bridge amount before invoking us. V3.3 adds `deadline` for stale-mempool
    protection (audit M-04)."""
    router = get_deposit_router(chain_id)
    base_args = [
        Web3.to_checksum_address(vault),
        Web3.to_checksum_address(asset),
        Web3.to_checksum_address(user),
        partner_id,
        partner_type,
        is_erc4626,
        min_amount,
        min_shares_out,
    ]
    args = base_args + [deadline] if deadline is not None else base_args
    return router.encode_abi(abi_element_identifier="depositForAvailable", args=args)


def encode_deposit_request_for_calldata(
    chain_id: int,
    vault: str,
    asset: str,
    amount: int,
    user: str,
    partner_id: bytes,
    partner_type: int,
    deadline: int | None = None,
) -> str:
    router = get_deposit_router(chain_id)
    base_args = [
        Web3.to_checksum_address(vault),
        Web3.to_checksum_address(asset),
        amount,
        Web3.to_checksum_address(user),
        partner_id,
        partner_type,
    ]
    args = base_args + [deadline] if deadline is not None else base_args
    return router.encode_abi(abi_element_identifier="depositRequestFor", args=args)


def sign_withdraw_intent(
    chain_id: int,
    router_address: str,
    user: str,
    vault: str,
    asset: str,
    shares: int,
    min_amount_out: int,
    nonce: int,
    deadline: int,
) -> str:
    settings = get_settings()
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "WithdrawIntent": EIP712_TYPES["WithdrawIntent"],
        },
        "primaryType": "WithdrawIntent",
        "domain": {
            "name": EIP712_DOMAIN_NAME,
            "version": EIP712_DOMAIN_VERSION,
            "chainId": chain_id,
            "verifyingContract": Web3.to_checksum_address(router_address),
        },
        "message": {
            "user": Web3.to_checksum_address(user),
            "vault": Web3.to_checksum_address(vault),
            "asset": Web3.to_checksum_address(asset),
            "shares": shares,
            "minAmountOut": min_amount_out,
            "nonce": nonce,
            "deadline": deadline,
        },
    }
    signable = encode_typed_data(full_message=typed_data)
    signed = Account.sign_message(signable, private_key=settings.signer_private_key)
    return "0x" + signed.signature.hex()


def encode_withdraw_calldata(
    chain_id: int,
    fn_name: str,
    user: str,
    vault: str,
    asset: str,
    shares: int,
    min_amount_out: int,
    nonce: int,
    deadline: int,
    signature: bytes,
) -> str:
    router = get_deposit_router(chain_id)
    intent_tuple = (
        Web3.to_checksum_address(user),
        Web3.to_checksum_address(vault),
        Web3.to_checksum_address(asset),
        shares,
        min_amount_out,
        nonce,
        deadline,
    )
    return router.encode_abi(abi_element_identifier=fn_name, args=[intent_tuple, signature])


def encode_claim_calldata(chain_id: int, req_hash: bytes) -> str:
    router = get_deposit_router(chain_id)
    return router.encode_abi(abi_element_identifier="claimWithdrawRequest", args=[req_hash])


def get_vault_convert_to_assets(chain_id: int, vault_address: str, shares: int) -> int:
    w3 = get_w3(chain_id)
    abi = [{
        "inputs": [{"internalType": "uint256", "name": "shares", "type": "uint256"}],
        "name": "convertToAssets",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }]
    c = w3.eth.contract(address=Web3.to_checksum_address(vault_address), abi=abi)
    return int(c.functions.convertToAssets(shares).call())


def get_erc20_balance(chain_id: int, token_address: str, holder: str) -> int:
    w3 = get_w3(chain_id)
    abi = [{
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }]
    c = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=abi)
    return int(c.functions.balanceOf(Web3.to_checksum_address(holder)).call())


def batch_erc20_balances(chain_id: int, tokens: list[str], holder: str) -> dict[str, int]:
    out = {}
    for t in tokens:
        try:
            out[t.lower()] = get_erc20_balance(chain_id, t, holder)
        except Exception:
            out[t.lower()] = 0
    return out
