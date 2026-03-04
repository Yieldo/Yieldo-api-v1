import { http, createConfig } from 'wagmi'
import { mainnet, base, arbitrum, optimism, avalanche, bsc } from 'wagmi/chains'
import { injected } from 'wagmi/connectors'

export const config = createConfig({
  chains: [mainnet, base, arbitrum, optimism, avalanche, bsc],
  connectors: [injected()],
  transports: {
    [mainnet.id]: http(),
    [base.id]: http(),
    [arbitrum.id]: http(),
    [optimism.id]: http(),
    [avalanche.id]: http(),
    [bsc.id]: http(),
  },
})
