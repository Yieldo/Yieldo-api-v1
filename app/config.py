from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    lifi_api_key: str = ""
    ethereum_rpc_url: str = "https://eth.drpc.org"
    base_rpc_url: str = "https://mainnet.base.org"
    arbitrum_rpc_url: str = "https://arb1.arbitrum.io/rpc"
    optimism_rpc_url: str = "https://mainnet.optimism.io"
    monad_rpc_url: str = "https://rpc.monad.xyz"
    hyperliquid_rpc_url: str = "https://rpc.hyperliquid.xyz/evm"
    katana_rpc_url: str = "https://rpc.katanarpc.com"
    gnosis_rpc_url: str = "https://rpc.gnosischain.com"
    mongodb_url: str = ""
    # The indexer (indexer-v1) writes to a different Mongo cluster — score
    # endpoints read from that cluster. If not set, falls back to mongodb_url.
    indexer_mongodb_url: str = ""
    intent_deadline_seconds: int = 3600
    signer_private_key: str = ""
    zerion_api_key: str = ""
    # Admin key for /v1/applications admin endpoints (list/approve/reject).
    # Set via .env on the VPS — never commit. Empty value disables admin endpoints.
    yieldo_admin_key: str = ""

    # /v1/admin (vault toggle dashboard) password. Required alongside a SIWE
    # signature from one of the wallets in `yieldo_admin_wallets`. Both checks
    # must pass — password proves "you have the shared secret", signature
    # proves "you control the wallet". Empty = admin disabled.
    yieldo_admin_password: str = ""
    # Comma-separated list of admin wallet addresses (lowercase, 0x...).
    # Add more by appending in the .env file — no code change needed.
    yieldo_admin_wallets: str = "0x7e14104e2433fde49c98008911298f069c9de41a"

    class Config:
        env_file = ".env"
        extra = "ignore"  # tolerate other unknown env vars (e.g. ops/secret rotation)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
