"""Infer + back-fill `parent_tracking_id` on historical step-2 deposit records.

A two-step deposit creates two transactions:
  - Parent: cross-chain bridge tx (from_chain -> to_chain, vault on dest)
  - Child : same-chain deposit on the dest chain (from_chain == to_chain), same
            user + same vault, created shortly after the parent (typically a few
            minutes, after the bridge settles).

We pair them by:
  - same user_address
  - same vault_id
  - parent: from_chain_id != to_chain_id  (and vault.to_chain == parent.to_chain)
  - child:  from_chain_id == to_chain_id == parent.to_chain_id
            child.from_token == vault asset_address (it's the deposit leg)
            child.parent_tracking_id is currently None
            created_at(child) > created_at(parent) and < created_at(parent) + WINDOW

  DRY=1 python scripts/backfill_parent_tracking_id.py
  python scripts/backfill_parent_tracking_id.py
"""
import asyncio, os, sys
from datetime import timedelta
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

WINDOW = timedelta(hours=4)  # parent and child must be within this window

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
    dry = os.environ.get("DRY", "").strip() in ("1","true","yes")

    db = AsyncIOMotorClient(url)["yieldo_wallets"]
    txs = db["transactions"]

    # Pull every (user, vault) bucket and look for parent/child pairs.
    n_pairs = 0
    pipeline = [
        {"$match": {"vault_id": {"$ne": None}, "user_address": {"$ne": None}}},
        {"$sort": {"created_at": 1}},
        {"$group": {
            "_id": {"u": "$user_address", "v": "$vault_id"},
            "txs": {"$push": {
                "_id": "$_id", "from_chain_id": "$from_chain_id", "to_chain_id": "$to_chain_id",
                "from_token": "$from_token", "created_at": "$created_at",
                "parent_tracking_id": "$parent_tracking_id",
            }},
        }},
    ]
    async for grp in txs.aggregate(pipeline):
        items = grp["txs"]
        if len(items) < 2: continue
        for parent in items:
            if parent.get("parent_tracking_id"): continue
            p_from = parent.get("from_chain_id"); p_to = parent.get("to_chain_id")
            if not p_from or not p_to or p_from == p_to: continue   # parent must be cross-chain
            for child in items:
                if child["_id"] == parent["_id"]: continue
                if child.get("parent_tracking_id"): continue
                c_from = child.get("from_chain_id"); c_to = child.get("to_chain_id")
                if not c_from or c_from != p_to: continue           # child on parent's dest
                if c_to and c_to != c_from: continue                 # child same-chain
                # time order
                if not parent.get("created_at") or not child.get("created_at"): continue
                if child["created_at"] <= parent["created_at"]: continue
                if child["created_at"] - parent["created_at"] > WINDOW: continue
                # match found
                n_pairs += 1
                print(f"  pair  user={grp['_id']['u'][:10]}…  vault={grp['_id']['v'][:30]}  "
                      f"parent={parent['_id']}  child={child['_id']}")
                if not dry:
                    await txs.update_one(
                        {"_id": child["_id"]},
                        {"$set": {"parent_tracking_id": str(parent["_id"])}},
                    )
                # mark in local list so we don't re-pair
                child["parent_tracking_id"] = "set"
                break  # one child per parent

    print()
    print(f"linked {n_pairs} child -> parent pairs")
    if dry: print("DRY=1 — no writes performed.")

if __name__ == "__main__":
    asyncio.run(main())
