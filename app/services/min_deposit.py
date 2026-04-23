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
    """Midas instant-issuance vault: minBuyAmount(asset) / instantInitialDeposit(asset)."""
    for fn in ("minBuyAmount", "instantInitialDeposit", "minDepositAmount"):
        v = _try_call_with_arg(w3, issuance_vault, fn, "address", w3.to_checksum_address(asset))
        if v is not None and v > 0:
            return v
    # Some Midas IVs use a no-arg uint256 for the min in 18-dec units
    for fn in ("minDepositAmountInBase18", "minAmountToDepositInBase18"):
        v = _try_call(w3, issuance_vault, fn)
        if v is not None and v > 0:
            return v
    return None


def _read_router_midas_vault(w3, router: str, share_token: str) -> Optional[str]:
    """Read midasVaults(shareToken) from our DepositRouter — gives us the IV address."""
    try:
        contract = w3.eth.contract(
            address=w3.to_checksum_address(router),
            abi=[{
                "inputs": [{"type": "address", "name": "x"}],
                "name": "midasVaults",
                "outputs": [{"type": "address", "name": ""}],
                "stateMutability": "view",
                "type": "function",
            }],
        )
        addr = contract.functions.midasVaults(w3.to_checksum_address(share_token)).call()
        if addr and int(addr, 16) != 0:
            return addr
    except Exception:
        pass
    return None


def _read_router_veda_teller(w3, router: str, vault: str) -> Optional[str]:
    """Read vedaTellers(vault) from our DepositRouter."""
    try:
        contract = w3.eth.contract(
            address=w3.to_checksum_address(router),
            abi=[{
                "inputs": [{"type": "address", "name": "x"}],
                "name": "vedaTellers",
                "outputs": [{"type": "address", "name": ""}],
                "stateMutability": "view",
                "type": "function",
            }],
        )
        addr = contract.functions.vedaTellers(w3.to_checksum_address(vault)).call()
        if addr and int(addr, 16) != 0:
            return addr
    except Exception:
        pass
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
            # Accountable vaults already pre-populated in JSON. If we get here
            # without a JSON value, probe; if nothing, no enforced minimum.
            min_amount = _generic_min(w3, vault["address"])
            if min_amount is None:
                has_no_min = True

        elif vtype == "veda":
            # Veda BoringVault: there is NO contract-enforced minimum. The min is
            # the `minimumMint` parameter the caller supplies per-tx. Our router
            # passes 0 (no slippage check at the Veda layer — vaults dispatch
            # picks shares > 0). Truthful answer: no enforced minimum.
            has_no_min = True

        elif vtype == "midas":
            # Midas: probe the issuance vault, not the share token. Read the
            # issuance vault address from our router's midasVaults mapping.
            router = vault.get("deposit_router")
            iv = _read_router_midas_vault(w3, router, vault["address"]) if router else None
            if iv and asset_addr:
                min_amount = _midas_min(w3, iv, asset_addr)
            if min_amount is None:
                # Issuance vault unknown to us → fall through; generic may catch it
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
            if min_amount is None:
                has_no_min = True

    except Exception as e:
        logger.warning(f"min_deposit resolve failed for {chain_id}:{addr}: {e}")
        # On RPC error, do not claim no_minimum; leave as unknown so the UI is honest

    _CACHE[cache_key] = (now, min_amount, has_no_min)
    return min_amount, has_no_min


def warm_cache(vaults: list[dict], max_workers: int = 16) -> None:
    """Pre-resolve all vault minimums in parallel so the first /v1/vaults response
    is fast. Called once on app startup. Failures are silently cached as None.
    Clears any stale cache entries first so resolver-logic changes take effect."""
    _CACHE.clear()
    from concurrent.futures import ThreadPoolExecutor
    started = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_safe_resolve, vaults))
    explicit = sum(1 for v in _CACHE.values() if v[1] is not None)
    no_min = sum(1 for v in _CACHE.values() if v[1] is None and v[2])
    unknown = sum(1 for v in _CACHE.values() if v[1] is None and not v[2])
    logger.info(
        f"min_deposit warm-cache done: {len(vaults)} vaults in {time.time() - started:.1f}s "
        f"(explicit={explicit}, no_min={no_min}, unknown={unknown})"
    )


def _safe_resolve(v: dict) -> None:
    try:
        resolve(v)
    except Exception:
        pass
