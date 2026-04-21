---
title: "Getting Started"
description: "Auth, request format, and a full integration walkthrough"
---

## Authentication

The Yieldo API is currently **open and does not require authentication** for public endpoints. Wallet partners can use API keys for attribution tracking.

## Base URL

All endpoints are available at:

```
https://api.yieldo.xyz
```

## Request Format

* All `POST` requests accept JSON bodies with `Content-Type: application/json`
* All `GET` requests use query parameters
* All amounts are in **raw token units** (wei for 18-decimal tokens, smallest unit for others)

## Response Format

All responses return JSON. Successful responses return the data directly. Errors return:

```json
{
  "detail": "Human-readable error message"
}
```

## Health Check

```
GET /health
```

Returns `{"status": "ok"}` when the API is running.

## Typical Integration Flow

### Step 1: Discover Vaults

Fetch the list of available vaults. Optionally filter by chain or asset.

```bash
GET /v1/vaults?chain_id=8453
```

### Step 2: Get Source Tokens

Fetch the tokens available on the user's source chain.

```bash
GET /v1/tokens?chain_id=42161
```

### Step 3: Request a Quote

Submit the user's source chain, token, amount, and target vault to get a quote.

```bash
POST /v1/quote
{
  "from_chain_id": 42161,
  "from_token": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
  "from_amount": "1000000000",
  "vault_id": "8453:0xbeefe94c8ad530842bfe7d8b397938ffc1cb83b2",
  "user_address": "0x..."
}
```

The response includes:

* **estimate** - Expected output amounts and estimated shares
* **approval** - Token approval details (if needed)
* **route_options** - Available bridge routes for cross-chain deposits

### Step 4: Token Approval

If the response includes an `approval` object, the user must approve the specified `spender_address` to spend their tokens before submitting the transaction.

### Step 5: Build the Transaction

Submit the vault and amount details to get the final transaction.

```bash
POST /v1/quote/build
{
  "from_chain_id": 42161,
  "from_token": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
  "from_amount": "1000000000",
  "vault_id": "8453:0xbeefe94c8ad530842bfe7d8b397938ffc1cb83b2",
  "user_address": "0x..."
}
```

### Step 6: Send the Transaction

Send the returned `transaction_request` using the user's wallet (`eth_sendTransaction`).

### Step 7: Track Status

For cross-chain deposits, poll the status endpoint:

```bash
GET /v1/status?tx_hash=0x...&from_chain_id=42161&to_chain_id=8453
```

## Amount Handling

All amounts in the API are strings representing raw token units:

| Token | Decimals | 1.0 token        |
| ----- | -------- | ----------------- |
| USDC  | 6        | `"1000000"`       |
| USDT  | 6        | `"1000000"`       |
| WETH  | 18       | `"1000000000000000000"` |
| WBTC  | 8        | `"100000000"`     |
