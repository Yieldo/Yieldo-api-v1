"""One-shot cleanup: delete deposit-only user records.

A deposit-only user is one that has NEVER signed the SIWE message (no
`last_login` in the `users` row, or no row at all). Since the deposit flow now
requires SIWE sign-in before hitting /v1/quote/build, these records are legacy.

This script deletes, for every such address:
  - the address's `transactions` rows
  - the address's `users` row (if present — e.g. seeded_from_transactions)
  - the address's `user_logins` rows (defensive — they should not exist)
  - the address's `user_sessions` rows (defensive)

Usage:
  DRY=1 python scripts/cleanup_deposit_only_users.py   # report only, no deletes
  python scripts/cleanup_deposit_only_users.py         # actually delete

The MongoDB URL is read from MONGODB_URL in the environment or .env file.
"""
import asyncio
import os
import sys
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

# Minimal .env loader (avoids adding dotenv as a dependency)
def _load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


async def main():
    _load_env()
    mongo_url = os.environ.get("MONGODB_URL")
    if not mongo_url:
        print("MONGODB_URL not set in environment or .env", file=sys.stderr)
        sys.exit(1)

    dry = os.environ.get("DRY", "").strip() in ("1", "true", "yes")

    client = AsyncIOMotorClient(mongo_url)
    db = client["yieldo_wallets"]

    users = db["users"]
    transactions = db["transactions"]
    user_logins = db["user_logins"]
    user_sessions = db["user_sessions"]

    # 1) Collect every user_address that appears in transactions
    tx_addresses = set(
        a.lower() for a in await transactions.distinct(
            "user_address",
            {"user_address": {"$nin": [None, ""]}},
        ) if a
    )
    print(f"Distinct addresses with transactions: {len(tx_addresses)}")

    # 2) Of those, which have never signed (no `last_login` in users)?
    signed_in_addresses = set()
    async for u in users.find(
        {"last_login": {"$exists": True, "$ne": None}},
        {"address": 1},
    ):
        if u.get("address"):
            signed_in_addresses.add(u["address"].lower())
    print(f"Addresses that have SIWE-signed at least once: {len(signed_in_addresses)}")

    orphan_addresses = sorted(tx_addresses - signed_in_addresses)
    print(f"Addresses to purge (in tx but never signed): {len(orphan_addresses)}")

    if not orphan_addresses:
        print("Nothing to clean up. Done.")
        return

    # Report
    print("\nFirst 20 targets:")
    for a in orphan_addresses[:20]:
        n = await transactions.count_documents({"user_address": a})
        print(f"  {a}  tx={n}")

    if dry:
        print("\nDRY=1 — no deletes performed.")
        return

    # 3) Delete
    print("\nDeleting…")
    tx_res = await transactions.delete_many({"user_address": {"$in": orphan_addresses}})
    users_res = await users.delete_many({"address": {"$in": orphan_addresses}})
    logins_res = await user_logins.delete_many({"address": {"$in": orphan_addresses}})
    sess_res = await user_sessions.delete_many({"address": {"$in": orphan_addresses}})
    print(f"  transactions deleted: {tx_res.deleted_count}")
    print(f"  users deleted:        {users_res.deleted_count}")
    print(f"  user_logins deleted:  {logins_res.deleted_count}")
    print(f"  user_sessions deleted:{sess_res.deleted_count}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
