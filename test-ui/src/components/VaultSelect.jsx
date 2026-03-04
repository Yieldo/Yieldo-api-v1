import { useState, useEffect } from 'react'
import { fetchVaults } from '../api'

export default function VaultSelect({ selected, onPick }) {
  const [vaults, setVaults] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [chainFilter, setChainFilter] = useState('')
  const [assetFilter, setAssetFilter] = useState('')

  useEffect(() => {
    setLoading(true)
    fetchVaults()
      .then(v => { setVaults(v); setLoading(false) })
      .catch(e => { setError('Failed to load vaults. Is the API running?'); setLoading(false) })
  }, [])

  const chains = [...new Set(vaults.map(v => v.chain_id))]
  const assets = [...new Set(vaults.map(v => v.asset.symbol))]

  let filtered = vaults
  if (chainFilter) filtered = filtered.filter(v => v.chain_id === +chainFilter)
  if (assetFilter) filtered = filtered.filter(v => v.asset.symbol === assetFilter)

  return (
    <div className="card">
      <div className="card-title">Choose a Vault</div>
      <div className="form-row">
        <div className="fg">
          <label>Filter by chain</label>
          <select value={chainFilter} onChange={e => setChainFilter(e.target.value)}>
            <option value="">All chains</option>
            {chains.map(c => {
              const v = vaults.find(x => x.chain_id === c)
              return <option key={c} value={c}>{v?.chain_name || c} ({c})</option>
            })}
          </select>
        </div>
        <div className="fg">
          <label>Filter by asset</label>
          <select value={assetFilter} onChange={e => setAssetFilter(e.target.value)}>
            <option value="">All assets</option>
            {assets.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      </div>

      {loading && <div className="alert alert-info"><span className="spinner" /> Loading vaults...</div>}
      {error && <div className="alert alert-err">{error}</div>}

      <div className="vault-grid">
        {filtered.map(v => (
          <div
            key={v.vault_id}
            className={`vault-card ${selected?.vault_id === v.vault_id ? 'selected' : ''}`}
            onClick={() => onPick(v)}
          >
            <div className="vname">{v.name}</div>
            <div className="vmeta">
              <span className="chain-tag">{v.chain_name}</span>
              <span>{v.asset.symbol}</span>
              <span className="mono" style={{ fontSize: 11 }}>
                {v.address.slice(0, 6)}...{v.address.slice(-4)}
              </span>
            </div>
          </div>
        ))}
      </div>
      {!loading && !error && filtered.length === 0 && (
        <div className="alert alert-info">No vaults match filters</div>
      )}
    </div>
  )
}
