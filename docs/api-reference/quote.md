---
title: "Quote & Build"
description: "Get a deposit quote with route options, then build the transaction"
---

## Get Quote

Returns a deposit quote with estimated output, route options for cross-chain deposits, and approval details.

```
POST /v1/quote
```

### Request Body

| Field           | Type   | Required | Default                                      | Description                            |
| --------------- | ------ | -------- | -------------------------------------------- | -------------------------------------- |
| `from_chain_id` | int    | Yes      |                                              | Source chain ID                        |
| `from_token`    | string | Yes      |                                              | Source token address                   |
| `from_amount`   | string | Yes      |                                              | Amount in raw token units              |
| `vault_id`      | string | Yes      |                                              | Target vault ID                        |
| `user_address`  | string | Yes      |                                              | User's wallet address                  |
| `slippage`      | float  | No       | `0.03`                                       | Slippage tolerance (0.03 = 3%)         |
| `referrer`      | string | No       | `0x0000000000000000000000000000000000000000`  | Referrer address                       |

### Example Request

```bash
curl -X POST https://api.yieldo.xyz/v1/quote \
  -H "Content-Type: application/json" \
  -d '{
    "from_chain_id": 42161,
    "from_token": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "from_amount": "1000000000",
    "vault_id": "8453:0xbeefe94c8ad530842bfe7d8b397938ffc1cb83b2",
    "user_address": "0xYourAddress"
  }'
```

### Response

```json
{
  "quote_type": "cross_chain",
  "vault": {
    "vault_id": "8453:0xbeefe94c8ad530842bfe7d8b397938ffc1cb83b2",
    "name": "Steakhouse Prime USDC",
    "address": "0xBEEFE94c8aD530842bfE7d8B397938fFc1cb83b2",
    "chain_id": 8453,
    "chain_name": "Base",
    "asset": { "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "symbol": "usdc", "decimals": 6 },
    "deposit_router": "0xF6B7723661d52E8533c77479d3cad534B4D147Aa",
    "type": "morpho"
  },
  "estimate": {
    "from_amount": "1000000000",
    "from_amount_usd": "1000.00",
    "to_amount": "999500000",
    "to_amount_min": "969515000",
    "deposit_amount": "999500000",
    "estimated_shares": "986000000",
    "price_impact": 0.001,
    "estimated_time": 120,
    "gas_cost_usd": "0.50",
    "steps": [
      { "type": "cross", "tool": "Stargate", "estimated_time": 120 }
    ]
  },
  "approval": {
    "token_address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "spender_address": "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE",
    "amount": "1000000000"
  },
  "route_options": [
    {
      "bridge": "stargate",
      "bridge_name": "Stargate",
      "bridge_logo": "https://...",
      "to_amount": "999500000",
      "to_amount_min": "969515000",
      "deposit_amount": "999500000",
      "estimated_time": 120,
      "gas_cost_usd": "0.50",
      "tags": ["RECOMMENDED", "CHEAPEST"]
    },
    {
      "bridge": "across",
      "bridge_name": "Across",
      "bridge_logo": "https://...",
      "to_amount": "998200000",
      "to_amount_min": "968254000",
      "deposit_amount": "998200000",
      "estimated_time": 5,
      "gas_cost_usd": "0.30",
      "tags": ["FASTEST"]
    }
  ]
}
```

### Quote Types

| Type               | Description                                                    |
| ------------------ | -------------------------------------------------------------- |
| `direct`           | Same chain, same token as the vault asset — no swap needed     |
| `same_chain_swap`  | Same chain, different token — swap via LiFi then deposit       |
| `cross_chain`      | Different chain — bridge + swap via LiFi then deposit          |

### Estimate Fields

| Field              | Type        | Description                                    |
| ------------------ | ----------- | ---------------------------------------------- |
| `from_amount`      | string      | Input amount                                   |
| `from_amount_usd`  | string/null | USD value of input                             |
| `to_amount`        | string      | Expected output in vault asset                 |
| `to_amount_min`    | string      | Minimum output after slippage                  |
| `deposit_amount`   | string      | Amount deposited into vault (= to_amount, no fee) |
| `estimated_shares` | string/null | Estimated vault shares received                |
| `price_impact`     | float/null  | Price impact of the swap                       |
| `estimated_time`   | int/null    | Estimated time in seconds                      |
| `gas_cost_usd`     | string/null | Estimated gas cost in USD                      |
| `steps`            | array/null  | Breakdown of swap/bridge steps                 |

### Route Options

For cross-chain deposits, `route_options` lists available bridge routes. Each route shows the bridge name, logo, output amount, estimated time, gas cost, and tags (`RECOMMENDED`, `CHEAPEST`, `FASTEST`).

Pass the selected route's `bridge` key as `preferred_bridge` when building the transaction.

---

## Build Transaction

Build a ready-to-send transaction for the deposit.

```
POST /v1/quote/build
```

### Request Body

| Field              | Type   | Required | Default                                      | Description                                |
| ------------------ | ------ | -------- | -------------------------------------------- | ------------------------------------------ |
| `from_chain_id`    | int    | Yes      |                                              | Source chain ID                             |
| `from_token`       | string | Yes      |                                              | Source token address                        |
| `from_amount`      | string | Yes      |                                              | Amount in raw token units                   |
| `vault_id`         | string | Yes      |                                              | Target vault ID                             |
| `user_address`     | string | Yes      |                                              | User's wallet address                       |
| `slippage`         | float  | No       | `0.03`                                       | Slippage tolerance                          |
| `referrer`         | string | No       | `0x0000...`                                  | Referrer address                            |
| `preferred_bridge` | string | No       |                                              | Bridge key from route_options               |
| `partner_id`       | string | No       | `""`                                         | Attribution: partner slug or handle         |
| `partner_type`     | int    | No       | `0`                                          | 0=direct, 1=kol, 2=wallet                  |

### Example Request

```bash
curl -X POST https://api.yieldo.xyz/v1/quote/build \
  -H "Content-Type: application/json" \
  -d '{
    "from_chain_id": 42161,
    "from_token": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "from_amount": "1000000000",
    "vault_id": "8453:0xbeefe94c8ad530842bfe7d8b397938ffc1cb83b2",
    "user_address": "0xYourAddress",
    "preferred_bridge": "stargate"
  }'
```

### Response (Single-Step)

For direct deposits and Morpho-compatible cross-chain deposits, the build returns a single transaction that bridges + deposits atomically via LiFi Composer. On cross-chain deposits the `to` address is LiFi's Diamond; LiFi then calls `router.depositFor(...)` on the destination chain via its bridge-specific receiver (Executor / ReceiverAcrossV4 / ReceiverStargateV2 / etc.). V3.1.1 accepts calls from any address, so new LiFi receivers work without a router upgrade. On same-chain deposits the `to` address is the Yieldo router directly.

The calldata currently uses the **7-arg `depositFor`** form (compat shim) with `minSharesOut = 0`. A future release will switch to the 8-arg form with a computed `minSharesOut` for on-chain slippage protection.

```json
{
  "transaction_request": {
    "to": "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE",
    "data": "0x...",
    "value": "0",
    "chain_id": 42161,
    "gas_limit": "500000"
  },
  "approval": {
    "token_address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "spender_address": "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE",
    "amount": "1000000000"
  },
  "tracking": {
    "from_chain_id": 42161,
    "to_chain_id": 8453,
    "bridge": "stargate",
    "lifi_explorer": "https://explorer.li.fi"
  },
  "tracking_id": "abc123...",
  "two_step": false
}
```

### Response (Two-Step Cross-Chain)

For vault types that LiFi Composer doesn't natively understand (Midas, Veda, Custom, IPOR, Lido), the response has `two_step: true`. The frontend must:

1. Execute `transaction_request` — LiFi bridges tokens to the user's wallet on the destination chain
2. Poll `/v1/status` until bridge is `DONE`
3. Execute `deposit_tx.transaction_request` (preceded by `deposit_tx.approval` if present) — a same-chain deposit on the destination

```json
{
  "transaction_request": { "to": "0x...", "data": "0x...", "value": "0", "chain_id": 42161 },
  "approval": { "token_address": "0x...", "spender_address": "0x...", "amount": "1000000000" },
  "tracking": {
    "from_chain_id": 42161,
    "to_chain_id": 1,
    "bridge": "stargate",
    "lifi_explorer": "https://explorer.li.fi"
  },
  "tracking_id": "abc123...",
  "two_step": true,
  "deposit_tx": {
    "transaction_request": {
      "to": "0x85f76c1685046Ea226E1148EE1ab81a8a15C385d",
      "data": "0x...",
      "value": "0",
      "chain_id": 1,
      "gas_limit": "900000"
    },
    "approval": {
      "token_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
      "spender_address": "0x85f76c1685046Ea226E1148EE1ab81a8a15C385d",
      "amount": "999500000"
    }
  }
}
```

This trades one extra click for near-zero revert risk on protocols whose deposit interfaces aren't composable with the bridge.

### Transaction Request Fields

| Field       | Type        | Description                                |
| ----------- | ----------- | ------------------------------------------ |
| `to`        | string      | Contract address to call                   |
| `data`      | string      | Encoded calldata                           |
| `value`     | string      | ETH value to send (usually `"0"`)          |
| `chain_id`  | int         | Chain to submit the transaction on         |
| `gas_limit` | string/null | Suggested gas limit                        |

### Top-Level Response Fields

| Field                 | Type         | Description                                                  |
| --------------------- | ------------ | ------------------------------------------------------------ |
| `transaction_request` | object       | Primary transaction (bridge+deposit or same-chain deposit)   |
| `approval`            | object/null  | ERC-20 approval required before sending the transaction      |
| `tracking`            | object       | Info for polling `/v1/status`                                |
| `tracking_id`         | string       | Internal tracking ID for correlating across our systems      |
| `two_step`            | bool         | `true` when destination deposit must be sent as a second tx  |
| `deposit_tx`          | object/null  | Step-2 details when `two_step=true`                          |

### Errors

| Status | Description                                          |
| ------ | ---------------------------------------------------- |
| 400    | No route found, below min deposit, or build failed   |
| 404    | Vault not found                                      |
