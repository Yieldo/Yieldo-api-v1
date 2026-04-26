---
title: "Vaults"
description: "List and inspect available yield vaults"
---

## List Vaults

Returns all available vaults. Optionally filter by chain or asset.

```
GET /v1/vaults
```

### Query Parameters

| Parameter  | Type    | Required | Description                         |
| ---------- | ------- | -------- | ----------------------------------- |
| `chain_id` | integer | No       | Filter by chain ID (e.g. `8453`)    |
| `asset`    | string  | No       | Filter by asset symbol (e.g. `usdc`)|

### Response

Returns an array of vault objects.

```json
[
  {
    "vault_id": "1:0x014e6da8f283c4af65b2aa0f201438680a004452",
    "name": "Lido Earn USD",
    "address": "0x014e6dA8F283c4Af65B2aa0F201438680a004452",
    "chain_id": 1,
    "chain_name": "Ethereum",
    "asset": {
      "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
      "symbol": "usdt",
      "decimals": 6
    },
    "accepted_assets": [
      { "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "symbol": "usdt", "decimals": 6 },
      { "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "symbol": "usdc", "decimals": 6 }
    ],
    "deposit_router": "0x85f76c1685046Ea226E1148EE1ab81a8a15C385d",
    "type": "lido",
    "paused": false
  }
]
```

### Response Fields

| Field             | Type        | Description                                                     |
| ----------------- | ----------- | --------------------------------------------------------------- |
| `vault_id`        | string      | Unique identifier for the vault (`<chain_id>:<address>`)        |
| `name`            | string      | Human-readable vault name                                       |
| `address`         | string      | Vault contract address                                          |
| `chain_id`        | int         | Chain ID where the vault is deployed                            |
| `chain_name`     | string      | Human-readable chain name                                       |
| `asset`           | object      | Primary deposit asset (used as the default for swaps)           |
| `asset.address`   | string      | Asset token contract address                                    |
| `asset.symbol`    | string      | Asset token symbol                                              |
| `asset.decimals`  | int         | Asset token decimals                                            |
| `accepted_assets` | array       | All tokens this vault accepts as direct deposits (no swap). Defaults to `[asset]` for single-asset vaults. Use this to surface multi-asset deposit options in your UI. |
| `deposit_router`  | string      | Deposit router contract address                                 |
| `type`            | string      | Vault type (`morpho`, `lido`, `veda`, `midas`, `ipor`, etc.)    |
| `paused`          | bool        | True when deposits are temporarily disabled upstream            |
| `paused_reason`   | string/null | Human-readable reason when `paused=true`                        |
| `min_deposit`     | string/null | Minimum deposit amount (raw units) when the vault enforces one  |

### Example

```bash
# All vaults
curl https://api.yieldo.xyz/v1/vaults

# USDC vaults on Base only
curl "https://api.yieldo.xyz/v1/vaults?chain_id=8453&asset=usdc"
```

---

## Get Vault Details

Returns detailed information about a specific vault, including on-chain data like total assets, total supply, and share price.

```
GET /v1/vaults/{vault_id}
```

### Path Parameters

| Parameter  | Type   | Required | Description       |
| ---------- | ------ | -------- | ----------------- |
| `vault_id` | string | Yes      | The vault ID      |

### Response

```json
{
  "vault_id": "base-steakhouse-prime-usdc",
  "name": "Steakhouse Prime USDC",
  "address": "0xBEEFE94c8aD530842bfE7d8B397938fFc1cb83b2",
  "chain_id": 8453,
  "chain_name": "Base",
  "asset": {
    "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "symbol": "USDC",
    "decimals": 6
  },
  "deposit_router": "0xF6B7723661d52E8533c77479d3cad534B4D147Aa",
  "type": "erc4626",
  "total_assets": "15000000000000",
  "total_supply": "14800000000000",
  "share_price": "1013513513513513513"
}
```

### Additional Fields

| Field          | Type        | Description                                         |
| -------------- | ----------- | --------------------------------------------------- |
| `total_assets` | string/null | Total assets in the vault (raw units)               |
| `total_supply` | string/null | Total vault shares in circulation                   |
| `share_price`  | string/null | Price per share scaled to 18 decimals               |

### Errors

| Status | Description               |
| ------ | ------------------------- |
| 404    | Vault not found           |
