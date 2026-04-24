"""Prune vault_ids from every kol's `enrolled_vaults` that no longer exist.

Context: we removed duplicated Accountable vault entries from vaults.json
when their contract addresses were updated to the canonical ones. Users who
had enrolled in the old (now-removed) vault IDs still have those IDs in
their `enrolled_vaults` array, and the UI — which only shows vaults that
still exist — gives them no way to unenroll. This script walks kols and
strips entries that aren't in the current vaults.json.

Usage:
  DRY=1 python scripts/prune_ghost_enrollments.py
  python scripts/prune_ghost_enrollments.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient


def _load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def _load_valid_vault_ids() -> set[str]:
    data_path = Path(__file__).resolve().parent.parent / "data" / "vaults.json"
    raw = json.loads(data_path.read_text())
    valid = set()
    for v in raw:
        chain_id = v["chain_id"]
        addr = v["address"].lower()
        valid.add(f"{chain_id}:{addr}")
    return valid


async def main():
    _load_env()
    mongo_url = os.environ.get("MONGODB_URL")
    if not mongo_url:
        print("MONGODB_URL not set", file=sys.stderr)
        sys.exit(1)
    dry = os.environ.get("DRY", "").strip() in ("1", "true", "yes")

    valid = _load_valid_vault_ids()
    print(f"Valid vault ids: {len(valid)}")

    client = AsyncIOMotorClient(mongo_url)
    db = client["yieldo_wallets"]
    kols = db["kols"]
    partners = db["partners"]

    # Gather changes per collection, then apply
    total_touched = 0
    total_removed = 0
    for coll_name, coll in (("kols", kols), ("partners", partners)):
        touched = 0
        removed_here = 0
        async for doc in coll.find({"enrolled_vaults": {"$exists": True, "$ne": []}}, {"address": 1, "handle": 1, "name": 1, "enrolled_vaults": 1}):
            current = [v.lower() for v in doc.get("enrolled_vaults") or []]
            kept = [v for v in current if v in valid]
            removed = [v for v in current if v not in valid]
            if not removed:
                continue
            label = doc.get("handle") or doc.get("name") or doc.get("address")
            print(f"  [{coll_name}] {label}: removing {len(removed)} stale ({', '.join(removed)})")
            touched += 1
            removed_here += len(removed)
            if not dry:
                await coll.update_one({"_id": doc["_id"]}, {"$set": {"enrolled_vaults": kept}})
        print(f"{coll_name}: touched {touched} docs, removed {removed_here} entries")
        total_touched += touched
        total_removed += removed_here

    if dry:
        print(f"\nDRY=1 — no changes applied. Would touch {total_touched} docs, remove {total_removed} entries.")
    else:
        print(f"\nDone. Touched {total_touched} docs, removed {total_removed} entries.")


if __name__ == "__main__":
    asyncio.run(main())
