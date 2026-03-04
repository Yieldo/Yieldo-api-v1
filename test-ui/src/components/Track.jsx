import { useState, useEffect, useRef } from 'react'
import { fetchStatus, fetchIntentStatus, fetchChains } from '../api'
import JsonViewer from './JsonViewer'

export default function Track({ buildData, sentTxHash, srcChain }) {
  const [chains, setChains] = useState([])
  const [txHash, setTxHash] = useState(sentTxHash || '')
  const [fromChain, setFromChain] = useState(srcChain || 1)
  const [toChain, setToChain] = useState(buildData?.tracking?.to_chain_id || 1)
  const [statusData, setStatusData] = useState(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [statusError, setStatusError] = useState(null)
  const [polling, setPolling] = useState(false)
  const pollRef = useRef(null)

  const [intentHash, setIntentHash] = useState('')
  const [intentChain, setIntentChain] = useState(buildData?.tracking?.to_chain_id || 1)
  const [intentData, setIntentData] = useState(null)
  const [intentLoading, setIntentLoading] = useState(false)
  const [intentError, setIntentError] = useState(null)

  useEffect(() => {
    fetchChains(true).then(setChains).catch(() => {})
  }, [])

  useEffect(() => {
    if (sentTxHash) setTxHash(sentTxHash)
  }, [sentTxHash])

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  async function doCheckStatus() {
    if (!txHash) return
    setStatusLoading(true)
    setStatusError(null)
    try {
      const data = await fetchStatus(txHash, fromChain, toChain)
      setStatusData(data)
    } catch (e) {
      setStatusError(e.data ? JSON.stringify(e.data, null, 2) : (e.message || 'Failed'))
    } finally {
      setStatusLoading(false)
    }
  }

  function togglePoll() {
    if (polling) {
      clearInterval(pollRef.current)
      pollRef.current = null
      setPolling(false)
    } else {
      setPolling(true)
      doCheckStatus()
      pollRef.current = setInterval(doCheckStatus, 10000)
    }
  }

  async function doCheckIntent() {
    if (!intentHash) return
    setIntentLoading(true)
    setIntentError(null)
    try {
      const data = await fetchIntentStatus(intentHash, intentChain)
      setIntentData(data)
    } catch (e) {
      setIntentError(e.data ? JSON.stringify(e.data, null, 2) : (e.message || 'Failed'))
    } finally {
      setIntentLoading(false)
    }
  }

  const statusColor = statusData?.status === 'DONE' ? 'var(--green)'
    : statusData?.status === 'FAILED' ? 'var(--red)' : 'var(--orange)'

  return (
    <div>
      <div className="card">
        <div className="card-title">Transfer Status</div>
        <div className="form-row tri">
          <div className="fg">
            <label>TX Hash</label>
            <input value={txHash} onChange={e => setTxHash(e.target.value)} placeholder="0x..." />
          </div>
          <div className="fg">
            <label>From Chain</label>
            <select value={fromChain} onChange={e => setFromChain(+e.target.value)}>
              {chains.map(c => <option key={c.chain_id} value={c.chain_id}>{c.name} ({c.chain_id})</option>)}
            </select>
          </div>
          <div className="fg">
            <label>To Chain</label>
            <select value={toChain} onChange={e => setToChain(+e.target.value)}>
              {chains.map(c => <option key={c.chain_id} value={c.chain_id}>{c.name} ({c.chain_id})</option>)}
            </select>
          </div>
        </div>
        <div className="btn-row">
          <button className="btn btn-primary" onClick={doCheckStatus} disabled={statusLoading || !txHash}>
            {statusLoading ? <><span className="spinner" /> Checking...</> : 'Check Status'}
          </button>
          <button className={`btn ${polling ? 'btn-primary' : 'btn-outline'}`} onClick={togglePoll}>
            {polling ? 'Stop Polling' : 'Auto-poll (10s)'}
          </button>
        </div>

        {statusError && (
          <div className="alert alert-err mt">
            <pre style={{ fontFamily:'var(--mono)', fontSize:12, whiteSpace:'pre-wrap' }}>{statusError}</pre>
          </div>
        )}

        {statusData && (
          <div className="mt">
            <div className="card" style={{ margin:0 }}>
              <div style={{ textAlign:'center', marginBottom:16 }}>
                <div style={{ fontSize:28, fontWeight:800, color: statusColor }}>{statusData.status}</div>
                {statusData.substatus && <div style={{ color:'var(--dim)', fontSize:13 }}>{statusData.substatus}</div>}
              </div>
              <div className="tx-detail">
                {statusData.sending?.tx_hash && (
                  <>
                    <span className="lbl">Sending TX</span>
                    <span className="val">
                      {statusData.sending.tx_hash}
                      {statusData.sending.tx_link && (
                        <> <a href={statusData.sending.tx_link} target="_blank" rel="noreferrer" className="link">explorer</a></>
                      )}
                    </span>
                  </>
                )}
                {statusData.receiving?.tx_hash && (
                  <>
                    <span className="lbl">Receiving TX</span>
                    <span className="val">
                      {statusData.receiving.tx_hash}
                      {statusData.receiving.tx_link && (
                        <> <a href={statusData.receiving.tx_link} target="_blank" rel="noreferrer" className="link">explorer</a></>
                      )}
                    </span>
                  </>
                )}
                {statusData.bridge && (
                  <><span className="lbl">Bridge</span><span className="val">{statusData.bridge}</span></>
                )}
                {statusData.lifi_explorer && (
                  <><span className="lbl">LiFi Explorer</span><span className="val"><a href={statusData.lifi_explorer} target="_blank" rel="noreferrer" className="link">{statusData.lifi_explorer}</a></span></>
                )}
              </div>
            </div>
            <JsonViewer data={statusData} label="Status Response" />
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title">Intent Status (on-chain)</div>
        <div className="form-row">
          <div className="fg">
            <label>Intent Hash (bytes32)</label>
            <input value={intentHash} onChange={e => setIntentHash(e.target.value)} placeholder="0x..." />
          </div>
          <div className="fg">
            <label>Chain ID</label>
            <select value={intentChain} onChange={e => setIntentChain(+e.target.value)}>
              {chains.filter(c => [1, 8453, 42161].includes(c.chain_id)).map(c => (
                <option key={c.chain_id} value={c.chain_id}>{c.name} ({c.chain_id})</option>
              ))}
            </select>
          </div>
        </div>
        <button className="btn btn-primary" onClick={doCheckIntent} disabled={intentLoading || !intentHash}>
          {intentLoading ? <><span className="spinner" /> Checking...</> : 'Check Intent'}
        </button>

        {intentError && (
          <div className="alert alert-err mt">
            <pre style={{ fontFamily:'var(--mono)', fontSize:12, whiteSpace:'pre-wrap' }}>{intentError}</pre>
          </div>
        )}

        {intentData && (
          <div className="mt">
            <div className="card" style={{ margin:0 }}>
              <div className="tx-detail">
                <span className="lbl">User</span><span className="val">{intentData.user}</span>
                <span className="lbl">Vault</span><span className="val">{intentData.vault}</span>
                <span className="lbl">Asset</span><span className="val">{intentData.asset}</span>
                <span className="lbl">Amount</span><span className="val">{intentData.amount}</span>
                <span className="lbl">Deadline</span><span className="val">{intentData.deadline}</span>
                <span className="lbl">Executed</span>
                <span className="val" style={{ color: intentData.executed ? 'var(--green)' : 'var(--dim)' }}>
                  {String(intentData.executed)}
                </span>
                <span className="lbl">Cancelled</span>
                <span className="val" style={{ color: intentData.cancelled ? 'var(--red)' : 'var(--dim)' }}>
                  {String(intentData.cancelled)}
                </span>
              </div>
            </div>
            <JsonViewer data={intentData} label="Intent Response" />
          </div>
        )}
      </div>
    </div>
  )
}
