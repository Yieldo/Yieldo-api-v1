---
title: "Deposit Router Contracts"
description: "Smart contract architecture, attribution system, and vault integrations"
---

The Deposit Router is the core smart contract that executes vault deposits on behalf of users. It's an attribution-only pass-through — no fees are deducted, 100% of the user's tokens go into the vault, and a `Routed` event is emitted for on-chain attribution.

## Contract Addresses

All chains are on V3.0 (attribution-only). Same address on Katana and HyperEVM by coincidence — these are separate contracts on separate chains.

| Chain    | Chain ID | Address                                      |
| -------- | -------- | -------------------------------------------- |
| Ethereum | 1        | `0x85f76c1685046Ea226E1148EE1ab81a8a15C385d` |
| Base     | 8453     | `0xF6B7723661d52E8533c77479d3cad534B4D147Aa` |
| Arbitrum | 42161    | `0xC5700f4D8054BA982C39838D7C33442f54688bd2` |
| Optimism | 10       | `0x7554937Aa95195D744A6c45E0fd7D4F95A2F8F72` |
| Monad    | 143      | `0xCD8dfD627A3712C9a2B079398e0d524970D5E73F` |
| HyperEVM | 999      | `0xa682CD1c2Fd7c8545b401824096A600C2bD98F69` |
| Katana   | 747474   | `0xa682CD1c2Fd7c8545b401824096A600C2bD98F69` |

## How Deposits Work

### Same-Chain Deposits

```
User approves tokens to router → Calls depositFor() → Router deposits into vault → Shares sent to user → Routed event emitted
```

### Cross-Chain Deposits (Two-Step)

```
User sends bridge tx (source chain) → LiFi bridges tokens to user on destination → User approves + calls depositFor() on destination → Shares sent to user
```

### Cross-Chain Deposits (Single-Step, Composer)

```
User sends bridge tx → LiFi bridges + calls depositFor() on destination in one step → Shares sent to user
```

## depositFor

The primary entry point for all deposits:

```solidity
function depositFor(
    address vault,        // Target vault contract
    address asset,        // Token being deposited
    uint256 amount,       // Amount to deposit
    address user,         // Recipient of vault shares
    bytes32 partnerId,    // Attribution: hash of partner slug
    uint8 partnerType,    // 0=direct, 1=kol, 2=wallet
    bool isERC4626        // true for standard vaults, false for custom
) external
```

Emits:

```solidity
event Routed(
    bytes32 indexed partnerId,
    uint8 partnerType,
    address indexed user,
    address indexed vault,
    address asset,
    uint256 amount
);
```

## Vault Dispatch

The router determines how to deposit based on this priority:

1. **Vault Adapter** — if `vaultAdapters[vault]` is set, delegate to the adapter
2. **Midas** — if `midasVaults[vault]` is set, use `depositInstant` on the issuance vault
3. **Veda** — if `vedaTellers[vault]` is set, use `teller.deposit`
4. **Lido** — if `lidoDepositQueues[vault][asset]` is set, use `queue.deposit`
5. **ERC-4626** — if `isERC4626=true`, call `vault.deposit(amount, recipient)`
6. **Custom** — call `vault.syncDeposit(amount, recipient, address(0))`

### Vault Adapter Pattern

New vault protocols can be integrated without upgrading the router. Deploy an adapter contract implementing `IVaultAdapter`:

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

Then register it: `router.setVaultAdapter(vaultAddress, adapterAddress)`.

## Supported Vault Types

### ERC-4626 Vaults
Standard tokenized vault interface. Router calls `vault.deposit(amount, recipient)`.

### Midas Vaults
Deposits go through a separate issuance vault with `depositInstant`. Amount is normalized to 18 decimals.

### Veda BoringVault
Deposits routed through a Teller contract: `teller.deposit(asset, amount, 0)`.

### Lido Earn
Deposits through SyncDepositQueue: `queue.deposit(uint224(amount), address(0), proof)`. Reverts if the price report is stale.

### Request-Based Vaults
For async deposits: `vault.requestDeposit(amount, recipient, controller)`.

## Security

- **No custody** — tokens are held only for the duration of the transaction (single block)
- **No fees** — 100% of tokens go to the vault
- **Pausable** — owner can pause all operations in an emergency
- **Reentrancy guard** — all deposit functions are protected
- **Vault whitelist** — optional access control for approved vaults
- **Two-step ownership** — prevents accidental ownership transfer
- **UUPS upgradeable** — implementation can be upgraded by owner

## Key Events

| Event                  | Description                           |
| ---------------------- | ------------------------------------- |
| `Routed`               | Deposit completed with attribution    |
| `DepositRequestRouted` | Async deposit queued with attribution |
| `VaultAdapterUpdated`  | New adapter registered for a vault    |
