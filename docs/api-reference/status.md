---
title: "Status & Tracking"
description: "Track cross-chain transfer progress"
---

## Get Transfer Status

Track the progress of a cross-chain deposit by its source transaction hash. Backed by LiFi's transfer tracker.

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

## Verifying the Deposit On-Chain

V3.1.0 of the Yieldo router no longer uses signed deposit intents. Once the bridge is `DONE`, the deposit has either already happened (single-step / Composer flow) or is pending the user's step-2 tx (two-step flow). In both cases the router emits:

```solidity
event Routed(
    bytes32 indexed partnerId,
    uint8 partnerType,
    address indexed user,
    address indexed vault,
    address asset,
    uint256 amount,
    uint256 shares
);
```

Filtering this event for `user == <user>` and `vault == <vault>` on the destination chain gives you a definitive on-chain record of the deposit and the exact shares minted. The Yieldo indexer consumes this event to power `/v1/deposits` and `/v1/positions`.
