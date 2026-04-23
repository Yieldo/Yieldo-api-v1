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
    min_deposit: Optional[str] = None
    # True iff we have evidence (vault type + on-chain probe) that there is no
    # enforced minimum. Distinct from `min_deposit == None` which means "unknown".
    no_minimum: bool = False


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


class StepDetail(BaseModel):
    type: str
    tool: str
    from_token: Optional[str] = None
    to_token: Optional[str] = None
    from_amount: Optional[str] = None
    to_amount: Optional[str] = None
    estimated_time: Optional[int] = None


class RouteOption(BaseModel):
    bridge: str
    bridge_name: str
    bridge_logo: Optional[str] = None
    to_amount: str
    to_amount_min: str
    deposit_amount: str
    estimated_time: Optional[int] = None
    gas_cost_usd: Optional[str] = None
    tags: list[str] = []


class QuoteEstimate(BaseModel):
    from_amount: str
    from_amount_usd: Optional[str] = None
    to_amount: str
    to_amount_min: str
    deposit_amount: str
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
    approval: Optional[ApprovalData] = None
    route_options: Optional[list[RouteOption]] = None


class BuildRequest(BaseModel):
    from_chain_id: int
    from_token: str
    from_amount: str
    vault_id: str
    user_address: str
    slippage: float = 0.03
    referrer: str = "0x0000000000000000000000000000000000000000"
    referrer_handle: str = ""
    preferred_bridge: Optional[str] = None
    partner_id: str = ""
    partner_type: int = 0


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


class DepositStep(BaseModel):
    transaction_request: TransactionRequest
    approval: Optional[ApprovalData] = None

class BuildResponse(BaseModel):
    transaction_request: TransactionRequest
    approval: Optional[ApprovalData] = None
    tracking: TrackingInfo
    tracking_id: Optional[str] = None
    two_step: bool = False
    deposit_tx: Optional[DepositStep] = None


class WithdrawIntentData(BaseModel):
    user: str
    vault: str
    asset: str
    shares: str
    min_amount_out: str
    nonce: str
    deadline: str


class WithdrawQuoteRequest(BaseModel):
    vault_id: str
    shares: str
    user_address: str
    slippage: float = 0.01


class WithdrawQuoteResponse(BaseModel):
    vault: VaultResponse
    mode: str  # "sync" | "async"
    shares: str
    estimated_assets: Optional[str] = None
    min_amount_out: str
    intent: WithdrawIntentData
    eip712: Optional[dict] = None  # None on direct-to-protocol path
    signature: str = ""
    approval: ApprovalData


class WithdrawBuildRequest(BaseModel):
    vault_id: str
    shares: str
    min_amount_out: str
    user_address: str
    nonce: str
    deadline: str
    signature: str
    mode: str  # "sync" | "async"


class WithdrawBuildResponse(BaseModel):
    transaction_request: TransactionRequest
    approval: ApprovalData
    mode: str
    tracking_id: Optional[str] = None


class Position(BaseModel):
    vault_id: str
    vault_name: str
    vault_address: str
    chain_id: int
    asset_symbol: str
    asset_address: str
    asset_decimals: int = 18
    share_balance: str
    share_decimals: int
    vault_type: str
    # Yield tracking — all in asset smallest units (wei-equivalent for the asset's decimals)
    current_assets: Optional[str] = None   # share_balance converted to asset via convertToAssets or share_price
    deposited_assets: Optional[str] = None  # sum of historical deposit amounts for this vault
    yield_assets: Optional[str] = None      # current_assets - deposited_assets (may be negative)
    # USD-denominated values (from Zerion when available)
    value_usd: Optional[float] = None       # current position value in USD
    apy: Optional[float] = None             # APY as fraction (0.045 = 4.5%) when reported by Zerion
    source: str = "rpc"                     # "zerion" or "rpc" — for debugging


class PositionsResponse(BaseModel):
    user_address: str
    positions: list[Position]


class WithdrawRequestRecord(BaseModel):
    req_hash: str
    user_address: str
    vault_id: str
    vault_name: str
    shares: str
    asset_address: str
    protocol_request_id: str
    escrow_address: str
    submitted_at: str
    claimed: bool
    tx_hash: str


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


# ========== KOL Models ==========

class KolNonceRequest(BaseModel):
    address: str


class KolNonceResponse(BaseModel):
    nonce: str
    message: str


class KolRegisterRequest(BaseModel):
    address: str
    signature: str
    handle: str
    name: str
    bio: str = ""
    twitter: str = ""
    invite_code: str = ""  # required unless depositing-referrals tier 2 reached


class CreatorInviteVerifyRequest(BaseModel):
    code: str


class CreatorApplicationRequest(BaseModel):
    address: str
    twitter: str
    audience: str = ""
    description: str = ""


class KolRegisterResponse(BaseModel):
    address: str
    handle: str
    name: str
    created_at: str


class KolLoginRequest(BaseModel):
    address: str
    signature: str


class KolLoginResponse(BaseModel):
    session_token: str
    expires_at: str
    kol: dict


class KolProfile(BaseModel):
    address: str
    handle: str
    name: str
    bio: str = ""
    twitter: str = ""
    fee_enabled: bool = True
    fee_collector_address: str = ""
    enrolled_vaults: list[str] = []
    created_at: str = ""
    status: str = "active"


class KolPublicProfile(BaseModel):
    handle: str
    name: str
    bio: str = ""
    twitter: str = ""
    enrolled_vaults: list[str] = []
    created_at: str = ""
    founding_creator: bool = False


class KolSettingsUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    twitter: Optional[str] = None
    fee_enabled: Optional[bool] = None
    fee_collector_address: Optional[str] = None


class KolVaultsUpdate(BaseModel):
    enrolled_vaults: list[str]


class KolDashboardResponse(BaseModel):
    total_referrals: int = 0
    total_volume: str = "0"
    total_earnings: str = "0"
    total_users: int = 0
    referrals_7d: int = 0
    users_7d: int = 0


# ========== User Models ==========

class UserNonceRequest(BaseModel):
    address: str


class UserNonceResponse(BaseModel):
    nonce: str
    message: str


class UserLoginRequest(BaseModel):
    address: str
    signature: str


class UserLoginResponse(BaseModel):
    session_token: str
    expires_at: str
    user: dict


class UserProfile(BaseModel):
    address: str
    created_at: str = ""
    last_login: str = ""
    status: str = "active"
