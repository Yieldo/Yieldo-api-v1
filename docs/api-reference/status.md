---
title: "Status & Tracking"
description: "Track cross-chain transfers and on-chain intent status"
---

## Get Transfer Status

Track the progress of a cross-chain deposit by its source transaction hash.

```
GET /v1/status
```

### Query Parameters

| Parameter       | Type    | Required | Description                     |
| --------------- | ------- | -------- | ------------------------------- |
| `tx_hash`       | string  | Yes      | Source chain transaction hash   |
| `from_chain_id` | integer | Yes      | Source chain ID                 |
| `to_chain_id`   | integer | Yes      | Destination chain ID            |

### Example Request

```bash
curl "https://api.yieldo.xyz/v1/status?tx_hash=0xabc...&from_chain_id=42161&to_chain_id=8453"
```

### Response

```json
{
  "status": "DONE",
  "substatus": null,
  "sending": {
    "tx_hash": "0xabc...",
    "tx_link": "https://arbiscan.io/tx/0xabc...",
    "amount": "1000000000",
    "chain_id": 42161
  },
  "receiving": {
    "tx_hash": "0xdef...",
    "tx_link": "https://basescan.org/tx/0xdef...",
    "amount": "999500000",
    "chain_id": 8453
  },
  "bridge": "stargate",
  "lifi_explorer": "https://explorer.li.fi/tx/0xabc..."
}
```

### Status Values

| Status      | Description                                    |
| ----------- | ---------------------------------------------- |
| `DONE`      | Transfer completed successfully                |
| `PENDING`   | Transfer is in progress                        |
| `FAILED`    | Transfer failed                                |
| `NOT_FOUND` | Transaction not yet indexed                    |

### Response Fields

| Field           | Type        | Description                              |
| --------------- | ----------- | ---------------------------------------- |
| `status`        | string      | Current transfer status                  |
| `substatus`     | string/null | Additional status detail from LiFi       |
| `sending`       | object/null | Source chain transaction info            |
| `receiving`     | object/null | Destination chain transaction info       |
| `bridge`        | string/null | Bridge protocol used                     |
| `lifi_explorer` | string/null | Link to LiFi explorer for this transfer  |

### Errors

| Status | Description              |
| ------ | ------------------------ |
| 404    | Transaction not found    |

---

## Get Intent Status

Check the on-chain status of a deposit intent directly from the deposit router contract.

```
GET /v1/intent-status
```

### Query Parameters

| Parameter     | Type    | Required | Description                                    |
| ------------- | ------- | -------- | ---------------------------------------------- |
| `intent_hash` | string  | Yes      | Intent hash (bytes32 hex string)               |
| `chain_id`    | integer | Yes      | Chain ID where the deposit router is deployed  |

### Example Request

```bash
curl "https://api.yieldo.xyz/v1/intent-status?intent_hash=0xabc123...&chain_id=8453"
```

### Response

```json
{
  "intent_hash": "0xabc123...",
  "chain_id": 8453,
  "user": "0xUserAddress...",
  "vault": "0xVaultAddress...",
  "asset": "0xAssetAddress...",
  "amount": "1000000000",
  "deadline": "1711900000",
  "timestamp": "1711895000",
  "executed": true,
  "cancelled": false,
  "explorer_link": "https://basescan.org/tx/0xabc123..."
}
```

### Response Fields

| Field           | Type   | Description                              |
| --------------- | ------ | ---------------------------------------- |
| `intent_hash`   | string | The queried intent hash                  |
| `chain_id`      | int    | Chain ID                                 |
| `user`          | string | User address from the intent             |
| `vault`         | string | Vault address from the intent            |
| `asset`         | string | Asset address from the intent            |
| `amount`        | string | Deposit amount                           |
| `deadline`      | string | Intent deadline (Unix timestamp)         |
| `timestamp`     | string | When the intent was recorded on-chain    |
| `executed`      | bool   | Whether the deposit was executed         |
| `cancelled`     | bool   | Whether the intent was cancelled         |
| `explorer_link` | string | Block explorer link                      |

### Errors

| Status | Description                                    |
| ------ | ---------------------------------------------- |
| 400    | No deposit router on the specified chain, or invalid intent hash |
