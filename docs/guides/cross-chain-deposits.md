---
title: "Cross-Chain Deposits"
description: "How cross-chain deposits work - bridging, slippage, and tracking"
---

This guide covers the specifics of cross-chain deposits, where the user's tokens originate on a different chain than the target vault.

## How It Works

When a user deposits from a different chain (e.g., Arbitrum USDC into a Base vault), the flow is:

```
Source Chain                          Destination Chain
┌──────────────┐                     ┌──────────────────┐
│ User's USDC  │ ──── Bridge ─────▶  │ Deposit Router   │
│ (Arbitrum)   │   (via LiFi)        │ (Base)           │
└──────────────┘                     │   ↓              │
                                     │ Yield Vault      │
                                     │ (shares → user)  │
                                     └──────────────────┘
```

1. **LiFi finds the optimal route** - swap + bridge in one or more steps
2. **The API builds a contract-call transaction** - bridges tokens and calls the deposit router on the destination chain
3. **The deposit router executes the intent** - deposits into the vault and mints shares to the user

## Quote Types

The API returns a `quote_type` field that tells you what kind of deposit this is:

| Type              | Same Chain? | Same Token? | What Happens                    |
| ----------------- | ----------- | ----------- | ------------------------------- |
| `direct`          | Yes         | Yes         | Direct deposit, no swap         |
| `same_chain_swap` | Yes         | No          | Swap via LiFi, then deposit     |
| `cross_chain`     | No          | -           | Bridge + optional swap + deposit|

## Slippage Handling

Cross-chain deposits have additional slippage considerations:

- **User-specified slippage** (`slippage` parameter, default 3%) - applied to the LiFi swap/bridge
- **Cross-chain slippage buffer** - the API applies an additional 1% buffer on the intent amount to account for bridge slippage variability
- **Intent amount** - the signed intent uses the buffered minimum amount, so the deposit router will accept anything above that threshold

```
from_amount: 1000 USDC
  → LiFi quote: ~999.5 USDC received on destination
  → min after slippage: 969.5 USDC
  → intent amount (with buffer): 959.8 USDC
  → fee deducted from actual received amount
  → remainder deposited into vault
```

## Bridging

Yieldo uses LiFi to find the best bridge route. The API automatically:

- Selects the optimal bridge protocol
- Excludes unreliable bridges (Near, Maya, Meson, Socket)
- Uses the same bridge for the contract-call transaction as the initial quote

The `tracking.bridge` field in the build response tells you which bridge was selected (e.g., `"stargate"`, `"across"`, `"hop"`).

## Tracking Cross-Chain Transfers

Cross-chain deposits take time (typically 1-10 minutes depending on the bridge). Use the status endpoint to track progress:

```bash
GET /v1/status?tx_hash=0x...&from_chain_id=42161&to_chain_id=8453
```

### Status Progression

```
NOT_FOUND → PENDING → DONE
                    → FAILED
```

- **`NOT_FOUND`** - Transaction not yet indexed by LiFi (normal for first few seconds)
- **`PENDING`** - Bridge transfer in progress
- **`DONE`** - Tokens received on destination chain
- **`FAILED`** - Something went wrong

### Recommended Polling Interval

Poll every **15 seconds**. Most transfers complete within 2-5 minutes.

## Verifying On-Chain

After a cross-chain transfer completes, you can verify the deposit intent was executed:

```bash
GET /v1/intent-status?intent_hash=0x...&chain_id=8453
```

The `executed` field confirms whether the vault deposit was successful.

## Source Chain Support

| Chain     | Chain ID | Tokens Available                           |
| --------- | -------- | ------------------------------------------ |
| Ethereum  | 1        | USDC, USDT, WETH, WBTC, DAI, and more     |
| Base      | 8453     | USDC, WETH, and more                       |
| Arbitrum  | 42161    | USDC, USDT, WETH, and more                |
| Optimism  | 10       | USDC, WETH, and more                       |
| Avalanche | 43114    | AVAX, USDC, and more                       |
| BSC       | 56       | BNB, USDC, and more                        |

Use `GET /v1/tokens?chain_id={id}` to get the exact list of tokens for each chain.

## Error Scenarios

| Error                                      | Cause                                    | Resolution                                    |
| ------------------------------------------ | ---------------------------------------- | --------------------------------------------- |
| "No route found"                           | LiFi can't find a bridge/swap path       | Try a different source token or larger amount  |
| "LiFi contract calls quote unavailable"    | Bridge doesn't support contract calls    | Use a different source chain                   |
| "Zero output amount"                       | Amount too small after fees/slippage     | Increase the deposit amount                    |
| Transfer stuck in `PENDING`                | Bridge congestion or delays              | Wait and keep polling; bridges can be slow     |
