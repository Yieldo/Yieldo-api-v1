import { useState, useEffect } from 'react'
import { fetchChains, fetchTokens } from '../api'
import { parseUnits } from 'viem'

export default function Configure({
  vault, srcChain, setSrcChain, srcToken, setSrcToken,
  tokenDecimals, setTokenDecimals, amount, setAmount,
  slippage, setSlippage, onNext, goBack
}) {
  const [chains, setChains] = useState([])
  const [tokens, setTokens] = useState([])
  const [tokensLoading, setTokensLoading] = useState(false)
  const [humanAmt, setHumanAmt] = useState('')
  const [amtError, setAmtError] = useState(null)

  useEffect(() => {
    fetchChains(true).then(setChains).catch(() => {})
  }, [])

  useEffect(() => {
    if (!srcChain) return
    setTokensLoading(true)
    fetchTokens(srcChain)
      .then(t => {
        setTokens(t)
        if (t.length && !t.find(tk => tk.address === srcToken)) {
          setSrcToken(t[0].address)
          setTokenDecimals(t[0].decimals)
        }
        setTokensLoading(false)
      })
      .catch(() => setTokensLoading(false))
  }, [srcChain])

  function pickToken(t) {
    setSrcToken(t.address)
    setTokenDecimals(t.decimals)
  }

  function onAmountChange(val) {
    setHumanAmt(val)
    setAmtError(null)
    if (!val || isNaN(+val) || +val <= 0) {
      setAmount('')
      return
    }
    try {
      const raw = parseUnits(val, tokenDecimals)
      setAmount(raw.toString())
    } catch {
      setAmtError('Invalid amount')
      setAmount('')
    }
  }

  const selectedTokenInfo = tokens.find(t => t.address === srcToken)

  return (
    <>
      {vault && (
        <div className="alert alert-info" style={{ marginBottom: 16 }}>
          Vault: <strong>{vault.name}</strong> on {vault.chain_name} ({vault.asset.symbol})
        </div>
      )}

      <div className="card">
        <div className="card-title">Source Chain & Token</div>
        <div className="form-row">
          <div className="fg">
            <label>Source Chain</label>
            <select value={srcChain} onChange={e => setSrcChain(+e.target.value)}>
              {chains.map(c => (
                <option key={c.chain_id} value={c.chain_id}>{c.name} ({c.chain_id})</option>
              ))}
            </select>
          </div>
          <div className="fg">
            <label>Source Token</label>
            <select
              value={srcToken || ''}
              onChange={e => {
                const t = tokens.find(tk => tk.address === e.target.value)
                if (t) pickToken(t)
              }}
            >
              {tokens.map(t => (
                <option key={t.address} value={t.address}>{t.symbol}</option>
              ))}
            </select>
          </div>
        </div>

        {tokensLoading ? (
          <div className="alert alert-info"><span className="spinner" /> Loading tokens...</div>
        ) : (
          <div className="token-grid">
            {tokens.map(t => (
              <div
                key={t.address}
                className={`token-chip ${srcToken === t.address ? 'selected' : ''}`}
                onClick={() => pickToken(t)}
              >
                {t.logo_uri ? (
                  <img src={t.logo_uri} alt="" onError={e => e.target.style.display='none'} />
                ) : (
                  <div style={{ width:22, height:22, borderRadius:'50%', background:'var(--s3)' }} />
                )}
                <span className="tsym">{t.symbol}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title">Amount</div>
        <div className="form-row">
          <div className="fg">
            <label>Amount ({selectedTokenInfo?.symbol || 'tokens'})</label>
            <input
              type="text" placeholder="e.g. 10.5"
              value={humanAmt} onChange={e => onAmountChange(e.target.value)}
            />
            {selectedTokenInfo && (
              <div className="hint">{selectedTokenInfo.symbol} has {selectedTokenInfo.decimals} decimals</div>
            )}
            {amtError && <div className="hint" style={{ color:'var(--red)' }}>{amtError}</div>}
          </div>
          <div className="fg">
            <label>Raw amount (wei)</label>
            <input value={amount} readOnly style={{ opacity: 0.6 }} />
          </div>
        </div>
        <div className="form-row">
          <div className="fg">
            <label>Slippage</label>
            <select value={slippage} onChange={e => setSlippage(+e.target.value)}>
              <option value={0.005}>0.5%</option>
              <option value={0.01}>1%</option>
              <option value={0.03}>3%</option>
              <option value={0.05}>5%</option>
            </select>
          </div>
        </div>
        <div className="btn-row">
          <button className="btn btn-outline" onClick={goBack}>Back</button>
          <button className="btn btn-primary" onClick={onNext} disabled={!amount || !srcToken}>
            Get Quote
          </button>
        </div>
      </div>
    </>
  )
}
