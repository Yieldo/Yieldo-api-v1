import { useState, useEffect } from 'react'
import { fetchQuote } from '../api'
import JsonViewer from './JsonViewer'

export default function QuoteView({
  vault, srcChain, srcToken, amount, slippage, address,
  tokenDecimals, quoteData, setQuoteData, onNext, goBack
}) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    doFetch()
  }, [])

  async function doFetch() {
    if (!address) { setError('Connect wallet first'); return }
    if (!vault) { setError('Select a vault first'); return }
    if (!amount) { setError('Enter an amount'); return }

    setLoading(true)
    setError(null)
    try {
      const data = await fetchQuote({
        from_chain_id: srcChain,
        from_token: srcToken,
        from_amount: amount,
        vault_id: vault.vault_id,
        user_address: address,
        slippage,
      })
      setQuoteData(data)
    } catch (e) {
      setError(e.data ? JSON.stringify(e.data, null, 2) : (e.message || 'Quote failed'))
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="card" style={{ textAlign:'center', padding:40 }}><span className="spinner" /> Fetching quote...</div>
  }

  if (error) {
    return (
      <div>
        <div className="alert alert-err">
          Quote failed
          <pre style={{ marginTop:8, fontFamily:'var(--mono)', fontSize:12, whiteSpace:'pre-wrap' }}>{error}</pre>
        </div>
        <div className="btn-row">
          <button className="btn btn-outline" onClick={goBack}>Back</button>
          <button className="btn btn-primary" onClick={doFetch}>Retry</button>
        </div>
      </div>
    )
  }

  if (!quoteData) return null

  const e = quoteData.estimate
  const intent = quoteData.intent

  return (
    <div>
      <div className="card">
        <div className="card-title">Quote Estimate</div>
        <div className="est-grid">
          <div className="est-item">
            <div className="est-label">You Send</div>
            <div className="est-val">{fmtBig(e.from_amount)}</div>
            {e.from_amount_usd && <div className="hint">${e.from_amount_usd}</div>}
          </div>
          <div className="est-item">
            <div className="est-label">Deposit Amount</div>
            <div className="est-val">{fmtBig(e.deposit_amount)}</div>
          </div>
          <div className="est-item">
            <div className="est-label">Fee ({e.fee_bps} bps)</div>
            <div className="est-val">{fmtBig(e.fee_amount)}</div>
          </div>
          {e.estimated_shares && (
            <div className="est-item">
              <div className="est-label">Est. Shares</div>
              <div className="est-val">{fmtBig(e.estimated_shares)}</div>
            </div>
          )}
          {e.estimated_time && (
            <div className="est-item">
              <div className="est-label">Est. Time</div>
              <div className="est-val">{e.estimated_time}s</div>
            </div>
          )}
          {e.gas_cost_usd && (
            <div className="est-item">
              <div className="est-label">Gas Cost</div>
              <div className="est-val">${e.gas_cost_usd}</div>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title">Quote Info</div>
        <div className="tx-detail">
          <span className="lbl">Type</span><span className="val">{quoteData.quote_type}</span>
          <span className="lbl">Vault</span><span className="val">{quoteData.vault.name} ({quoteData.vault.chain_name})</span>
          <span className="lbl">Intent Amount</span><span className="val">{intent.amount}</span>
          <span className="lbl">Nonce</span><span className="val">{intent.nonce}</span>
          <span className="lbl">Deadline</span>
          <span className="val">{intent.deadline} ({new Date(+intent.deadline * 1000).toLocaleString()})</span>
        </div>
      </div>

      <JsonViewer data={quoteData} label="Quote Response" />

      <div className="btn-row mt">
        <button className="btn btn-outline" onClick={goBack}>Back</button>
        <button className="btn btn-primary" onClick={() => doFetch()}>Refresh Quote</button>
        <button className="btn btn-green" onClick={onNext}>Sign Intent & Build TX</button>
      </div>
    </div>
  )
}

function fmtBig(raw) {
  if (!raw) return '—'
  try { return BigInt(raw).toLocaleString() } catch { return raw }
}
