---
title: "Cross-Chain Deposits"
description: "How cross-chain deposits work — bridging, vault dispatch, and tracking"
---

This guide covers the specifics of cross-chain deposits, where the user's tokens originate on a different chain than the target vault.

## How It Works

When a user deposits from a different chain (e.g., Arbitrum USDC into a Base vault), Yieldo offers two flows depending on the target vault type:

### Single-Step (LiFi Composer)

Used for Morpho and other standard ERC-4626 vaults.

```
Source Chain                               Destination Chain
┌──────────────┐                          ┌──────────────────────────────┐
│ User's USDC  │ ── bridge (LiFi) ────▶   │ LiFi Executor receives USDC  │
│ (Arbitrum)   │                          │   ↓                          │
└──────────────┘                          │ router.depositFor(..., user) │
                                          │   ↓                          │
                                          │ Vault mints shares to user   │
                                          └──────────────────────────────┘
```

LiFi's Executor is on the router's `authorizedCallers` whitelist (V3.1.0), so it can pass `user=<user>` instead of `msg.sender`. No user signature beyond the bridge tx.

### Two-Step

Used for vault types LiFi Composer doesn't natively understand (Midas, Veda, Custom, IPOR, Lido).

```
Step 1 (source):   User sends bridge tx
                   → tokens arrive at user's wallet on destination
Step 2 (dest):     User approves + calls router.depositFor(...) themselves
                   → msg.sender == user, so no whitelist needed
                   → shares land in user's wallet
```

Step 2 is a normal same-chain deposit signed by the user. Tokens are always safe in between — they sit in the user's own wallet.

The build response signals the flow via `two_step: true|false`. See the [Deposit Flow guide](/guides/deposit-flow) for code examples of each.

## Quote Types

The API returns a `quote_type` field that tells you what kind of deposit this is:

| Type              | Same Chain? | Same Token? | What Happens                    |
| ----------------- | ----------- | ----------- | ------------------------------- |
| `direct`          | Yes         | Yes         | Direct deposit, no swap         |
| `same_chain_swap` | Yes         | No          | Swap via LiFi, then deposit     |
| `cross_chain`     | No          | -           | Bridge + optional swap + deposit|

## Slippage Handling

Cross-chain deposits have additional slippage considerations:

- **User-specified slippage** (`slippage` parameter, default 3%) — applied to the LiFi swap/bridge.
- **Cross-chain slippage buffer** — the API applies an extra ~1% buffer on the amount that will arrive on the destination, so the deposit succeeds even if the bridge slippage lands a hair below quoted.
- **Router-level `minSharesOut`** — V3.1.0 supports an 8-arg `depositFor` with an on-chain share floor. The API currently emits the 7-arg compat form (`minSharesOut=0`) during the rollout window and will switch to the 8-arg form with a computed floor in a follow-up release.

```
from_amount: 1000 USDC
  → LiFi quote: ~999.5 USDC received on destination
  → min after 3% slippage: 969.5 USDC
  → buffered deposit amount: ~959.8 USDC
  → remainder deposited into the vault by the router
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

- **`NOT_FOUND`** — Transaction not yet indexed by LiFi (normal for first few seconds)
- **`PENDING`** — Bridge transfer in progress
- **`DONE`** — Tokens received on destination chain
- **`FAILED`** — Something went wrong

### Recommended Polling Interval

Poll every **15 seconds**. Most transfers complete within 2–5 minutes.

## Verifying the Deposit On-Chain

Once the bridge is `DONE`:

- **Single-step** — the same LiFi tx on the destination emits the router's `Routed(partnerId, partnerType, user, vault, asset, amount, shares)` event. Indexers can read `shares` directly from the event (V3.1.0).
- **Two-step** — the user's own step-2 tx emits `Routed(...)` on the destination chain.

The `/v1/deposits` and `/v1/positions` endpoints consume this event for attribution and position display.

## Source Chain Support

| Chain     | Chain ID | Tokens Available                          |
| --------- | -------- | ----------------------------------------- |
| Ethereum  | 1        | USDC, USDT, WETH, WBTC, DAI, and more     |
| Base      | 8453     | USDC, WETH, and more                      |
| Arbitrum  | 42161    | USDC, USDT, WETH, and more                |
| Optimism  | 10       | USDC, WETH, and more                      |
| Monad     | 143      | USDC, WETH, and more                      |
| HyperEVM  | 999      | USDT0, WHYPE, USDC, uBTC, and more        |
| Katana    | 747474   | USDC, WETH, and more                      |
| Avalanche | 43114    | AVAX, USDC, and more                      |
| BSC       | 56       | BNB, USDC, and more                       |

Use `GET /v1/tokens?chain_id={id}` to get the exact list of tokens for each chain.

## Error Scenarios

| Error                                      | Cause                                    | Resolution                                    |
| ------------------------------------------ | ---------------------------------------- | --------------------------------------------- |
| "No route found"                           | LiFi can't find a bridge/swap path       | Try a different source token or larger amount |
| "LiFi contract calls quote unavailable"    | Bridge doesn't support contract calls    | Use a different source chain                  |
| "Zero output amount"                       | Amount too small after fees/slippage     | Increase the deposit amount                   |
| "Unauthorized caller" (on-chain revert)    | LiFi Executor not whitelisted on router  | Chain not yet on V3.1.0 — report to Yieldo    |
| Transfer stuck in `PENDING`                | Bridge congestion or delays              | Wait and keep polling; bridges can be slow    |
