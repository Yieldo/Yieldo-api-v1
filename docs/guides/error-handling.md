# Error Handling

## Error Response Format

All API errors return a JSON body with a `detail` field:

```json
{
  "detail": "Human-readable error message"
}
```

Standard HTTP status codes are used:

| Status | Meaning                        |
| ------ | ------------------------------ |
| 400    | Bad request / invalid input    |
| 404    | Resource not found             |
| 422    | Validation error               |
| 500    | Internal server error          |

## Common Errors

### Vault Not Found (404)

```json
{ "detail": "Vault some-vault-id not found" }
```

The vault ID is invalid. Use `GET /v1/vaults` to get valid vault IDs.

### No Route Found (400)

```json
{ "detail": "No route found for this token/chain combination" }
```

LiFi could not find a swap/bridge path. Common causes:
- Token not supported on the source chain
- Amount too small to bridge
- Liquidity unavailable for this pair

**Fix:** Try a different source token, increase the amount, or try a different source chain.

### Zero Output Amount (400)

```json
{ "detail": "LiFi returned zero output amount" }
```

The input amount is too small to produce any output after fees and slippage.

**Fix:** Increase the deposit amount.

### Contract Calls Quote Unavailable (400)

```json
{ "detail": "LiFi contract calls quote unavailable for this route. Use fallback flow." }
```

The selected bridge doesn't support destination-chain contract calls, which are required for the deposit.

**Fix:** Try depositing from a different source chain, or use the vault's native chain.

### No Deposit Router (400)

```json
{ "detail": "No deposit router on chain {chain_id}" }
```

The specified chain doesn't have a deposit router deployed. Deposit routers are currently deployed on:
- Ethereum (chain ID: 1)
- Base (chain ID: 8453)

### Validation Error (422)

```json
{
  "detail": [
    {
      "loc": ["body", "from_amount"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

A required field is missing or has an invalid type. Check the request body against the API reference.

## Best Practices

1. **Always check for `approval`** - It can be `null` for native token deposits
2. **Never recompute signed values** - Use the exact `intent_amount`, `nonce`, and `deadline` from the quote response when building
3. **Handle quote expiry** - Quotes can become stale. If the build fails, fetch a new quote
4. **Poll with backoff** - For status checks, start at 15s intervals. Don't poll faster than every 10 seconds
5. **Show the LiFi explorer link** - Give users `tracking.lifi_explorer` so they can independently track their bridge transfer
