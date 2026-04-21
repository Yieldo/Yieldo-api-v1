DEPOSIT_ROUTER_ABI = [
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

_WITHDRAW_INTENT_COMPONENTS = [
    {"internalType": "address", "name": "user", "type": "address"},
    {"internalType": "address", "name": "vault", "type": "address"},
    {"internalType": "address", "name": "asset", "type": "address"},
    {"internalType": "uint256", "name": "shares", "type": "uint256"},
    {"internalType": "uint256", "name": "minAmountOut", "type": "uint256"},
    {"internalType": "uint256", "name": "nonce", "type": "uint256"},
    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
]

DEPOSIT_ROUTER_ABI.extend([
    {
        "inputs": [
            {"components": _WITHDRAW_INTENT_COMPONENTS, "internalType": "struct DepositRouter.WithdrawIntent", "name": "intent", "type": "tuple"},
            {"internalType": "bytes", "name": "signature", "type": "bytes"},
        ],
        "name": "withdrawWithIntent",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"components": _WITHDRAW_INTENT_COMPONENTS, "internalType": "struct DepositRouter.WithdrawIntent", "name": "intent", "type": "tuple"},
            {"internalType": "bytes", "name": "signature", "type": "bytes"},
        ],
        "name": "withdrawRequestWithIntent",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "reqHash", "type": "bytes32"}],
        "name": "claimWithdrawRequest",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
])

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
