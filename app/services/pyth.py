import logging
import httpx
from web3 import Web3
from app.core.constants import PYTH_CONTRACT_ADDRESSES
from app.core.abi import PYTH_ABI
from app.services.rpc import get_w3

logger = logging.getLogger(__name__)

HERMES_URL = "https://hermes.pyth.network/v2/updates/price/latest"

PYTH_FEED_IDS: dict[str, str] = {
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913": "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
    "0x4200000000000000000000000000000000000006": "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48": "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2": "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599": "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "0xdAC17F958D2ee523a2206206994597C13D831ec7": "0x2b89b9dc8fdf9f34592c9b02cfa78aab1be94e6f05fa0d46c67e6e9e30e34070",
    "0xaf88d065e77c8cC2239327C5EDb3A432268e5831": "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
    "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9": "0x2b89b9dc8fdf9f34592c9b02cfa78aab1be94e6f05fa0d46c67e6e9e30e34070",
}


def get_price_update(asset_address: str) -> list[bytes]:
    feed_id = PYTH_FEED_IDS.get(asset_address)
    if not feed_id:
        return []
    try:
        resp = httpx.get(HERMES_URL, params={"ids[]": feed_id, "encoding": "hex"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return [bytes.fromhex(item) for item in data["binary"]["data"]]
    except Exception as e:
        logger.error(f"Failed to fetch Pyth price update: {e}")
        return []


def get_pyth_update_fee(chain_id: int, price_update: list[bytes]) -> int:
    if not price_update:
        return 0
    pyth_addr = PYTH_CONTRACT_ADDRESSES.get(chain_id)
    if not pyth_addr:
        return 0
    try:
        w3 = get_w3(chain_id)
        pyth = w3.eth.contract(address=Web3.to_checksum_address(pyth_addr), abi=PYTH_ABI)
        return pyth.functions.getUpdateFee(price_update).call()
    except Exception as e:
        logger.error(f"Failed to get Pyth update fee: {e}")
        return 0
