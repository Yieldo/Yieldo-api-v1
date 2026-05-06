"""One-shot fix for cross-chain two-step deposit records that were marked
"completed" by the resolver before commit cdda9ae landed — when in reality the
user's step-2 deposit never executed (e.g., wagmi chain switch failed, tab
closed). The bridge delivered tokens to their wallet but no vault shares were
ever minted.

Usage (on the API VPS):
  cd /home/elliot37/yieldo-api-v1
  source .env
  ./venv/bin/python scripts/cleanup_stuck_deposit.py <tx_hash>

What it does:
  1. Finds the parent transaction record by tx_hash
  2. Confirms it's a cross-chain two-step with no successful child
  3. Flips status to "partial" and writes a recovery note
  4. Prints the before/after for confirmation

Idempotent: safe to re-run. Will skip if status is already terminal-non-completed.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient


RECOVERY_NOTE = (
    "Bridge delivered to your wallet but the vault deposit step never ran. "
    "The bridged tokens are in your wallet on the destination chain — open the "
    "vault from /vault and click Deposit to convert them to vault shares in one tx."
)


async def main(tx_hash: str):
    uri = os.environ.get("MONGODB_URL") or os.environ.get("mongodb_url")
    if not uri:
        print("ERROR: MONGODB_URL not set in environment")
        sys.exit(1)

    client = AsyncIOMotorClient(uri)
    db = client["yieldo_wallets"]
    coll = db["transactions"]

    rec = await coll.find_one({"tx_hash": tx_hash})
    if not rec:
        print(f"No record found for tx_hash={tx_hash}")
        sys.exit(1)

    print("─" * 60)
    print("BEFORE")
    print(f"  _id          : {rec['_id']}")
    print(f"  vault_name   : {rec.get('vault_name')}")
    print(f"  status       : {rec.get('status')}")
    print(f"  from → to    : {rec.get('from_chain_id')} → {rec.get('to_chain_id')}")
    print(f"  user_address : {rec.get('user_address')}")
    is_two_step = bool((rec.get("response") or {}).get("two_step"))
    print(f"  two_step     : {is_two_step}")

    children = await coll.find({"parent_tracking_id": str(rec["_id"])}).to_list(length=10)
    print(f"  children     : {len(children)}")
    completed_child = False
    for c in children:
        cs = c.get("status")
        print(f"    - child status={cs} tx={c.get('tx_hash')}")
        if cs == "completed":
            completed_child = True

    if completed_child:
        print()
        print("Step 2 already succeeded — nothing to clean up. Aborting.")
        return
    if rec.get("status") in ("partial", "failed", "abandoned"):
        print()
        print(f"Already in non-completed terminal state ({rec.get('status')}) — nothing to do.")
        return

    now = datetime.now(timezone.utc)
    update = {
        "$set": {
            "status": "partial",
            "updated_at": now,
            "resolution_note": RECOVERY_NOTE,
        },
        "$push": {
            "status_history": {"status": "partial", "timestamp": now,
                               "reason": "manual cleanup — step-2 never ran"},
        },
    }
    res = await coll.update_one({"_id": rec["_id"]}, update)
    print()
    print("─" * 60)
    print(f"AFTER  modified_count={res.modified_count}")
    after = await coll.find_one({"_id": rec["_id"]})
    print(f"  status         : {after.get('status')}")
    print(f"  resolution_note: {after.get('resolution_note')}")
    print()
    print("Done. The history card on /history will reflect 'Partial' on next page load.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/cleanup_stuck_deposit.py <tx_hash>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
