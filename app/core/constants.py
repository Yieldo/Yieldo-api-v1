LIFI_BASE_URL = "https://li.quest/v1"
LIFI_INTEGRATOR = "Yieldo"
FEE_BPS = 10
CROSS_CHAIN_SLIPPAGE_BUFFER = 0.95

DEPOSIT_ROUTER_ADDRESSES: dict[int, str] = {
    1: "0xc4418Da01AD12130273d72aC7BC77aaEcf2Cc6C0",
    8453: "0xdE064d1D41e4d30B913b27f147E228fEe8fd31dc",
    42161: "0xC75e95201bC574299a3C849181469B5B3B20cc97",
}

CHAIN_CONFIG: dict[int, dict] = {
    1: {
        "name": "Ethereum",
        "key": "eth",
        "explorer": "https://etherscan.io",
    },
    8453: {
        "name": "Base",
        "key": "base",
        "explorer": "https://basescan.org",
    },
    42161: {
        "name": "Arbitrum",
        "key": "arb",
        "explorer": "https://arbiscan.io",
    },
    10: {
        "name": "Optimism",
        "key": "op",
        "explorer": "https://optimistic.etherscan.io",
    },
    43114: {
        "name": "Avalanche",
        "key": "avax",
        "explorer": "https://snowscan.xyz",
    },
    56: {
        "name": "BSC",
        "key": "bsc",
        "explorer": "https://bscscan.com",
    },
}

SOURCE_CHAINS = [1, 8453, 42161, 10, 43114, 56]

ASSET_TOKEN_CONFIG: dict[int, dict[str, tuple[str, int]]] = {
    1: {
        "usdc": ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),
        "usdt": ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
        "weth": ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18),
        "wbtc": ("0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8),
        "pyusd": ("0x6c3ea9036406852006290770BEdFcAbA0e23A0e8", 6),
        "usdtb": ("0xC139190F447e929f090edF9bB84c22a9D232dDA2", 18),
        "ausd": ("0x00000000eFE302BEAA2b3e6e1b18d08D69a9012a", 6),
    },
    8453: {
        "usdc": ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6),
        "weth": ("0x4200000000000000000000000000000000000006", 18),
    },
    42161: {
        "usdc": ("0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6),
        "usdt": ("0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6),
    },
    10: {
        "usdc": ("0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85", 6),
    },
}

UNSUPPORTED_BRIDGES = ["near", "maya", "meson", "socket"]

EIP712_DOMAIN_NAME = "DepositRouter"
EIP712_DOMAIN_VERSION = "1"
EIP712_TYPES = {
    "DepositIntent": [
        {"name": "user", "type": "address"},
        {"name": "vault", "type": "address"},
        {"name": "asset", "type": "address"},
        {"name": "amount", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
        {"name": "deadline", "type": "uint256"},
    ]
}
