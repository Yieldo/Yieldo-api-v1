import { useState } from 'react'
import {
  useSendTransaction,
  useWaitForTransactionReceipt,
  useWriteContract,
  useSwitchChain,
  useChainId,
} from 'wagmi'
import { parseAbi } from 'viem'

const erc20Abi = parseAbi(['function approve(address spender, uint256 amount) returns (bool)'])

export default function SendTx({ buildData, sentTxHash, setSentTxHash, onNext, goBack }) {
  const [approvalHash, setApprovalHash] = useState(null)
  const [approvalDone, setApprovalDone] = useState(false)
  const [approvalError, setApprovalError] = useState(null)
  const [sendError, setSendError] = useState(null)

  const chainId = useChainId()
  const { switchChainAsync } = useSwitchChain()

  const { writeContractAsync, isPending: isApproving } = useWriteContract()

  const { sendTransactionAsync, isPending: isSending } = useSendTransaction()

  const { data: approvalReceipt, isLoading: approvalConfirming } = useWaitForTransactionReceipt({
    hash: approvalHash,
    query: { enabled: !!approvalHash },
  })

  const { data: txReceipt, isLoading: txConfirming } = useWaitForTransactionReceipt({
    hash: sentTxHash,
    query: { enabled: !!sentTxHash },
  })

  if (!buildData) return <div className="alert alert-warn">Build a transaction first</div>

  const tx = buildData.transaction_request
  const approval = buildData.approval
  const needsApproval = approval && !approvalDone

  async function ensureChain() {
    if (chainId !== tx.chain_id) {
      await switchChainAsync({ chainId: tx.chain_id })
    }
  }

  async function doApprove() {
    setApprovalError(null)
    try {
      await ensureChain()
      const hash = await writeContractAsync({
        address: approval.token_address,
        abi: erc20Abi,
        functionName: 'approve',
        args: [approval.spender_address, BigInt(approval.amount)],
      })
      setApprovalHash(hash)
      setApprovalDone(true)
    } catch (e) {
      setApprovalError(e.shortMessage || e.message || 'Approval failed')
    }
  }

  async function doSend() {
    setSendError(null)
    try {
      await ensureChain()
      const txReq = {
        to: tx.to,
        data: tx.data,
        value: BigInt(tx.value || '0'),
      }
      if (tx.gas_limit) txReq.gas = BigInt(tx.gas_limit)

      const hash = await sendTransactionAsync(txReq)
      setSentTxHash(hash)
    } catch (e) {
      setSendError(e.shortMessage || e.message || 'Transaction failed')
    }
  }

  return (
    <div>
      <div className="card">
        <div className="card-title">Transaction Summary</div>
        <div className="tx-detail">
          <span className="lbl">To</span><span className="val">{tx.to}</span>
          <span className="lbl">Chain</span><span className="val">{tx.chain_id}</span>
          <span className="lbl">Value</span><span className="val">{tx.value} wei</span>
          <span className="lbl">Data</span><span className="val">{tx.data.slice(0, 66)}...</span>
        </div>
      </div>

      {approval && (
        <div className="card">
          <div className="card-title">Step 1: Token Approval</div>
          <div className="tx-detail">
            <span className="lbl">Token</span><span className="val">{approval.token_address}</span>
            <span className="lbl">Spender</span><span className="val">{approval.spender_address}</span>
            <span className="lbl">Amount</span><span className="val">{approval.amount}</span>
          </div>
          <div className="mt">
            {!approvalDone ? (
              <button className="btn btn-orange" onClick={doApprove} disabled={isApproving}>
                {isApproving ? <><span className="spinner" /> Approving...</> : 'Approve Token'}
              </button>
            ) : approvalHash && approvalConfirming ? (
              <div className="alert alert-info">
                <span className="spinner" /> Approval sent, waiting for confirmation...
                <div className="mono" style={{ fontSize:11, marginTop:4 }}>{approvalHash}</div>
              </div>
            ) : approvalReceipt ? (
              <div className="alert alert-ok">
                Approval confirmed in block {approvalReceipt.blockNumber.toString()}
              </div>
            ) : (
              <div className="alert alert-ok">Approval submitted</div>
            )}
            {approvalError && <div className="alert alert-err mt">{approvalError}</div>}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-title">{approval ? 'Step 2: Send Transaction' : 'Send Transaction'}</div>
        {!sentTxHash ? (
          <>
            {needsApproval && !approvalDone && (
              <div className="alert alert-warn">Complete token approval first</div>
            )}
            <button
              className="btn btn-green"
              onClick={doSend}
              disabled={isSending || (needsApproval && !approvalDone)}
            >
              {isSending ? <><span className="spinner" /> Confirm in wallet...</> : 'Send Transaction'}
            </button>
            {sendError && <div className="alert alert-err mt">{sendError}</div>}
          </>
        ) : txConfirming ? (
          <div className="alert alert-info">
            <span className="spinner" /> Transaction sent, waiting for confirmation...
            <div className="mono" style={{ fontSize:11, marginTop:4, wordBreak:'break-all' }}>{sentTxHash}</div>
          </div>
        ) : txReceipt ? (
          <div>
            <div className={`alert ${txReceipt.status === 'success' ? 'alert-ok' : 'alert-err'}`}>
              {txReceipt.status === 'success' ? 'Transaction confirmed!' : 'Transaction reverted!'}
              <div className="mono" style={{ fontSize:11, marginTop:4 }}>
                Hash: {sentTxHash}<br />
                Block: {txReceipt.blockNumber.toString()} | Gas: {txReceipt.gasUsed.toString()}
              </div>
            </div>
            <button className="btn btn-primary mt" onClick={onNext}>Track Cross-Chain Status</button>
          </div>
        ) : (
          <div className="alert alert-info">
            Transaction submitted
            <div className="mono" style={{ fontSize:11, marginTop:4, wordBreak:'break-all' }}>{sentTxHash}</div>
          </div>
        )}
      </div>

      <div className="btn-row">
        <button className="btn btn-outline" onClick={goBack}>Back</button>
      </div>
    </div>
  )
}
