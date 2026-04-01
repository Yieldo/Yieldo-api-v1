# Quote & Build

## Get Quote

Returns a deposit quote with the estimated output, fees, a pre-signed intent, and a ready-to-use signature.

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
    "vault_id": "base-steakhouse-prime-usdc",
    "user_address": "0xYourAddress"
  }'
```

### Response

```json
{
  "quote_type": "cross_chain",
  "vault": {
    "vault_id": "base-steakhouse-prime-usdc",
    "name": "Steakhouse Prime USDC",
    "address": "0xBEEFE94c8aD530842bfE7d8B397938fFc1cb83b2",
    "chain_id": 8453,
    "chain_name": "Base",
    "asset": { "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "symbol": "USDC", "decimals": 6 },
    "deposit_router": "0xF6B7723661d52E8533c77479d3cad534B4D147Aa",
    "type": "erc4626"
  },
  "estimate": {
    "from_amount": "1000000000",
    "from_amount_usd": "1000.00",
    "to_amount": "999500000",
    "to_amount_min": "969515000",
    "deposit_amount": "999400050",
    "fee_amount": "99950",
    "fee_bps": 10,
    "estimated_shares": "986000000",
    "price_impact": 0.001,
    "estimated_time": 120,
    "gas_cost_usd": "0.50",
    "steps": [
      {
        "type": "swap",
        "tool": "1inch",
        "from_token": "USDC",
        "to_token": "USDC",
        "from_amount": "1000000000",
        "to_amount": "999500000",
        "estimated_time": 30
      }
    ]
  },
  "intent": {
    "user": "0xYourAddress",
    "vault": "0xBEEFE94c8aD530842bfE7d8B397938fFc1cb83b2",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "amount": "969515000",
    "nonce": "0",
    "deadline": "1711900000",
    "fee_bps": "10"
  },
  "signature": "0x...",
  "eip712": {
    "domain": {
      "name": "DepositRouter",
      "version": "1",
      "chainId": 8453,
      "verifyingContract": "0xF6B7723661d52E8533c77479d3cad534B4D147Aa"
    },
    "types": {
      "DepositIntent": [
        { "name": "user", "type": "address" },
        { "name": "vault", "type": "address" },
        { "name": "asset", "type": "address" },
        { "name": "amount", "type": "uint256" },
        { "name": "nonce", "type": "uint256" },
        { "name": "deadline", "type": "uint256" },
        { "name": "feeBps", "type": "uint256" }
      ]
    },
    "primaryType": "DepositIntent",
    "message": {
      "user": "0xYourAddress",
      "vault": "0xBEEFE94c8aD530842bfE7d8B397938fFc1cb83b2",
      "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
      "amount": "969515000",
      "nonce": "0",
      "deadline": "1711900000",
      "fee_bps": "10"
    }
  },
  "approval": {
    "token_address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "spender_address": "0xF6B7723661d52E8533c77479d3cad534B4D147Aa",
    "amount": "1000000000"
  }
}
```

### Quote Types

| Type               | Description                                                    |
| ------------------ | -------------------------------------------------------------- |
| `direct`           | Same chain, same token as the vault asset - no swap needed     |
| `same_chain_swap`  | Same chain, different token - swap via LiFi then deposit       |
| `cross_chain`      | Different chain - bridge + swap via LiFi then deposit          |

### Estimate Fields

| Field              | Type        | Description                                    |
| ------------------ | ----------- | ---------------------------------------------- |
| `from_amount`      | string      | Input amount                                   |
| `from_amount_usd`  | string/null | USD value of input                             |
| `to_amount`        | string      | Expected output in vault asset                 |
| `to_amount_min`    | string      | Minimum output after slippage                  |
| `deposit_amount`   | string      | Amount deposited into vault (after fee)        |
| `fee_amount`       | string      | Fee deducted from deposit                      |
| `fee_bps`          | int         | Fee in basis points                            |
| `estimated_shares` | string/null | Estimated vault shares received                |
| `price_impact`     | float/null  | Price impact of the swap                       |
| `estimated_time`   | int/null    | Estimated time in seconds                      |
| `gas_cost_usd`     | string/null | Estimated gas cost in USD                      |
| `steps`            | array/null  | Breakdown of swap/bridge steps                 |

### Approval

If `approval` is present (not null), the user must approve the `spender_address` to spend `amount` of `token_address` before sending the transaction. For native token deposits (ETH), `approval` will be `null`.

### Errors

| Status | Description                                     |
| ------ | ----------------------------------------------- |
| 400    | No route found or zero output amount            |
| 404    | Vault not found                                 |

---

## Build Transaction

Submit the signature from the quote response to get a ready-to-send transaction.

```
POST /v1/quote/build
```

### Request Body

| Field           | Type   | Required | Default                                      | Description                                |
| --------------- | ------ | -------- | -------------------------------------------- | ------------------------------------------ |
| `from_chain_id` | int    | Yes      |                                              | Source chain ID                             |
| `from_token`    | string | Yes      |                                              | Source token address                        |
| `from_amount`   | string | Yes      |                                              | Amount in raw token units                   |
| `vault_id`      | string | Yes      |                                              | Target vault ID                             |
| `user_address`  | string | Yes      |                                              | User's wallet address                       |
| `signature`     | string | Yes      |                                              | The `signature` from the quote response     |
| `intent_amount` | string | Yes      |                                              | The `amount` from the quote intent          |
| `nonce`         | string | Yes      |                                              | The `nonce` from the quote intent           |
| `deadline`      | string | Yes      |                                              | The `deadline` from the quote intent        |
| `fee_bps`       | string | Yes      |                                              | The `fee_bps` from the quote intent         |
| `slippage`      | float  | No       | `0.03`                                       | Slippage tolerance                          |
| `referrer`      | string | No       | `0x0000000000000000000000000000000000000000`  | Referrer address                            |

> **Important:** The `signature`, `intent_amount`, `nonce`, `deadline`, and `fee_bps` must match the exact values from the quote response. Do not recompute these.

### Example Request

```bash
curl -X POST https://api.yieldo.xyz/v1/quote/build \
  -H "Content-Type: application/json" \
  -d '{
    "from_chain_id": 42161,
    "from_token": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "from_amount": "1000000000",
    "vault_id": "base-steakhouse-prime-usdc",
    "user_address": "0xYourAddress",
    "signature": "<signature from quote response>",
    "intent_amount": "969515000",
    "nonce": "0",
    "deadline": "1711900000",
    "fee_bps": "10"
  }'
```

### Response

```json
{
  "transaction_request": {
    "to": "0xF6B7723661d52E8533c77479d3cad534B4D147Aa",
    "data": "0x...",
    "value": "0",
    "chain_id": 42161,
    "gas_limit": "500000"
  },
  "approval": {
    "token_address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "spender_address": "0xF6B7723661d52E8533c77479d3cad534B4D147Aa",
    "amount": "1000000000"
  },
  "intent": {
    "user": "0xYourAddress",
    "vault": "0xBEEFE94c8aD530842bfE7d8B397938fFc1cb83b2",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "amount": "969515000",
    "nonce": "0",
    "deadline": "1711900000",
    "fee_bps": "10"
  },
  "tracking": {
    "from_chain_id": 42161,
    "to_chain_id": 8453,
    "bridge": "stargate",
    "lifi_explorer": "https://explorer.li.fi"
  },
  "tracking_id": "abc123..."
}
```

### Transaction Request Fields

| Field       | Type        | Description                                |
| ----------- | ----------- | ------------------------------------------ |
| `to`        | string      | Contract address to call                   |
| `data`      | string      | Encoded calldata                           |
| `value`     | string      | ETH value to send (usually `"0"`)          |
| `chain_id`  | int         | Chain to submit the transaction on         |
| `gas_limit` | string/null | Suggested gas limit                        |

### Errors

| Status | Description                                          |
| ------ | ---------------------------------------------------- |
| 400    | No route found or contract calls quote unavailable   |
| 404    | Vault not found                                      |
