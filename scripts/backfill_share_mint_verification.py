"""One-time backfill: re-evaluate every historical 'completed' deposit with
share-mint verification, demote to 'partial' the ones where no shares actually
arrived in the user's wallet.

Same logic as `app/services/status_resolver.py::_verify_share_mint` but runs
across the whole `transactions` collection, not just pending records.

Reads the receipt of:
  - same-chain single-tx flows  -> tx_hash itself
  - cross-chain composer flows  -> dest_tx_hash (LiFi receiving)
  - two-step parents            -> their child's tx_hash
For each, scans logs for an ERC-20 Transfer of the vault's share token to
the user. No mint = swap/bridge succeeded but the deposit didn't happen,
which is exactly the Midas HyperBTC class of bug.

Usage:
  DRY=1 python scripts/backfill_share_mint_verification.py   # dry-run, prints what would change
  python scripts/backfill_share_mint_verification.py         # write changes
"""
import os, sys, asyncio
from datetime import datetime, timezone
from pathlib import Path
import httpx
from motor.motor_asyncio import AsyncIOMotorClient


def _load_env():
    p = Path(__file__).resolve().parent.parent / ".env"
    if not p.exists(): return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())


_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

RPCS = {
    1:    os.environ.get("ETHEREUM_RPC_URL")  or "https://eth.llamarpc.com",
    8453: os.environ.get("BASE_RPC_URL")      or "https://mainnet.base.org",
    42161:os.environ.get("ARBITRUM_RPC_URL")  or "https://arb1.arbitrum.io/rpc",
    10:   os.environ.get("OPTIMISM_RPC_URL")  or "https://mainnet.optimism.io",
    143:  os.environ.get("MONAD_RPC_URL")     or "https://rpc.monad.xyz",
    999:  os.environ.get("HYPEREVM_RPC_URL")  or "https://rpc.hyperliquid.xyz/evm",
}


async def _get_receipt(client, rpc, tx_hash):
    if not rpc or not tx_hash: return None
    try:
        r = await client.post(rpc, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx_hash],
        }, timeout=20.0)
        return (r.json() or {}).get("result")
    except Exception:
        return None


def _verify_share_mint(receipt, share_token, user):
    if not share_token or not user or not receipt: return False
    st = share_token.lower()
    user_topic = "0x" + ("000000000000000000000000" + user.lower().lstrip("0x")).rjust(64, "0")[-64:]
    for log in receipt.get("logs") or []:
        try:
            if (log.get("address") or "").lower() != st: continue
            topics = log.get("topics") or []
            if len(topics) < 3 or topics[0].lower() != _TRANSFER_TOPIC: continue
            if topics[2].lower() != user_topic.lower(): continue
            if int(log.get("data", "0x0"), 16) > 0: return True
        except Exception:
            continue
    return False


def _share_token_for(doc, vaults_by_id):
    """vaults_by_id[chain_id:lowercase_addr] -> {address, share_token, ...}"""
    vid = (doc.get("vault_id") or "").lower()
    v = vaults_by_id.get(vid)
    if not v: return None
    return v.get("share_token") or v.get("address")


def _load_vaults_index():
    """Load vaults.json -> dict keyed by 'chain_id:lowercase_addr'."""
    import json
    path = Path(__file__).resolve().parent.parent / "data" / "vaults.json"
    raw = json.loads(path.read_text())
    out = {}
    for v in raw:
        addr = (v.get("address") or "").lower()
        if not addr: continue
        out[f"{v['chain_id']}:{addr}"] = v
    return out


async def _resolve_receipt_for_doc(doc, txs_coll, client, vaults_by_id):
    """Determine WHICH receipt holds the share-mint event for this record:
       - two-step parent  -> the child's tx_hash receipt (on dest chain)
       - cross-chain composer -> dest_tx_hash receipt
       - everything else  -> source tx_hash receipt
    Returns (receipt, share_token, user, note)."""
    user = (doc.get("user_address") or "").lower()
    share_token = _share_token_for(doc, vaults_by_id)
    if not share_token or not user:
        return None, None, None, "no share_token or user"

    response = doc.get("response") or {}
    is_two_step = bool(response.get("two_step")) and not doc.get("parent_tracking_id")
    if is_two_step:
        # Find the child record
        child = await txs_coll.find_one(
            {"parent_tracking_id": str(doc["_id"])},
            sort=[("created_at", -1)],
        )
        if child and child.get("tx_hash"):
            chain = child.get("from_chain_id")
            rpc = RPCS.get(chain)
            receipt = await _get_receipt(client, rpc, child["tx_hash"])
            return receipt, share_token, user, f"checked child tx {child['tx_hash'][:14]}…"
        # No child tx — step-2 was never sent. The source receipt is just the
        # swap/bridge, which won't have a share-mint event. Fall through to
        # source-receipt check; the verify will correctly return False and
        # demote the record to 'partial' (this catches the Midas HyperBTC
        # "swap succeeded, deposit never happened" case).
        if doc.get("tx_hash"):
            rpc = RPCS.get(doc.get("from_chain_id"))
            receipt = await _get_receipt(client, rpc, doc["tx_hash"])
            return receipt, share_token, user, "two-step parent, no child — checked source (will be partial if no mint)"
        return None, share_token, user, "two-step: no child tx + no source tx"

    # Cross-chain composer: check dest_tx_hash if present
    from_c, to_c = doc.get("from_chain_id"), doc.get("to_chain_id")
    if from_c and to_c and from_c != to_c and doc.get("dest_tx_hash"):
        rpc = RPCS.get(to_c)
        receipt = await _get_receipt(client, rpc, doc["dest_tx_hash"])
        return receipt, share_token, user, f"checked dest tx {doc['dest_tx_hash'][:14]}…"

    # Same-chain or any single-tx flow: source receipt
    if not doc.get("tx_hash"):
        return None, share_token, user, "no tx_hash"
    rpc = RPCS.get(from_c)
    receipt = await _get_receipt(client, rpc, doc["tx_hash"])
    return receipt, share_token, user, f"checked source tx {doc['tx_hash'][:14]}…"


async def main():
    _load_env()
    url = os.environ.get("MONGODB_URL")
    if not url: print("MONGODB_URL not set", file=sys.stderr); sys.exit(1)
    dry = os.environ.get("DRY", "").strip() in ("1", "true", "yes")
    db = AsyncIOMotorClient(url)["yieldo_wallets"]
    txs = db["transactions"]
    vaults_by_id = _load_vaults_index()
    print(f"Loaded {len(vaults_by_id)} vaults from vaults.json")

    n_total = await txs.count_documents({"status": "completed"})
    print(f"Scanning {n_total} 'completed' transactions...\n")

    n_demoted = 0
    n_verified = 0
    n_unknown = 0
    async with httpx.AsyncClient() as client:
        async for doc in txs.find({"status": "completed"}):
            receipt, share_token, user, note = await _resolve_receipt_for_doc(doc, txs, client, vaults_by_id)
            label = f"{(doc.get('vault_name') or 'unknown')[:30]:<30} tx={(doc.get('tx_hash') or '')[:14]}… created={str(doc.get('created_at'))[:19]}"
            if receipt is None:
                n_unknown += 1
                print(f"  ?  {label}  ({note})")
                continue
            verified = _verify_share_mint(receipt, share_token, user)
            if verified:
                n_verified += 1
                continue  # silent on the happy path
            n_demoted += 1
            print(f"  X  {label}  ({note}) — NO SHARE MINT — demoting to 'partial'")
            if not dry:
                now = datetime.now(timezone.utc)
                await txs.update_one(
                    {"_id": doc["_id"]},
                    {
                        "$set": {
                            "status": "partial",
                            "updated_at": now,
                            "resolution_note": "Backfill: receipt confirmed but no share-mint event for user — swap/bridge succeeded but actual deposit didn't happen.",
                        },
                        "$push": {"status_history": {"status": "partial", "timestamp": now, "note": "backfill: no share-mint detected"}},
                    },
                )

    print()
    print(f"verified (real deposits): {n_verified}")
    print(f"demoted to 'partial':     {n_demoted}")
    print(f"unknown / unresolvable:   {n_unknown}")
    if dry:
        print("\nDRY=1 — no writes performed.")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    asyncio.run(main())
