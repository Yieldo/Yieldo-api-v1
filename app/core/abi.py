DEPOSIT_ROUTER_ABI = [
    # depositFor — 7-arg V3.0 shim
    {
        "inputs": [
            {"internalType": "address", "name": "vault", "type": "address"},
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address", "name": "user", "type": "address"},
            {"internalType": "bytes32", "name": "partnerId", "type": "bytes32"},
            {"internalType": "uint8", "name": "partnerType", "type": "uint8"},
            {"internalType": "bool", "name": "isERC4626", "type": "bool"},
        ],
        "name": "depositFor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # depositFor — 8-arg V3.1 shim (minSharesOut)
    {
        "inputs": [
            {"internalType": "address", "name": "vault", "type": "address"},
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address", "name": "user", "type": "address"},
            {"internalType": "bytes32", "name": "partnerId", "type": "bytes32"},
            {"internalType": "uint8", "name": "partnerType", "type": "uint8"},
            {"internalType": "bool", "name": "isERC4626", "type": "bool"},
            {"internalType": "uint256", "name": "minSharesOut", "type": "uint256"},
        ],
        "name": "depositFor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # depositFor — 9-arg V3.3 primary (adds deadline)
    {
        "inputs": [
            {"internalType": "address", "name": "vault", "type": "address"},
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address", "name": "user", "type": "address"},
            {"internalType": "bytes32", "name": "partnerId", "type": "bytes32"},
            {"internalType": "uint8", "name": "partnerType", "type": "uint8"},
            {"internalType": "bool", "name": "isERC4626", "type": "bool"},
            {"internalType": "uint256", "name": "minSharesOut", "type": "uint256"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "depositFor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # depositRequestFor — 6-arg V3.0 shim
    {
        "inputs": [
            {"internalType": "address", "name": "vault", "type": "address"},
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address", "name": "user", "type": "address"},
            {"internalType": "bytes32", "name": "partnerId", "type": "bytes32"},
            {"internalType": "uint8", "name": "partnerType", "type": "uint8"},
        ],
        "name": "depositRequestFor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # depositRequestFor — 7-arg V3.3 primary (adds deadline)
    {
        "inputs": [
            {"internalType": "address", "name": "vault", "type": "address"},
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "address", "name": "user", "type": "address"},
            {"internalType": "bytes32", "name": "partnerId", "type": "bytes32"},
            {"internalType": "uint8", "name": "partnerType", "type": "uint8"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "depositRequestFor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # depositForAvailable — 8-arg V3.2 shim
    {
        "inputs": [
            {"internalType": "address", "name": "vault", "type": "address"},
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "address", "name": "user", "type": "address"},
            {"internalType": "bytes32", "name": "partnerId", "type": "bytes32"},
            {"internalType": "uint8", "name": "partnerType", "type": "uint8"},
            {"internalType": "bool", "name": "isERC4626", "type": "bool"},
            {"internalType": "uint256", "name": "minAmount", "type": "uint256"},
            {"internalType": "uint256", "name": "minSharesOut", "type": "uint256"},
        ],
        "name": "depositForAvailable",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # depositForAvailable — 9-arg V3.3 primary (adds deadline)
    {
        "inputs": [
            {"internalType": "address", "name": "vault", "type": "address"},
            {"internalType": "address", "name": "asset", "type": "address"},
            {"internalType": "address", "name": "user", "type": "address"},
            {"internalType": "bytes32", "name": "partnerId", "type": "bytes32"},
            {"internalType": "uint8", "name": "partnerType", "type": "uint8"},
            {"internalType": "bool", "name": "isERC4626", "type": "bool"},
            {"internalType": "uint256", "name": "minAmount", "type": "uint256"},
            {"internalType": "uint256", "name": "minSharesOut", "type": "uint256"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "depositForAvailable",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

ERC4626_ABI = [
    {
        "inputs": [],
        "name": "asset",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalAssets",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]

PYTH_ABI = [
    {
        "inputs": [{"internalType": "bytes[]", "name": "updateData", "type": "bytes[]"}],
        "name": "getUpdateFee",
        "outputs": [{"internalType": "uint256", "name": "feeAmount", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

ERC20_ABI = [
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]
