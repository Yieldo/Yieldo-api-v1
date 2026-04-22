---
title: "Deposit Router Contracts"
description: "V3.1.0 attribution-only router, vault dispatch, authorized callers"
---

The Deposit Router is an attribution-only, non-custodial pass-through. It pulls tokens from the caller, dispatches to the correct vault protocol (ERC-4626, Midas issuance vault, Veda teller, Lido queue, or custom adapter), forwards the minted shares to the user, and emits a `Routed` event for on-chain attribution. **No fees are deducted** — 100% of the user's tokens reach the vault.

Current version: **V3.1.0**.

## What Changed in V3.1.0

- **`authorizedCallers` mapping** — a whitelist that controls who may pass a `user` address different from `msg.sender`. LiFi's Executor and Diamond contracts are whitelisted on chains where the composer is live (Ethereum, Base, Arbitrum, Optimism). On two-step chains (Monad, Katana) no whitelist is needed because the user signs their own `depositFor` call on the destination chain.
- **8-arg `depositFor` with `minSharesOut`** — new slippage floor on same-chain deposits. The 7-arg form is kept as a compatibility shim (forwards with `minSharesOut=0`).
- **Shares returned explicitly** — `_executeVaultCall` now returns the exact shares minted, cross-checked against `balanceOf(recipient)` to detect silent failures in downstream adapters.
- **`Routed` event now includes `shares`** — previously indexers had to read vault share balances to compute this.

## Contract Addresses

All chains are on V3.1.0 as of 2026-04-23. Same proxy address on Katana and HyperEVM is coincidental (CREATE2 on separate chains).

| Chain    | Chain ID | Proxy Address                                 |
| -------- | -------- | --------------------------------------------- |
| Ethereum | 1        | `0x85f76c1685046Ea226E1148EE1ab81a8a15C385d`  |
| Base     | 8453     | `0xF6B7723661d52E8533c77479d3cad534B4D147Aa`  |
| Arbitrum | 42161    | `0xC5700f4D8054BA982C39838D7C33442f54688bd2`  |
| Optimism | 10       | `0x7554937Aa95195D744A6c45E0fd7D4F95A2F8F72`  |
| Monad    | 143      | `0xCD8dfD627A3712C9a2B079398e0d524970D5E73F`  |
| HyperEVM | 999      | `0xa682CD1c2Fd7c8545b401824096A600C2bD98F69`  |
| Katana   | 747474   | `0xa682CD1c2Fd7c8545b401824096A600C2bD98F69`  |

## How Deposits Work

### Same-Chain Deposit

```
User approves tokens to router → User calls depositFor() → Router pulls tokens
  → Router dispatches to vault protocol → Shares sent to user → Routed event emitted
```

msg.sender == user. No whitelist check needed.

### Cross-Chain Deposit (Two-Step)

Used for vault types that aren't composable with LiFi's Composer (Midas, Veda, Custom, IPOR, Lido):

```
Step 1 (source):  User sends LiFi bridge tx
                  → tokens arrive at user's wallet on destination chain
Step 2 (dest):    User approves → User calls depositFor() → Shares sent to user
```

Step 2 is a normal same-chain deposit from the user's perspective.

### Cross-Chain Deposit (Single-Step, Composer)

Used for Morpho and other standard ERC-4626 vaults. LiFi bridges + calls `depositFor` atomically on the destination:

```
User sends LiFi tx on source chain → LiFi Executor on destination receives tokens
  → Executor calls router.depositFor(..., user=<user>) → Shares sent to user
```

Because msg.sender is the LiFi Executor (not the user), the router checks `authorizedCallers[msg.sender]` to authorize the call.

## depositFor

Primary entry point. Two overloaded forms are exposed for backward compatibility:

```solidity
// 8-arg (preferred) — includes slippage floor
function depositFor(
    address vault,
    address asset,
    uint256 amount,
    address user,
    bytes32 partnerId,
    uint8 partnerType,
    bool isERC4626,
    uint256 minSharesOut
) public;

// 7-arg (compat) — forwards to the 8-arg form with minSharesOut = 0
function depositFor(
    address vault,
    address asset,
    uint256 amount,
    address user,
    bytes32 partnerId,
    uint8 partnerType,
    bool isERC4626
) external;
```

Access control inside both forms:

```solidity
require(msg.sender == user || authorizedCallers[msg.sender], "Unauthorized caller");
```

## depositRequestFor

For vaults with async deposit queues (Yearn-style `requestDeposit`):

```solidity
function depositRequestFor(
    address vault,
    address asset,
    uint256 amount,
    address user,
    bytes32 partnerId,
    uint8 partnerType
) external;
```

Emits `DepositRequestRouted(partnerId, partnerType, user, vault, asset, amount, requestId)`.

## Events

```solidity
event Routed(
    bytes32 indexed partnerId,
    uint8 partnerType,
    address indexed user,
    address indexed vault,
    address asset,
    uint256 amount,
    uint256 shares     // NEW in V3.1.0
);

event DepositRequestRouted(
    bytes32 indexed partnerId,
    uint8 partnerType,
    address indexed user,
    address indexed vault,
    address asset,
    uint256 amount,
    uint256 requestId
);

event VaultAdapterUpdated(address indexed vault, address indexed adapter);
event AuthorizedCallerUpdated(address indexed caller, bool authorized);
```

## Vault Dispatch Priority

`_executeVaultCall` picks the deposit path in this order:

| Priority | Mapping                              | Call emitted                                          |
| -------- | ------------------------------------ | ----------------------------------------------------- |
| 1        | `vaultAdapters[vault]`               | `IVaultAdapter(adapter).deposit(...)`                 |
| 2        | `midasVaults[vault]`                 | `midasIssuance.depositInstant(asset, amt18, 0, 0)`    |
| 3        | `vedaTellers[vault]`                 | `teller.deposit(asset, amount, 0)`                    |
| 4        | `lidoDepositQueues[vault][asset]`    | `queue.deposit(uint224(amount), address(0), [])`      |
| 5        | `isERC4626 == true`                  | `vault.deposit(amount, recipient)`                    |
| 6        | fallback                             | `vault.syncDeposit(amount, recipient, address(0))`    |

Every path checks shares > 0 and cross-verifies `balanceOf(recipient)` deltas to fail closed.

### Vault Adapter Pattern

New vault protocols can be added without a router upgrade. Deploy an adapter implementing `IVaultAdapter`:

```solidity
interface IVaultAdapter {
    function deposit(
        address vault,
        address asset,
        uint256 amount,
        address recipient
    ) external returns (uint256 shares);
}
```

The router transfers `amount` of `asset` to the adapter and calls `adapter.deposit(...)`. The adapter must (a) return the actual share count and (b) deliver those shares to `recipient`. Retained assets on the adapter revert the deposit.

Register an adapter:
```solidity
router.setVaultAdapter(vaultAddress, adapterAddress);      // single
router.setVaultAdapterBatch(vaults[], adapters[]);          // batch
```

## Authorized Callers (V3.1.0)

Who can call `depositFor(..., user=<someoneElse>)`:

- `msg.sender == user` — always allowed (same-chain direct deposits)
- `authorizedCallers[msg.sender] == true` — LiFi Executor / Diamond in production

Admin management:
```solidity
router.setAuthorizedCaller(caller, true);
router.setAuthorizedCallerBatch(callers[], flags[]);
```

Currently whitelisted on composer-capable chains (Ethereum, Base, Arbitrum, Optimism):
- `0x4DaC9d1769b9b304cb04741DCDEb2FC14aBdF110` — LiFi Executor (current, CREATE3 deterministic)
- `0x2dC0E2aa608532Da689e89e237dF582B783E5408` — LiFi Executor (legacy variant, defensive)
- `0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE` — LiFi Diamond (same-chain composer)

## Admin Functions

Owner-only:

| Function                                 | Purpose                                                    |
| ---------------------------------------- | ---------------------------------------------------------- |
| `setVaultAdapter(vault, adapter)`        | Register a vault protocol integration                      |
| `setVaultAdapterBatch(vaults, adapters)` | Batch variant                                              |
| `setMidasVault(token, iv)`               | Map a Midas share token to its issuance vault              |
| `setVedaTeller(vault, teller)`           | Map a Veda BoringVault to its teller                       |
| `setLidoDepositQueue(vault, asset, q)`   | Map a Lido vault to its SyncDepositQueue                   |
| `setAuthorizedCaller(caller, ok)`        | Whitelist a composer caller                                |
| `setVaultAllowed(vault, ok)`             | Optional vault-level whitelist                             |
| `setVaultWhitelistEnabled(bool)`         | Enable/disable the vault allowlist                         |
| `pause()` / `unpause()`                  | Circuit breaker                                            |
| `rescueERC20(token, to, amt)`            | Recover any stuck ERC-20 (should never be needed)          |
| `withdrawETH()`                          | Withdraw any native ETH that landed on the contract        |
| `transferOwnership(newOwner)`            | Step 1 of two-step ownership transfer                      |
| `acceptOwnership()`                      | Step 2 — pending owner accepts                             |

## Security Properties

- **No custody** — contract never holds a positive balance between transactions. Any stuck balance is rescuable by owner.
- **No fees** — 100% of the deposited amount is forwarded to the vault. Attribution is event-only.
- **Access-controlled `user` spoofing** — non-authorized callers can only pass `user == msg.sender`.
- **Reentrancy protected** — all state-mutating deposit paths use the OpenZeppelin `ReentrancyGuard`.
- **Optional vault allowlist** — `vaultWhitelistEnabled` can gate which vaults can be deposited into. Off by default.
- **Two-step ownership** — prevents accidental transfer to dead addresses.
- **UUPS upgradeable** — owner-controlled, storage layout preserved across all upgrades via `_deprecated_` padding.

## API Integration Notes

The Yieldo API (`/v1/quote/build`) returns pre-encoded `depositFor` calldata using the **7-arg form** for maximum backward compat during the rollout window. After all integrators have migrated, the API will switch to the 8-arg form with a computed `minSharesOut` for real slippage protection.

Users never sign an intent or typed-data message for deposits anymore — they only sign the approval (for ERC-20) and the deposit transaction itself. Withdrawals are handled by the vault protocols directly (ERC-4626 `redeem` / `withdraw`) and are outside the router's scope.
