import { useState } from 'react'
import { fetchBuild } from '../api'
import JsonViewer from './JsonViewer'

export default function SignBuild({
  vault, srcChain, srcToken, amount, slippage, address,
  quoteData, signature, setSignature, buildData, setBuildData,
  onNext, goBack
}) {
  const [buildLoading, setBuildLoading] = useState(false)
  const [buildError, setBuildError] = useState(null)

  if (!quoteData) return <div className="alert alert-warn">Get a quote first</div>

  const intent = quoteData.intent
  const backendSig = quoteData.signature

  async function doBuild() {
    setBuildLoading(true)
    setBuildError(null)
    try {
      setSignature(backendSig)
      const data = await fetchBuild({
        from_chain_id: srcChain,
        from_token: srcToken,
        from_amount: amount,
        vault_id: vault.vault_id,
        user_address: address,
        signature: backendSig,
        intent_amount: intent.amount,
        nonce: intent.nonce,
        deadline: intent.deadline,
        fee_bps: intent.fee_bps,
        slippage,
      })
      setBuildData(data)
    } catch (e) {
      setBuildError(e.data ? JSON.stringify(e.data, null, 2) : (e.message || 'Build failed'))
    } finally {
      setBuildLoading(false)
    }
  }

  return (
    <div>
      <div className="card">
        <div className="card-title">Deposit Intent (Backend-Signed)</div>
        <div className="tx-detail">
          <span className="lbl">User</span><span className="val">{intent.user}</span>
          <span className="lbl">Vault</span><span className="val">{intent.vault}</span>
          <span className="lbl">Asset</span><span className="val">{intent.asset}</span>
          <span className="lbl">Amount</span><span className="val">{intent.amount}</span>
          <span className="lbl">Nonce</span><span className="val">{intent.nonce}</span>
          <span className="lbl">Deadline</span><span className="val">{intent.deadline}</span>
          <span className="lbl">Fee BPS</span><span className="val">{intent.fee_bps}</span>
        </div>
        <div className="mt">
          <div className="alert alert-ok">
            Signature provided by backend
            <div className="mono" style={{ fontSize:11, marginTop:4, wordBreak:'break-all', color:'var(--dim)' }}>
              {backendSig}
            </div>
          </div>
        </div>
        <div className="mt">
          {!buildData && (
            <button className="btn btn-green" onClick={doBuild} disabled={buildLoading}>
              {buildLoading ? <><span className="spinner" /> Building...</> : 'Build Transaction'}
            </button>
          )}
        </div>
      </div>

      {buildLoading && (
        <div className="card" style={{ textAlign:'center', padding:30 }}>
          <span className="spinner" /> Building transaction...
        </div>
      )}

      {buildError && (
        <div className="alert alert-err">
          Build failed
          <pre style={{ marginTop:6, fontFamily:'var(--mono)', fontSize:12, whiteSpace:'pre-wrap' }}>{buildError}</pre>
        </div>
      )}

      {buildData && (
        <>
          <div className="card">
            <div className="card-title">Built Transaction</div>
            <div className="tx-detail">
              <span className="lbl">To</span><span className="val">{buildData.transaction_request.to}</span>
              <span className="lbl">Chain</span><span className="val">{buildData.transaction_request.chain_id}</span>
              <span className="lbl">Value</span><span className="val">{buildData.transaction_request.value} wei</span>
              <span className="lbl">Gas Limit</span><span className="val">{buildData.transaction_request.gas_limit || 'auto'}</span>
              {buildData.tracking_id && (
                <><span className="lbl">Tracking ID</span><span className="val">{buildData.tracking_id}</span></>
              )}
              {buildData.tracking?.bridge && (
                <><span className="lbl">Bridge</span><span className="val">{buildData.tracking.bridge}</span></>
              )}
            </div>
          </div>

          {buildData.approval && (
            <div className="card">
              <div className="card-title">Token Approval Needed</div>
              <div className="tx-detail">
                <span className="lbl">Token</span><span className="val">{buildData.approval.token_address}</span>
                <span className="lbl">Spender</span><span className="val">{buildData.approval.spender_address}</span>
                <span className="lbl">Amount</span><span className="val">{buildData.approval.amount}</span>
              </div>
              <div className="hint mt">You'll approve in the next step before sending.</div>
            </div>
          )}

          <JsonViewer data={buildData} label="Build Response" />

          <div className="btn-row mt">
            <button className="btn btn-outline" onClick={goBack}>Back</button>
            <button className="btn btn-primary" onClick={onNext}>Continue to Send</button>
          </div>
        </>
      )}

      {!buildData && (
        <div className="btn-row">
          <button className="btn btn-outline" onClick={goBack}>Back</button>
        </div>
      )}
    </div>
  )
}
