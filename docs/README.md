# Yieldo API

Yieldo is a cross-chain deposit aggregator that lets users deposit into yield vaults from any supported chain and token. The API supports **ERC-4626 vaults** and **custom vault integrations** across multiple protocols. It handles routing, bridging, and vault deposits in a single flow using an intent-based architecture.

## Base URL

```
https://api.yieldo.xyz
```

## How It Works

1. **Browse vaults** - Query available vaults across chains and protocols
2. **Get a quote** - Submit your source chain, token, and amount to receive a deposit quote with an EIP-712 intent to sign
3. **Sign the intent** - The user signs the EIP-712 typed data in their wallet
4. **Build the transaction** - Submit the signature to get a ready-to-send transaction
5. **Track status** - Monitor the deposit progress through bridging and execution

## Key Concepts

### Intent-Based Deposits

Yieldo uses an intent-based system where users sign a `DepositIntent` via EIP-712. This intent authorizes the deposit router contract to deposit funds into a vault on the user's behalf. The intent includes a deadline and nonce for replay protection.

### Cross-Chain Routing

For cross-chain deposits, Yieldo uses [LiFi](https://li.fi/) to bridge and swap tokens. The API finds the optimal route, handles slippage calculations, and builds the final transaction that bridges + deposits in a single step.

### Supported Chains

| Chain       | Chain ID | Role              |
| ----------- | -------- | ----------------- |
| Ethereum    | 1        | Source + Vaults    |
| Base        | 8453     | Source + Vaults    |
| Arbitrum    | 42161    | Source + Vaults    |
| Optimism    | 10       | Source + Vaults    |
| Avalanche   | 43114    | Source only        |
| BSC         | 56       | Source only        |

### Supported Vault Types

Yieldo supports a variety of vault standards and protocols:

| Type     | Description                          | Examples                                      |
| -------- | ------------------------------------ | --------------------------------------------- |
| ERC-4626 | Standard tokenized vault interface   | Steakhouse USDC, Gauntlet WETH Prime, Moonwell Flagship USDC |
| Custom   | Protocol-specific vault integrations | Veda Liquid ETH, Midas mTBILL, Spark USDC Vault |

Vaults span multiple protocols and curators including Steakhouse, Gauntlet, Moonwell, Midas, Veda, Upshift, MEV Capital, and more. Use `GET /v1/vaults` to see the full list.

### Fees

Yieldo charges a flat **10 bps (0.1%)** fee on the deposit amount, deducted before the vault deposit.

## Quick Example

```bash
# 1. List vaults on Base
curl https://api.yieldo.xyz/v1/vaults?chain_id=8453

# 2. Get a quote to deposit 1000 USDC from Arbitrum into a Base vault
curl -X POST https://api.yieldo.xyz/v1/quote \
  -H "Content-Type: application/json" \
  -d '{
    "from_chain_id": 42161,
    "from_token": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "from_amount": "1000000000",
    "vault_id": "base-steakhouse-prime-usdc",
    "user_address": "0xYourAddress"
  }'

# 3. Sign the returned EIP-712 data, then build the transaction
curl -X POST https://api.yieldo.xyz/v1/quote/build \
  -H "Content-Type: application/json" \
  -d '{
    "from_chain_id": 42161,
    "from_token": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "from_amount": "1000000000",
    "vault_id": "base-steakhouse-prime-usdc",
    "user_address": "0xYourAddress",
    "signature": "0xYourSignature...",
    "intent_amount": "997000000",
    "nonce": "0",
    "deadline": "1711900000"
  }'
```
