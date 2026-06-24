"""Re-trigger /v1/status on every completed cross-chain record that's missing
dest_tx_hash, so the destination receipt link surfaces on HistoryPage. Safe
to re-run; idempotent.

  python scripts/backfill_dest_tx_hash.py
"""
import asyncio, os, sys
from pathlib import Path
import httpx
from motor.motor_asyncio import AsyncIOMotorClient

API = os.environ.get("YIELDO_API", "https://api.yieldo.xyz")

def _load_env():
    p = Path(__file__).resolve().parent.parent / ".env"
    if not p.exists(): return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k,_,v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())

async def main():
    _load_env()
    url = os.environ.get("MONGODB_URL")
    if not url: print("MONGODB_URL not set", file=sys.stderr); sys.exit(1)
    db = AsyncIOMotorClient(url)["yieldo_wallets"]
    txs = db["transactions"]

    q = {
        "tx_hash": {"$ne": None},
        "from_chain_id": {"$ne": None},
        "to_chain_id":   {"$ne": None},
        "$expr": {"$ne": ["$from_chain_id", "$to_chain_id"]},
        "status": {"$in": ["completed", "partial"]},
        "$or": [{"dest_tx_hash": {"$exists": False}}, {"dest_tx_hash": None}],
    }
    n = await txs.count_documents(q)
    print(f"records to refresh: {n}")
    triggered = 0
    async with httpx.AsyncClient() as client:
        async for d in txs.find(q):
            try:
                r = await client.get(f"{API}/v1/status",
                    params={"tx_hash": d["tx_hash"], "from_chain_id": d["from_chain_id"], "to_chain_id": d["to_chain_id"]},
                    timeout=20.0)
                triggered += 1
                if triggered % 5 == 0:
                    print(f"  {triggered}/{n} refreshed")
            except Exception as e:
                print(f"  err on tx={d.get('tx_hash','')[:10]}: {e}")
    print(f"done — triggered {triggered}/{n}")

if __name__ == "__main__":
    asyncio.run(main())
