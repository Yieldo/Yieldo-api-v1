"""One-shot: lowercase user_address + from_token + referrer in transactions.

Reads/writes the transactions collection. Safe to re-run; idempotent.

  DRY=1 python scripts/normalize_tx_addresses.py
  python scripts/normalize_tx_addresses.py
"""
import asyncio, os, sys
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

def _load_env():
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists(): return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k,_,v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())

async def main():
    _load_env()
    url = os.environ.get("MONGODB_URL")
    if not url: print("MONGODB_URL not set", file=sys.stderr); sys.exit(1)
    dry = os.environ.get("DRY", "").strip() in ("1","true","yes")
    c = AsyncIOMotorClient(url)
    txs = c["yieldo_wallets"]["transactions"]
    total = await txs.count_documents({})
    print(f"transactions: {total}")
    touched = 0
    cursor = txs.find({}, {"user_address": 1, "from_token": 1, "referrer": 1})
    async for d in cursor:
        upd = {}
        for f in ("user_address", "from_token", "referrer"):
            v = d.get(f)
            if isinstance(v, str) and v != v.lower():
                upd[f] = v.lower()
        if upd:
            touched += 1
            if not dry:
                await txs.update_one({"_id": d["_id"]}, {"$set": upd})
    print(f"{'would touch' if dry else 'touched'} {touched} docs")

if __name__ == "__main__":
    asyncio.run(main())
