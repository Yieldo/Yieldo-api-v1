from fastapi import APIRouter, Query
from app.core.constants import CHAIN_CONFIG, SOURCE_CHAINS, DEPOSIT_ROUTER_ADDRESSES
from app.models import ChainInfo, TokenInfo
from app.services import lifi

router = APIRouter(prefix="/v1", tags=["info"])

MAJOR_SYMBOLS = {
    "USDC", "USDT", "DAI", "WETH", "ETH", "WBTC", "BTC",
    "AVAX", "WAVAX", "BNB", "WBNB",
    "OP", "ARB", "LINK", "UNI", "AAVE",
    "stETH", "wstETH", "rETH", "cbETH",
}


@router.get("/chains", response_model=list[ChainInfo])
async def list_chains(source: bool = Query(False, description="If true, return all source chains. If false, return vault chains only.")):
    chain_ids = SOURCE_CHAINS if source else list(DEPOSIT_ROUTER_ADDRESSES.keys())
    result = []
    for cid in chain_ids:
        cfg = CHAIN_CONFIG.get(cid)
        if cfg:
            result.append(ChainInfo(chain_id=cid, name=cfg["name"], key=cfg["key"], explorer=cfg["explorer"]))
    return result


@router.get("/tokens", response_model=list[TokenInfo])
async def list_tokens(chain_id: int = Query(..., description="Chain ID to get tokens for")):
    raw_tokens = await lifi.get_tokens(chain_id)
    seen = set()
    result = []
    for t in raw_tokens:
        sym = t.get("symbol", "")
        if sym not in MAJOR_SYMBOLS:
            continue
        if sym in seen:
            continue
        seen.add(sym)
        result.append(TokenInfo(
            address=t["address"],
            symbol=sym,
            decimals=t["decimals"],
            chain_id=t["chainId"],
            name=t.get("name"),
            logo_uri=t.get("logoURI"),
        ))
    return result
