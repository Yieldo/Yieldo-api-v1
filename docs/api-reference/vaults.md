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
    "type": "erc4626"
  }
]
```

### Response Fields

| Field            | Type   | Description                              |
| ---------------- | ------ | ---------------------------------------- |
| `vault_id`       | string | Unique identifier for the vault          |
| `name`           | string | Human-readable vault name                |
| `address`        | string | Vault contract address                   |
| `chain_id`       | int    | Chain ID where the vault is deployed     |
| `chain_name`     | string | Human-readable chain name                |
| `asset`          | object | Underlying asset details                 |
| `asset.address`  | string | Asset token contract address             |
| `asset.symbol`   | string | Asset token symbol                       |
| `asset.decimals` | int    | Asset token decimals                     |
| `deposit_router` | string | Deposit router contract address          |
| `type`           | string | Vault type (e.g. `"erc4626"`, `"custom"`)|

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
