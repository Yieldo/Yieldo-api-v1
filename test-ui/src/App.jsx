import { useState, useEffect, useCallback } from 'react'
import { useAccount, useConnect, useDisconnect, useChainId } from 'wagmi'
import { injected } from 'wagmi/connectors'
import { checkHealth } from './api'
import VaultSelect from './components/VaultSelect'
import Configure from './components/Configure'
import QuoteView from './components/QuoteView'
import SignBuild from './components/SignBuild'
import SendTx from './components/SendTx'
import Track from './components/Track'

const CHAIN_NAMES = { 1:'ETH', 8453:'Base', 42161:'Arb', 10:'OP', 43114:'AVAX', 56:'BSC' }

const STEPS = [
  { n:1, label:'Select Vault' },
  { n:2, label:'Configure' },
  { n:3, label:'Quote' },
  { n:4, label:'Sign & Build' },
  { n:5, label:'Send TX' },
  { n:6, label:'Track' },
]

export default function App() {
  const [step, setStep] = useState(1)
  const [apiOk, setApiOk] = useState(null)
  const [vault, setVault] = useState(null)
  const [srcChain, setSrcChain] = useState(1)
  const [srcToken, setSrcToken] = useState(null)
  const [tokenDecimals, setTokenDecimals] = useState(6)
  const [amount, setAmount] = useState('')
  const [slippage, setSlippage] = useState(0.03)
  const [quoteData, setQuoteData] = useState(null)
  const [signature, setSignature] = useState(null)
  const [buildData, setBuildData] = useState(null)
  const [sentTxHash, setSentTxHash] = useState(null)
  const [flowKey, setFlowKey] = useState(0)

  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const { connect, isPending: isConnecting } = useConnect()
  const { disconnect } = useDisconnect()

  useEffect(() => {
    checkHealth().then(setApiOk)
    const t = setInterval(() => checkHealth().then(setApiOk), 15000)
    return () => clearInterval(t)
  }, [])

  const clearFrom = useCallback((fromStep) => {
    if (fromStep <= 3) { setQuoteData(null) }
    if (fromStep <= 4) { setSignature(null); setBuildData(null) }
    if (fromStep <= 5) { setSentTxHash(null) }
    setFlowKey(k => k + 1)
  }, [])

  function goStep(n) {
    if (n < step) clearFrom(n + 1)
    setStep(n)
  }

  function onVaultPick(v) {
    const changed = !vault || vault.vault_id !== v.vault_id
    setVault(v)
    if (changed) {
      clearFrom(3)
    }
    setStep(2)
  }

  function startNewTx() {
    setQuoteData(null)
    setSignature(null)
    setBuildData(null)
    setSentTxHash(null)
    setFlowKey(k => k + 1)
    setStep(1)
  }

  function stepStatus(n) {
    if (n === step) return 'active'
    if (n > step) return ''
    switch (n) {
      case 1: return vault ? 'done' : ''
      case 2: return (amount && srcToken) ? 'done' : ''
      case 3: return quoteData ? 'done' : ''
      case 4: return (signature && buildData) ? 'done' : ''
      case 5: return sentTxHash ? 'done' : ''
      default: return ''
    }
  }

  return (
    <>
      <div className="header">
        <h1><b>Yieldo</b> Test UI</h1>
        <div className="header-right">
          <div className="api-status">
            <span className={`dot ${apiOk === true ? 'dot-ok' : apiOk === false ? 'dot-err' : 'dot-wait'}`} />
            {apiOk === true ? 'API Online' : apiOk === false ? 'API Offline' : 'Checking...'}
          </div>
          {(quoteData || signature || buildData || sentTxHash) && (
            <button className="btn btn-outline" style={{ fontSize: 12, padding: '6px 12px' }} onClick={startNewTx}>
              New TX
            </button>
          )}
          {isConnected ? (
            <button className="wallet-btn connected" onClick={() => disconnect()}>
              <span className="chain-tag">{CHAIN_NAMES[chainId] || `Chain ${chainId}`}</span>
              <span className="wallet-addr">{address.slice(0,6)}...{address.slice(-4)}</span>
            </button>
          ) : (
            <button className="wallet-btn" onClick={() => connect({ connector: injected() })} disabled={isConnecting}>
              {isConnecting ? <><span className="spinner" /> Connecting...</> : 'Connect Wallet'}
            </button>
          )}
        </div>
      </div>

      <div className="container">
        <div className="steps">
          {STEPS.map(s => (
            <div
              key={s.n}
              className={`step-pill ${stepStatus(s.n)}`}
              onClick={() => goStep(s.n)}
            >
              <span className="step-num">{s.n}</span>
              {s.label}
            </div>
          ))}
        </div>

        {!isConnected && (
          <div className="alert alert-warn">
            Connect your wallet (MetaMask) to begin. The wallet button is in the top right.
          </div>
        )}

        {step === 1 && <VaultSelect selected={vault} onPick={onVaultPick} />}
        {step === 2 && (
          <Configure
            vault={vault}
            srcChain={srcChain} setSrcChain={setSrcChain}
            srcToken={srcToken} setSrcToken={setSrcToken}
            tokenDecimals={tokenDecimals} setTokenDecimals={setTokenDecimals}
            amount={amount} setAmount={setAmount}
            slippage={slippage} setSlippage={setSlippage}
            onNext={() => { clearFrom(3); setStep(3) }}
            goBack={() => goStep(1)}
          />
        )}
        {step === 3 && (
          <QuoteView
            key={flowKey}
            vault={vault} srcChain={srcChain} srcToken={srcToken}
            amount={amount} slippage={slippage} address={address}
            tokenDecimals={tokenDecimals}
            quoteData={quoteData} setQuoteData={setQuoteData}
            onNext={() => setStep(4)} goBack={() => goStep(2)}
          />
        )}
        {step === 4 && (
          <SignBuild
            key={flowKey}
            vault={vault} srcChain={srcChain} srcToken={srcToken}
            amount={amount} slippage={slippage} address={address}
            quoteData={quoteData}
            signature={signature} setSignature={setSignature}
            buildData={buildData} setBuildData={setBuildData}
            onNext={() => setStep(5)} goBack={() => goStep(3)}
          />
        )}
        {step === 5 && (
          <SendTx
            key={flowKey}
            buildData={buildData}
            sentTxHash={sentTxHash} setSentTxHash={setSentTxHash}
            onNext={() => setStep(6)} goBack={() => goStep(4)}
          />
        )}
        {step === 6 && (
          <Track
            key={flowKey}
            buildData={buildData} sentTxHash={sentTxHash}
            srcChain={srcChain}
          />
        )}
      </div>
    </>
  )
}
