from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    lifi_api_key: str = ""
    ethereum_rpc_url: str = "https://eth.drpc.org"
    base_rpc_url: str = "https://mainnet.base.org"
    arbitrum_rpc_url: str = "https://arb1.arbitrum.io/rpc"
    optimism_rpc_url: str = "https://mainnet.optimism.io"
    mongodb_url: str = ""
    intent_deadline_seconds: int = 3600
    signer_private_key: str = ""

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
