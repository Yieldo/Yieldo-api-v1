import { useState, useEffect } from 'react'
import { useSignTypedData, useSwitchChain, useChainId } from 'wagmi'
import { fetchBuild } from '../api'
import JsonViewer from './JsonViewer'

export default function SignBuild({
  vault, srcChain, srcToken, amount, slippage, address,
  quoteData, signature, setSignature, buildData, setBuildData,
  onNext, goBack
}) {
  const [signError, setSignError] = useState(null)
  const [buildLoading, setBuildLoading] = useState(false)
  const [buildError, setBuildError] = useState(null)

  const chainId = useChainId()
  const { switchChainAsync } = useSwitchChain()
  const { signTypedDataAsync, isPending: isSigning } = useSignTypedData()

  if (!quoteData) return <div className="alert alert-warn">Get a quote first</div>

  const eip712 = quoteData.eip712
  const intent = quoteData.intent
  const needChain = eip712.domain.chainId

  async function doSign() {
    setSignError(null)
    try {
      if (chainId !== needChain) {
        await switchChainAsync({ chainId: needChain })
      }

      const sig = await signTypedDataAsync({
        domain: {
          name: eip712.domain.name,
          version: eip712.domain.version,
          chainId: eip712.domain.chainId,
          verifyingContract: eip712.domain.verifyingContract,
        },
        types: {
          DepositIntent: eip712.types.DepositIntent.map(f => ({
            name: f.name,
            type: f.type,
          })),
        },
        primaryType: 'DepositIntent',
        message: {
          user: intent.user,
          vault: intent.vault,
          asset: intent.asset,
          amount: BigInt(intent.amount),
          nonce: BigInt(intent.nonce),
          deadline: BigInt(intent.deadline),
        },
      })

      setSignature(sig)
      doBuild(sig)
    } catch (e) {
      setSignError(e.shortMessage || e.message || 'Signing failed')
    }
  }

  async function doBuild(sig) {
    setBuildLoading(true)
    setBuildError(null)
    try {
      const data = await fetchBuild({
        from_chain_id: srcChain,
        from_token: srcToken,
        from_amount: amount,
        vault_id: vault.vault_id,
        user_address: address,
        signature: sig || signature,
        intent_amount: intent.amount,
        nonce: intent.nonce,
        deadline: intent.deadline,
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
        <div className="card-title">EIP-712 Intent Signature</div>
        {chainId !== needChain && (
          <div className="alert alert-warn" style={{ marginBottom: 12 }}>
            You need to switch to chain {needChain} to sign. This will happen automatically.
          </div>
        )}
        <div className="tx-detail">
          <span className="lbl">User</span><span className="val">{intent.user}</span>
          <span className="lbl">Vault</span><span className="val">{intent.vault}</span>
          <span className="lbl">Asset</span><span className="val">{intent.asset}</span>
          <span className="lbl">Amount</span><span className="val">{intent.amount}</span>
          <span className="lbl">Nonce</span><span className="val">{intent.nonce}</span>
          <span className="lbl">Deadline</span><span className="val">{intent.deadline}</span>
        </div>
        <div className="mt">
          {!signature ? (
            <button className="btn btn-green" onClick={doSign} disabled={isSigning}>
              {isSigning ? <><span className="spinner" /> Signing...</> : 'Sign with Wallet'}
            </button>
          ) : (
            <div className="alert alert-ok">
              Signature obtained
              <div className="mono" style={{ fontSize:11, marginTop:4, wordBreak:'break-all', color:'var(--dim)' }}>
                {signature}
              </div>
            </div>
          )}
          {signError && <div className="alert alert-err mt">{signError}</div>}
        </div>
      </div>

      {signature && (
        <>
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
        </>
      )}

      {!signature && (
        <div className="btn-row">
          <button className="btn btn-outline" onClick={goBack}>Back</button>
        </div>
      )}
    </div>
  )
}
