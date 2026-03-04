const API = 'http://localhost:8000'

export async function apiFetch(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body) opts.body = JSON.stringify(body)
  const res = await fetch(API + path, opts)
  const data = await res.json()
  if (!res.ok) throw { status: res.status, data }
  return data
}

export async function checkHealth() {
  try {
    const d = await apiFetch('GET', '/health')
    return d.status === 'ok'
  } catch {
    return false
  }
}

export function fetchChains(source = false) {
  return apiFetch('GET', `/v1/chains?source=${source}`)
}

export function fetchTokens(chainId) {
  return apiFetch('GET', `/v1/tokens?chain_id=${chainId}`)
}

export function fetchVaults(chainId, asset) {
  let path = '/v1/vaults'
  const params = []
  if (chainId) params.push(`chain_id=${chainId}`)
  if (asset) params.push(`asset=${asset}`)
  if (params.length) path += '?' + params.join('&')
  return apiFetch('GET', path)
}

export function fetchVaultDetail(vaultId) {
  return apiFetch('GET', `/v1/vaults/${encodeURIComponent(vaultId)}`)
}

export function fetchQuote(body) {
  return apiFetch('POST', '/v1/quote', body)
}

export function fetchBuild(body) {
  return apiFetch('POST', '/v1/quote/build', body)
}

export function fetchStatus(txHash, fromChainId, toChainId) {
  return apiFetch('GET', `/v1/status?tx_hash=${txHash}&from_chain_id=${fromChainId}&to_chain_id=${toChainId}`)
}

export function fetchIntentStatus(intentHash, chainId) {
  return apiFetch('GET', `/v1/intent-status?intent_hash=${intentHash}&chain_id=${chainId}`)
}
