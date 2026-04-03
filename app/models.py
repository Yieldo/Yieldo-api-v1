from pydantic import BaseModel, Field
from typing import Optional


class ChainInfo(BaseModel):
    chain_id: int
    name: str
    key: str
    explorer: str


class AssetInfo(BaseModel):
    address: str
    symbol: str
    decimals: int


class VaultResponse(BaseModel):
    vault_id: str
    name: str
    address: str
    chain_id: int
    chain_name: str
    asset: AssetInfo
    deposit_router: str
    type: str = "morpho"


class VaultDetailResponse(VaultResponse):
    total_assets: Optional[str] = None
    total_supply: Optional[str] = None
    share_price: Optional[str] = None


class QuoteRequest(BaseModel):
    from_chain_id: int
    from_token: str
    from_amount: str
    vault_id: str
    user_address: str
    slippage: float = 0.03
    referrer: str = "0x0000000000000000000000000000000000000000"


class IntentData(BaseModel):
    user: str
    vault: str
    asset: str
    amount: str
    nonce: str
    deadline: str
    fee_bps: str = "10"


class EIP712Domain(BaseModel):
    name: str
    version: str
    chainId: int
    verifyingContract: str


class EIP712Data(BaseModel):
    domain: EIP712Domain
    types: dict
    primaryType: str = "DepositIntent"
    message: IntentData


class StepDetail(BaseModel):
    type: str
    tool: str
    from_token: Optional[str] = None
    to_token: Optional[str] = None
    from_amount: Optional[str] = None
    to_amount: Optional[str] = None
    estimated_time: Optional[int] = None


class QuoteEstimate(BaseModel):
    from_amount: str
    from_amount_usd: Optional[str] = None
    to_amount: str
    to_amount_min: str
    deposit_amount: str
    fee_amount: str
    fee_bps: int = 10
    estimated_shares: Optional[str] = None
    price_impact: Optional[float] = None
    estimated_time: Optional[int] = None
    gas_cost_usd: Optional[str] = None
    steps: Optional[list[StepDetail]] = None


class ApprovalData(BaseModel):
    token_address: str
    spender_address: str
    amount: str


class QuoteResponse(BaseModel):
    quote_type: str
    vault: VaultResponse
    estimate: QuoteEstimate
    intent: IntentData
    eip712: EIP712Data
    signature: str
    approval: Optional[ApprovalData] = None


class BuildRequest(BaseModel):
    from_chain_id: int
    from_token: str
    from_amount: str
    vault_id: str
    user_address: str
    signature: str
    intent_amount: str
    nonce: str
    deadline: str
    fee_bps: str = "10"
    slippage: float = 0.03
    referrer: str = "0x0000000000000000000000000000000000000000"


class TransactionRequest(BaseModel):
    to: str
    data: str
    value: str
    chain_id: int
    gas_limit: Optional[str] = None


class TrackingInfo(BaseModel):
    from_chain_id: int
    to_chain_id: int
    bridge: Optional[str] = None
    lifi_explorer: Optional[str] = None


class BuildResponse(BaseModel):
    transaction_request: TransactionRequest
    approval: Optional[ApprovalData] = None
    intent: IntentData
    tracking: TrackingInfo
    tracking_id: Optional[str] = None


class SendingInfo(BaseModel):
    tx_hash: Optional[str] = None
    tx_link: Optional[str] = None
    amount: Optional[str] = None
    chain_id: Optional[int] = None


class ReceivingInfo(BaseModel):
    tx_hash: Optional[str] = None
    tx_link: Optional[str] = None
    amount: Optional[str] = None
    chain_id: Optional[int] = None


class StatusResponse(BaseModel):
    status: str
    substatus: Optional[str] = None
    sending: Optional[SendingInfo] = None
    receiving: Optional[ReceivingInfo] = None
    bridge: Optional[str] = None
    lifi_explorer: Optional[str] = None


class TokenInfo(BaseModel):
    address: str
    symbol: str
    decimals: int
    chain_id: int
    name: Optional[str] = None
    logo_uri: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ========== Partner / Wallet Provider Models ==========

class PartnerNonceRequest(BaseModel):
    address: str


class PartnerNonceResponse(BaseModel):
    nonce: str
    message: str


class PartnerRegisterRequest(BaseModel):
    address: str
    signature: str
    name: str
    website: str = ""
    contact_email: str = ""
    description: str = ""


class PartnerRegisterResponse(BaseModel):
    address: str
    name: str
    api_key: str
    api_secret: str
    api_key_prefix: str
    created_at: str


class PartnerLoginRequest(BaseModel):
    address: str
    signature: str


class PartnerLoginResponse(BaseModel):
    session_token: str
    expires_at: str
    partner: dict


class PartnerProfile(BaseModel):
    address: str
    name: str
    website: str = ""
    contact_email: str = ""
    description: str = ""
    fee_enabled: bool = True
    fee_collector_address: str = ""
    webhook_url: str = ""
    enrolled_vaults: list[str] = []
    api_key_prefix: str = ""
    created_at: str = ""
    status: str = "active"


class PartnerSettingsUpdate(BaseModel):
    fee_enabled: Optional[bool] = None
    fee_collector_address: Optional[str] = None
    webhook_url: Optional[str] = None
    name: Optional[str] = None
    website: Optional[str] = None
    contact_email: Optional[str] = None


class PartnerVaultsUpdate(BaseModel):
    enrolled_vaults: list[str]


class PartnerDashboardResponse(BaseModel):
    total_transactions: int = 0
    successful_transactions: int = 0
    failed_transactions: int = 0
    total_volume: str = "0"
    total_users: int = 0
    total_fee_earned: str = "0"
    transactions_7d: int = 0
    users_7d: int = 0


class PartnerTransactionEntry(BaseModel):
    user_address: str
    vault_id: str
    from_chain_id: int
    from_amount: str
    quote_type: str
    status: str
    fee_amount: str = "0"
    created_at: str


class PartnerAPIKeyRotateResponse(BaseModel):
    api_key: str
    api_secret: str
    api_key_prefix: str
