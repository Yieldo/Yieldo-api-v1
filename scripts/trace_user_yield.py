"""Diagnostic: show every deposit + withdrawal record contributing to the
yield calc for a user, so we can see exactly which records are inflating
the cost basis."""
import os, sys, asyncio
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

USER = sys.argv[1] if len(sys.argv) > 1 else "0x7E14104e2433fDe49C98008911298F069C9dE41a"

def _load_env():
    p = Path(__file__).resolve().parent.parent / ".env"
    if not p.exists(): return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())

async def main():
    _load_env()
    db = AsyncIOMotorClient(os.environ["MONGODB_URL"])["yieldo_wallets"]
    addr = USER.lower()
    print(f"User: {addr}\n")

    # Per vault — show each deposit record
    by_vault = {}
    cursor = db["transactions"].find({"user_address": addr, "status": "completed"})
    async for tx in cursor:
        vid = tx.get("vault_id")
        if not vid: continue
        est = ((tx.get("response") or {}).get("estimate") or {})
        dep_amt = est.get("deposit_amount") or est.get("to_amount")
        from_token = (tx.get("from_token") or "")
        from_amount = tx.get("from_amount")
        by_vault.setdefault(vid, []).append({
            "name": tx.get("vault_name"), "type": tx.get("quote_type"),
            "from_token": from_token, "from_amount": from_amount,
            "deposit_amount": dep_amt, "tx_hash": tx.get("tx_hash"),
            "created": str(tx.get("created_at"))[:19],
        })

    # Withdrawals
    wd_by_vault = {}
    async for w in db["withdrawals"].find({"user": addr}):
        vid = w.get("vault_id")
        wd_by_vault.setdefault(vid, []).append({
            "shares": w.get("shares"), "assets_out": w.get("assets_out"),
            "status": w.get("status"), "created": str(w.get("created_at"))[:19],
        })

    for vid, txs in sorted(by_vault.items()):
        name = txs[0]["name"] or "?"
        print(f"=== {name}  ({vid}) ===")
        cum_used = 0
        for t in txs:
            used = t["deposit_amount"] or "(skipped — no deposit_amount + cross-asset)"
            tag = "USED" if t["deposit_amount"] else "----"
            print(f"  {tag}  {t['created']}  type={t['type']:<14}  from={t['from_token'][:10]}…  from_amt={t['from_amount']}  deposit_amount={t['deposit_amount']}")
            if isinstance(used, str) and used.startswith("("): continue
            cum_used += int(used)
        wds = wd_by_vault.get(vid, [])
        wd_sum = 0
        for w in wds:
            ao = w.get("assets_out")
            tag = "USED" if ao and w["status"] in ("submitted","completed","claimed") else "skip"
            print(f"  WD-{tag}  {w['created']}  status={w['status']}  shares={w['shares']}  assets_out={ao}")
            if tag == "USED": wd_sum += int(ao)
        net_dep = max(0, cum_used - wd_sum)
        print(f"  >> deposited_sum={cum_used}, withdrawn_sum={wd_sum}, net_deposit_basis={net_dep}\n")

asyncio.run(main())
