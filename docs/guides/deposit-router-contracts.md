# Deposit Router Contracts

The Deposit Router is the core smart contract that executes vault deposits on behalf of users. It uses an intent-based architecture where users sign an EIP-712 message authorizing a deposit, and the router executes it.

## Contract Addresses

| Chain    | Chain ID | Address                                      |
| -------- | -------- | -------------------------------------------- |
| Ethereum | 1        | `0x85f76c1685046Ea226E1148EE1ab81a8a15C385d` |
| Base     | 8453     | `0xF6B7723661d52E8533c77479d3cad534B4D147Aa` |

## DepositIntent

Every deposit starts with a signed intent:

```solidity
struct DepositIntent {
    address user;       // Depositor's address
    address vault;      // Target vault contract
    address asset;      // Token being deposited (e.g. USDC)
    uint256 amount;     // Amount to deposit
    uint256 nonce;      // Per-user nonce (replay protection)
    uint256 deadline;   // Unix timestamp after which intent expires
}
```

The intent is signed via **EIP-712** (`eth_signTypedData_v4`) with domain:

```
name: "DepositRouter"
version: "1"
chainId: <destination chain ID>
verifyingContract: <deposit router address>
```

## How Deposits Work

### Same-Chain Deposits

```
User signs intent → Approve token → Send tx to router
                                          ↓
                              Router pulls tokens from user
                                          ↓
                              Fee deducted (10 bps)
                                          ↓
                              Tokens deposited into vault
                                          ↓
                              Vault shares sent to user
```

The router calls `safeTransferFrom` to pull tokens from the user, deducts the fee, then deposits the remainder into the vault.

### Cross-Chain Deposits

```
User signs intent → Approve token → Send bridge tx (source chain)
                                          ↓
                              LiFi bridges tokens to destination chain
                                          ↓
                              Router receives tokens + executes deposit
                                          ↓
                              Slippage validated via oracle
                                          ↓
                              Fee deducted (10 bps)
                                          ↓
                              Tokens deposited into vault
                                          ↓
                              Vault shares sent to user
```

For cross-chain deposits, the bridge delivers tokens directly to the router contract. The router then validates slippage against a Pyth oracle, deducts fees, and deposits into the vault.

## Supported Vault Types

The router supports multiple vault integration patterns:

### ERC-4626 Vaults

Standard tokenized vault interface. The router calls `vault.deposit(amount, recipient)` and shares are minted directly to the user.

```solidity
vault.deposit(depositAmount, recipient)
```

### Veda BoringVault

For Veda protocol vaults, the router interacts with a Teller contract:

```solidity
teller.deposit(asset, depositAmount, 0)
// Shares minted to router, then transferred to user
```

### Request-Based Vaults

Some vaults use async deposits with a request queue:

```solidity
vault.requestDeposit(amount, recipient, controller)
// Returns a requestId for later fulfillment
```

## Revenue Share & Fees

```
feeAmount    = (amount * feeBps) / 10000    // Default: 10 bps (0.1%)
depositAmount = amount - feeAmount
```

Yieldo has agreements with curators and vault platforms to share revenue with wallets and distributors. 100% of curator revenue share is passed to the distributor.

**On-chain fee distribution (10 bps):**

| Scenario                          | Fee Collector | Wallet/Distributor |
| --------------------------------- | ------------- | ------------------ |
| No referrer                       | 100%          | 0%                 |
| With referrer (wallet/distributor)| 50%           | 50%                |

Wallets and distributors earn 50% of the on-chain fee by passing their address as the `referrer` parameter. Referral earnings are tracked per token per referrer on-chain.

## Cross-Chain Slippage Protection

For cross-chain deposits, the router validates the received amount against the expected amount using a Pyth price oracle:

```
actualUsd >= expectedUsd * (10000 - maxSlippageBps) / 10000
actualUsd >= minDepositUsd
```

This prevents deposits from executing if the bridge delivered significantly fewer tokens than expected.

## Security Features

- **Nonce replay protection** - Each intent increments the user's nonce, preventing the same intent from being used twice
- **Deadline enforcement** - Intents expire after the specified deadline
- **Pausable** - Owner can pause all operations in an emergency
- **Reentrancy guard** - All deposit functions are protected against reentrancy
- **Vault whitelist** - Optional access control to restrict which vaults can receive deposits
- **Two-step ownership** - Prevents accidental ownership transfer

## Intent Lifecycle

```
Created → Executed
       → Cancelled (by user, before deadline)
       → Expired (deadline passed, not executed)
```

Users can cancel unexecuted intents before the deadline by calling `cancelIntent(intentHash)`.

## Key Events

| Event                        | Description                           |
| ---------------------------- | ------------------------------------- |
| `DepositExecuted`            | Same-chain deposit completed          |
| `CrossChainDepositExecuted`  | Cross-chain deposit completed         |
| `DepositIntentCreated`       | Intent recorded on-chain              |
| `DepositIntentCancelled`     | User cancelled an intent              |
| `FeeCollected`               | Fee transferred to collector          |
| `ReferralFeeCollected`       | Referral fee paid out                 |
| `DepositRequestSubmitted`    | Async deposit queued (request vaults) |

## View Functions

| Function                  | Description                                 |
| ------------------------- | ------------------------------------------- |
| `getNonce(user)`          | Current nonce for a user                    |
| `getDeposit(intentHash)`  | Full deposit record                         |
| `isIntentValid(intentHash)` | Whether an intent can still be executed   |
| `verifyIntent(intent, sig)` | Verify an EIP-712 signature              |
| `getUsdValue(asset, amount)` | Get USD value via oracle                |
| `getReferralEarnings(referrer, asset)` | Track referral fee earnings   |
