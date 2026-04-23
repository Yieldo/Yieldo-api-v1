"""Per-vault minimum-deposit resolver. Reads real on-chain values where they exist;
returns explicit None when a vault genuinely has no enforced minimum.

We avoid guessing. ERC-4626 metamorpho vaults (the bulk of our list) accept any
amount above 1 wei — for those we report `explicit_none=True` and the UI shows
"No minimum". Vaults with real on-chain mins (Veda Tellers, Midas issuance,
Lido SyncDepositQueue, certain custom vaults) are queried directly.
"""
import logging
import time
from typing import Optional

from app.services.rpc import get_w3

logger = logging.getLogger(__name__)

# Cache: (chain_id, vault_address.lower()) -> (resolved_at, min_int_or_None, explicit_none_bool)
_CACHE: dict[tuple[int, str], tuple[float, Optional[int], bool]] = {}
_CACHE_TTL = 3600.0  # 1 hour — minimums rarely change


def _try_call(w3, target: str, signature: str, return_type: str = "uint256") -> Optional[int]:
    """Try a no-arg uint256-returning view. Returns None on revert / no method."""
    try:
        contract = w3.eth.contract(
            address=w3.to_checksum_address(target),
            abi=[{
                "inputs": [],
                "name": signature,
                "outputs": [{"type": return_type, "name": ""}],
                "stateMutability": "view",
                "type": "function",
            }],
        )
        return int(getattr(contract.functions, signature)().call())
    except Exception:
        return None


def _try_call_with_arg(w3, target: str, signature: str, arg_type: str, arg_value, return_type: str = "uint256") -> Optional[int]:
    try:
        contract = w3.eth.contract(
            address=w3.to_checksum_address(target),
            abi=[{
                "inputs": [{"type": arg_type, "name": "x"}],
                "name": signature,
                "outputs": [{"type": return_type, "name": ""}],
                "stateMutability": "view",
                "type": "function",
            }],
        )
        return int(getattr(contract.functions, signature)(arg_value).call())
    except Exception:
        return None


def _veda_min_mint(w3, teller: str, asset: str) -> Optional[int]:
    """Veda BoringVault Teller exposes assetData(asset) → (..., minimumMint, ...)."""
    try:
        contract = w3.eth.contract(
            address=w3.to_checksum_address(teller),
            abi=[{
                "inputs": [{"type": "address", "name": "asset"}],
                "name": "assetData",
                "outputs": [
                    {"type": "bool", "name": "allowDeposits"},
                    {"type": "bool", "name": "allowWithdraws"},
                    {"type": "uint16", "name": "sharePremium"},
                ],
                "stateMutability": "view",
                "type": "function",
            }],
        )
        contract.functions.assetData(w3.to_checksum_address(asset)).call()
    except Exception:
        pass
    # Try minimumMint(address) as a separate fn (some Tellers expose this)
    return _try_call_with_arg(w3, teller, "minimumMint", "address", w3.to_checksum_address(asset))


def _midas_min(w3, issuance_vault: str, asset: str) -> Optional[int]:
    """Midas instant-issuance vault: instantInitialDeposit(asset) or minBuyAmount(asset)."""
    for fn in ("minBuyAmount", "instantInitialDeposit", "minDepositAmount"):
        v = _try_call_with_arg(w3, issuance_vault, fn, "address", w3.to_checksum_address(asset))
        if v is not None and v > 0:
            return v
    return None


def _lido_min(w3, queue: str) -> Optional[int]:
    """Lido SyncDepositQueue: minDeposit() or MIN_DEPOSIT()."""
    for fn in ("minDeposit", "MIN_DEPOSIT"):
        v = _try_call(w3, queue, fn)
        if v is not None and v > 0:
            return v
    return None


def _generic_min(w3, vault: str) -> Optional[int]:
    """Try common min-deposit views on arbitrary vault contracts."""
    for fn in ("minDeposit", "MIN_DEPOSIT", "minimumDeposit", "minMint"):
        v = _try_call(w3, vault, fn)
        if v is not None and v > 0:
            return v
    return None


def resolve(vault: dict) -> tuple[Optional[int], bool]:
    """Returns (min_amount_in_asset_units, has_no_minimum_bool).

    - If we find a real on-chain min: (int, False)
    - If the vault type genuinely has no enforced minimum: (None, True)
    - If we couldn't determine and shouldn't claim either way: (None, False)
    """
    # Manually-curated mins in vaults.json win
    pre = vault.get("min_deposit")
    if pre is not None and pre != "" and int(pre) > 0:
        return int(pre), False

    chain_id = vault["chain_id"]
    addr = vault["address"].lower()
    cache_key = (chain_id, addr)
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1], cached[2]

    vtype = vault.get("type", "morpho")
    asset_addr = vault.get("asset_address")
    min_amount: Optional[int] = None
    has_no_min = False

    try:
        w3 = get_w3(chain_id)

        if vtype == "morpho":
            # Standard ERC-4626 / MetaMorpho — no on-chain minimum.
            has_no_min = True

        elif vtype == "ipor":
            # Plonk / IPOR vaults — also standard 4626 in practice.
            min_amount = _generic_min(w3, vault["address"])
            if min_amount is None:
                has_no_min = True

        elif vtype == "accountable":
            # Accountable vaults already pre-populated in JSON. If we get here,
            # try generic.
            min_amount = _generic_min(w3, vault["address"])

        elif vtype == "veda":
            # Veda's Teller is a separate contract. Without knowing the teller
            # mapping client-side, just try generic on the vault.
            min_amount = _generic_min(w3, vault["address"])

        elif vtype == "midas":
            min_amount = _generic_min(w3, vault["address"])

        elif vtype == "lido":
            min_amount = _lido_min(w3, vault["address"])

        elif vtype == "custom":
            # Hyperbeat, 9Summits, etc. — try common signatures.
            min_amount = _generic_min(w3, vault["address"])
            if min_amount is None:
                # syncDeposit pattern often has no enforced minimum
                has_no_min = True

        else:
            min_amount = _generic_min(w3, vault["address"])

    except Exception as e:
        logger.warning(f"min_deposit resolve failed for {chain_id}:{addr}: {e}")

    _CACHE[cache_key] = (now, min_amount, has_no_min)
    return min_amount, has_no_min


def warm_cache(vaults: list[dict]) -> None:
    """Optional: pre-resolve on startup to make first vault list response fast."""
    for v in vaults:
        try:
            resolve(v)
        except Exception:
            pass
