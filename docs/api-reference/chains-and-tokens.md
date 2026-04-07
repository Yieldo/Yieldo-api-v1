---
title: "Chains & Tokens"
description: "Supported blockchain networks and source tokens"
---

## List Chains

Returns supported blockchain networks.

```
GET /v1/chains
```

### Query Parameters

| Parameter | Type    | Required | Default | Description                                          |
| --------- | ------- | -------- | ------- | ---------------------------------------------------- |
| `source`  | boolean | No       | `false` | If `true`, returns all source chains. If `false`, returns vault chains only. |

### Example Request

```bash
# Vault chains (where deposits land)
curl https://api.yieldo.xyz/v1/chains

# Source chains (where users can deposit from)
curl "https://api.yieldo.xyz/v1/chains?source=true"
```

### Response

```json
[
  {
    "chain_id": 1,
    "name": "Ethereum",
    "key": "eth",
    "explorer": "https://etherscan.io"
  },
  {
    "chain_id": 8453,
    "name": "Base",
    "key": "base",
    "explorer": "https://basescan.org"
  }
]
```

### Response Fields

| Field      | Type   | Description                  |
| ---------- | ------ | ---------------------------- |
| `chain_id` | int    | EVM chain ID                 |
| `name`     | string | Human-readable chain name    |
| `key`      | string | Short chain identifier       |
| `explorer` | string | Block explorer base URL      |

---

## List Tokens

Returns the major tokens available on a given chain. These are the tokens users can deposit from.

```
GET /v1/tokens
```

### Query Parameters

| Parameter  | Type    | Required | Description                |
| ---------- | ------- | -------- | -------------------------- |
| `chain_id` | integer | Yes      | Chain ID to get tokens for |

### Example Request

```bash
curl "https://api.yieldo.xyz/v1/tokens?chain_id=42161"
```

### Response

```json
[
  {
    "address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "symbol": "USDC",
    "decimals": 6,
    "chain_id": 42161,
    "name": "USD Coin",
    "logo_uri": "https://..."
  },
  {
    "address": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
    "symbol": "USDT",
    "decimals": 6,
    "chain_id": 42161,
    "name": "Tether USD",
    "logo_uri": "https://..."
  }
]
```

### Response Fields

| Field      | Type        | Description                |
| ---------- | ----------- | -------------------------- |
| `address`  | string      | Token contract address     |
| `symbol`   | string      | Token symbol               |
| `decimals` | int         | Token decimals             |
| `chain_id` | int         | Chain ID                   |
| `name`     | string/null | Full token name            |
| `logo_uri` | string/null | Token logo image URL       |

### Supported Token Symbols

The API returns a curated list of major tokens:

`USDC` `USDT` `DAI` `WETH` `ETH` `WBTC` `BTC` `AVAX` `WAVAX` `BNB` `WBNB` `OP` `ARB` `LINK` `UNI` `AAVE` `stETH` `wstETH` `rETH` `cbETH`
