"""Back-fill missing tx_hash on historical pending/abandoned records by walking
the user's on-chain history (via Etherscan V2 multi-chain API) and matching:

  - `to` ∈ {LiFi Diamond, LiFi Executor, our DepositRouter}
  - timestamp within +/- 30 min of `created_at`
  - matching `from_amount` heuristic (just timestamp + to-address is usually enough)

Once a record has its tx_hash, we hit our own /v1/status endpoint which calls
LiFi (cross-chain) or the RPC (same-chain) and writes the final status. This
turns "abandoned" records that ACTUALLY broadcast back into completed/failed/partial.

  ETHERSCAN_API_KEY=...  (read from .env or environment)
  DRY=1 python scripts/backfill_tx_hashes.py
  python scripts/backfill_tx_hashes.py
"""
import asyncio, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
# Free Blockscout endpoints used as fallback when Etherscan v2 doesn't cover a chain
BLOCKSCOUT_HOSTS = {
    1:     "eth.blockscout.com",
    8453:  "base.blockscout.com",
    42161: "arbitrum.blockscout.com",
    10:    "optimism.blockscout.com",
}
# Direct Etherscan-style endpoints (used when Etherscan v2 doesn't cover the chain
# AND Blockscout isn't ideal). Snowtrace has a working free API for Avalanche.
ETHERSCAN_LIKE = {
    43114: "https://api.snowtrace.io/api",
}

# Targets per chain. Anything `to` one of these is a Yieldo-related deposit tx.
LIFI_DIAMOND = "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE"
LIFI_EXECUTORS = {1, 8453, 42161, 10, 43114}  # we'll just check both common executor addrs
LIFI_EXEC_ADDRS = {
    "0x4DaC9d1769b9b304cb04741DCDEb2FC14aBdF110".lower(),
    "0x2dfaDAB8266483beD9Fd9A292Ce56596a2D1378D".lower(),
}
ROUTERS = {
    1:    "0x85f76c1685046Ea226E1148EE1ab81a8a15C385d",
    8453: "0xF6B7723661d52E8533c77479d3cad534B4D147Aa",
    42161:"0xC5700f4D8054BA982C39838D7C33442f54688bd2",
    10:   "0x7554937Aa95195D744A6c45E0fd7D4F95A2F8F72",
    143:  "0xCD8dfD627A3712C9a2B079398e0d524970D5E73F",
    747474:"0xa682CD1c2Fd7c8545b401824096A600C2bD98F69",
    999:  "0xa682CD1c2Fd7c8545b401824096A600C2bD98F69",
    43114: None,  # Avalanche has no router yet — txs on AVAX are LiFi-only
}

API = os.environ.get("YIELDO_API", "https://api.yieldo.xyz")
TIME_WINDOW_SEC = 30 * 60  # +/- 30 min match window


def _load_env():
    for src in (Path(__file__).resolve().parent.parent / ".env",
                Path("E:/yieldo-contracts/.env")):
        if not src.exists(): continue
        for line in src.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k,_,v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


async def fetch_user_txs(client, address, chain_id, api_key, limit=300):
    """Try Etherscan V2 first; if the chain isn't on the free plan, fall back
    to the chain's free Blockscout instance."""
    # Try Etherscan V2
    try:
        r = await client.get(ETHERSCAN_V2, params={
            "chainid": chain_id, "module": "account", "action": "txlist",
            "address": address, "startblock": 0, "endblock": 99999999,
            "page": 1, "offset": limit, "sort": "desc", "apikey": api_key,
        }, timeout=30.0)
        d = r.json()
        if d.get("status") == "1" and isinstance(d.get("result"), list):
            return d["result"]
    except Exception:
        pass
    # Fall back to Blockscout (free, no key)
    host = BLOCKSCOUT_HOSTS.get(chain_id)
    if host:
        try:
            r = await client.get(f"https://{host}/api", params={
                "module": "account", "action": "txlist", "address": address,
                "page": 1, "offset": limit, "sort": "desc",
            }, timeout=30.0)
            d = r.json()
            if isinstance(d.get("result"), list):
                return d["result"]
        except Exception:
            pass
    # Last resort: chain-specific Etherscan-like (e.g. Snowtrace for Avalanche)
    url = ETHERSCAN_LIKE.get(chain_id)
    if url:
        try:
            r = await client.get(url, params={
                "module": "account", "action": "txlist", "address": address,
                "page": 1, "offset": limit, "sort": "desc",
            }, timeout=30.0)
            d = r.json()
            if isinstance(d.get("result"), list):
                return d["result"]
        except Exception:
            pass
    return []


def is_yieldo_target(to_addr: str, chain_id: int) -> bool:
    if not to_addr: return False
    a = to_addr.lower()
    if a == LIFI_DIAMOND.lower(): return True
    if a in LIFI_EXEC_ADDRS: return True
    router = ROUTERS.get(chain_id)
    if router and a == router.lower(): return True
    return False


async def main():
    _load_env()
    mongo_url = os.environ.get("MONGODB_URL")
    api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not mongo_url: print("MONGODB_URL not set", file=sys.stderr); sys.exit(1)
    if not api_key: print("ETHERSCAN_API_KEY not set (look in E:/yieldo-contracts/.env)", file=sys.stderr); sys.exit(1)
    dry = os.environ.get("DRY", "").strip() in ("1","true","yes")

    db = AsyncIOMotorClient(mongo_url)["yieldo_wallets"]
    txs = db["transactions"]

    # 1) Find every record with no tx_hash. Group by (user_address, chain).
    needing = {}   # (user, chain) -> [records]
    cursor = txs.find({"tx_hash": None})
    async for d in cursor:
        ua = (d.get("user_address") or "").lower()
        ch = d.get("from_chain_id")
        if not ua or not ch: continue
        needing.setdefault((ua, ch), []).append(d)
    print(f"records missing tx_hash: {sum(len(v) for v in needing.values())} across {len(needing)} (user,chain) pairs")

    matched = 0
    rebumped = 0  # asked /v1/status to resolve
    async with httpx.AsyncClient() as client:
        for (user, chain), recs in needing.items():
            print(f"\nuser={user} chain={chain} records={len(recs)}")
            chain_txs = await fetch_user_txs(client, user, chain, api_key)
            relevant = [t for t in chain_txs if is_yieldo_target(t.get("to") or "", chain)
                        and (t.get("isError") in (None, "0") or True)]
            print(f"  on-chain txs to LiFi/router: {len(relevant)}")
            if not relevant: continue

            # Sort records oldest-first; greedy match against on-chain tx by closest timestamp.
            recs.sort(key=lambda d: d.get("created_at") or datetime.min.replace(tzinfo=timezone.utc))
            used = set()
            for rec in recs:
                created = rec.get("created_at")
                if isinstance(created, str):
                    try: created = datetime.fromisoformat(created.replace("Z","+00:00"))
                    except Exception: continue
                if isinstance(created, datetime) and created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if not isinstance(created, datetime): continue
                ct = int(created.timestamp())

                best = None; best_dt = TIME_WINDOW_SEC + 1
                for t in relevant:
                    h = t.get("hash")
                    if not h or h in used: continue
                    ts = int(t.get("timeStamp") or 0)
                    if ts == 0: continue
                    dt = abs(ts - ct)
                    if dt < best_dt:
                        best_dt = dt; best = t
                if not best:
                    print(f"  no match for record created={created} ({rec.get('vault_name','?')[:30]})")
                    continue
                used.add(best["hash"])
                tx_hash = best["hash"]
                onchain_status = "failed" if best.get("isError") == "1" else None
                print(f"  match  rec.created={created.isoformat()[:19]} -> tx={tx_hash[:14]}… (delta={best_dt}s)")
                if not dry:
                    update = {"$set": {"tx_hash": tx_hash, "updated_at": datetime.now(timezone.utc)}}
                    # If on-chain says failed, mark it now. If success, push to submitted so /v1/status takes over.
                    if onchain_status:
                        update["$set"]["status"] = "failed"
                    else:
                        update["$set"]["status"] = "submitted"
                    await txs.update_one({"_id": rec["_id"]}, update)
                matched += 1

                # Trigger our /v1/status to fully resolve via LiFi (cross-chain) or RPC (same-chain).
                to_chain = rec.get("to_chain_id") or chain
                try:
                    await client.get(f"{API}/v1/status",
                        params={"tx_hash": tx_hash, "from_chain_id": chain, "to_chain_id": to_chain},
                        timeout=20.0)
                    rebumped += 1
                except Exception:
                    pass

    print(f"\nlinked tx_hash on {matched} records; triggered /v1/status on {rebumped}")
    if dry: print("DRY=1 — no writes performed.")


if __name__ == "__main__":
    asyncio.run(main())
