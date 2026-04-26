---
title: "Positions"
description: "Read a user's vault positions with current value and yield"
---

Returns a user's share balances across all known vaults, including current asset value and historical deposit amount for yield calculation.

```
GET /v1/positions/{user_address}
```

## Path Parameters

| Parameter       | Type   | Required | Description                   |
| --------------- | ------ | -------- | ----------------------------- |
| `user_address`  | string | Yes      | User's wallet address         |

## Query Parameters

| Parameter  | Type | Required | Description               |
| ---------- | ---- | -------- | ------------------------- |
| `chain_id` | int  | No       | Filter by chain ID        |

## How It Works

For each known vault (excluding those marked `unsupported`):

1. Read the user's share balance on-chain via `balanceOf(user)`
2. Skip if balance is zero
3. Convert shares to asset units via `vault.convertToAssets(shares)` (falls back to `totalAssets/totalSupply` ratio if unavailable)
4. Sum the user's historical net deposits to that vault (deposits − withdrawals) in vault-asset units
5. Compute yield as `current_assets − deposited_assets`

Values are in the vault asset's smallest unit (e.g. 6 decimals for USDC).

## Response

```json
{
  "user_address": "0xAb3d...",
  "positions": [
    {
      "vault_id": "1:0xbeef01735c132ada46aa9aa4c54623caa92a64cb",
      "vault_name": "Steakhouse USDC",
      "vault_address": "0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB",
      "chain_id": 1,
      "asset_symbol": "USDC",
      "asset_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
      "asset_decimals": 6,
      "share_balance": "9873521412345678",
      "share_decimals": 18,
      "vault_type": "morpho",
      "current_assets": "10412000000",
      "deposited_assets": "10000000000",
      "yield_assets": "412000000"
    }
  ]
}
```

## Fields

| Field               | Type          | Description                                                            |
| ------------------- | ------------- | ---------------------------------------------------------------------- |
| `vault_id`          | string        | Vault ID                                                               |
| `vault_name`        | string        | Display name                                                           |
| `vault_address`     | string        | Vault contract address                                                 |
| `chain_id`          | int           | Chain ID                                                               |
| `asset_symbol`      | string        | Underlying asset symbol (uppercase)                                    |
| `asset_address`     | string        | Asset token contract                                                   |
| `asset_decimals`    | int           | Asset token decimals (use to format `current_assets`, `yield_assets`)  |
| `share_balance`     | string        | Raw vault share balance                                                |
| `share_decimals`    | int           | Vault share token decimals (usually 18)                                |
| `vault_type`        | string        | `morpho`, `veda`, `midas`, `custom`, `lido`, `ipor`, or `accountable`  |
| `current_assets`    | string / null | Current asset-denominated value of shares (in asset's smallest unit)   |
| `deposited_assets`  | string / null | Sum of historical deposits for this vault (asset's smallest unit)      |
| `yield_assets`      | string / null | `current_assets - deposited_assets` — can be negative                  |

## Notes

- `current_assets`, `deposited_assets`, and `yield_assets` can each be `null` independently if the data isn't available (e.g. the vault doesn't expose share price, or the user has no recorded deposits).
- For vaults that don't support `convertToAssets`, the API falls back to `(shares * totalAssets) / totalSupply`. If both fail, `current_assets` is `null` and the frontend should display the raw share balance.
- Yield is in asset units, not USD. A portfolio with mixed assets (USDC + WETH) shouldn't be summed directly — the frontend should show per-asset totals or use a price oracle.

## Example

```bash
curl https://api.yieldo.xyz/v1/positions/0xAb3d00f8c1D6F2e5a1E4b0B92c5e7cF4a4f12e1f
```
