# Deposit Flow

This guide walks through the complete deposit flow for integrating Yieldo into a frontend application.

## Overview

```
User selects vault → Get quote → Approve token → Sign intent → Build tx → Send tx → Track status
```

## Step 1: Select a Vault

Fetch available vaults and let the user choose one.

```javascript
const response = await fetch('https://api.yieldo.xyz/v1/vaults?chain_id=8453');
const vaults = await response.json();
```

## Step 2: Get a Quote

Once the user specifies a source chain, token, and amount, request a quote.

```javascript
const quote = await fetch('https://api.yieldo.xyz/v1/quote', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    from_chain_id: 42161,
    from_token: '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
    from_amount: '1000000000', // 1000 USDC
    vault_id: 'base-steakhouse-prime-usdc',
    user_address: userAddress,
  }),
});
const quoteData = await quote.json();
```

The response contains:
- **`estimate`** - Shows the expected output, fees, and estimated shares
- **`intent`** - The deposit intent data
- **`eip712`** - The typed data to sign
- **`approval`** - Token approval details (if needed)

## Step 3: Approve Token Spending

If `quoteData.approval` is not null, the user needs to approve the token first.

```javascript
if (quoteData.approval) {
  const tx = await walletClient.writeContract({
    address: quoteData.approval.token_address,
    abi: erc20Abi,
    functionName: 'approve',
    args: [quoteData.approval.spender_address, quoteData.approval.amount],
  });
  await publicClient.waitForTransactionReceipt({ hash: tx });
}
```

> **Tip:** For native token deposits (e.g., ETH), the `approval` field will be `null` and you can skip this step.

## Step 4: Sign the EIP-712 Intent

Ask the user to sign the typed data returned in the quote.

```javascript
const signature = await walletClient.signTypedData({
  domain: quoteData.eip712.domain,
  types: quoteData.eip712.types,
  primaryType: quoteData.eip712.primaryType,
  message: quoteData.eip712.message,
});
```

## Step 5: Build the Transaction

Submit the signature to get the final transaction.

```javascript
const buildResponse = await fetch('https://api.yieldo.xyz/v1/quote/build', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    from_chain_id: 42161,
    from_token: '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
    from_amount: '1000000000',
    vault_id: 'base-steakhouse-prime-usdc',
    user_address: userAddress,
    signature: signature,
    intent_amount: quoteData.intent.amount,
    nonce: quoteData.intent.nonce,
    deadline: quoteData.intent.deadline,
  }),
});
const buildData = await buildResponse.json();
```

## Step 6: Send the Transaction

Send the transaction using the user's wallet.

```javascript
const txHash = await walletClient.sendTransaction({
  to: buildData.transaction_request.to,
  data: buildData.transaction_request.data,
  value: BigInt(buildData.transaction_request.value),
  chain: { id: buildData.transaction_request.chain_id },
  gas: buildData.transaction_request.gas_limit
    ? BigInt(buildData.transaction_request.gas_limit)
    : undefined,
});
```

## Step 7: Track the Deposit

For cross-chain deposits, poll the status endpoint until the transfer completes.

```javascript
async function pollStatus(txHash, fromChainId, toChainId) {
  while (true) {
    const res = await fetch(
      `https://api.yieldo.xyz/v1/status?tx_hash=${txHash}&from_chain_id=${fromChainId}&to_chain_id=${toChainId}`
    );
    const status = await res.json();

    if (status.status === 'DONE') {
      console.log('Deposit complete!', status.receiving);
      return status;
    }
    if (status.status === 'FAILED') {
      throw new Error('Transfer failed');
    }

    // Poll every 15 seconds
    await new Promise(r => setTimeout(r, 15000));
  }
}
```

## Complete Example

```javascript
async function deposit(vaultId, fromChainId, fromToken, amount, userAddress) {
  // 1. Get quote
  const quote = await getQuote(fromChainId, fromToken, amount, vaultId, userAddress);

  // 2. Approve if needed
  if (quote.approval) {
    await approveToken(quote.approval);
  }

  // 3. Sign intent
  const signature = await signIntent(quote.eip712);

  // 4. Build transaction
  const build = await buildTransaction({
    fromChainId, fromToken, amount, vaultId, userAddress,
    signature,
    intentAmount: quote.intent.amount,
    nonce: quote.intent.nonce,
    deadline: quote.intent.deadline,
  });

  // 5. Send transaction
  const txHash = await sendTransaction(build.transaction_request);

  // 6. Track (cross-chain only)
  if (fromChainId !== quote.vault.chain_id) {
    await pollStatus(txHash, fromChainId, quote.vault.chain_id);
  }

  return txHash;
}
```
