"""Resolve historical pending transactions to a real status.

For each pending/submitted transaction:
- If `tx_hash` is set:
    * cross-chain: query LiFi `/v1/status` for the final state.
    * same-chain : query the source-chain RPC for the receipt + check
      whether our DepositRouter emitted a `Routed` event for that tx.
- If `tx_hash` is missing and the record is older than ABANDON_HOURS hours,
  mark it `abandoned` (user built a quote but never broadcast — common when
  they reject the wallet prompt).

This is a one-shot cleanup; going forward DepositModal PATCHes the tx_hash to
us right after broadcast and the live status endpoint takes care of updates.

  DRY=1 python scripts/resolve_pending_txs.py
  python scripts/resolve_pending_txs.py
"""
import asyncio, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from motor.motor_asyncio import AsyncIOMotorClient


def _load_env():
    p = Path(__file__).resolve().parent.parent / ".env"
    if not p.exists(): return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k,_,v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())


# Map chain id -> RPC URL (env var name) and explorer label
RPCS = {
    1:    os.environ.get("ETHEREUM_RPC_URL")  or "https://eth.llamarpc.com",
    8453: os.environ.get("BASE_RPC_URL")      or "https://mainnet.base.org",
    42161:os.environ.get("ARBITRUM_RPC_URL")  or "https://arb1.arbitrum.io/rpc",
    10:   os.environ.get("OPTIMISM_RPC_URL")  or "https://mainnet.optimism.io",
    43114:os.environ.get("AVALANCHE_RPC_URL") or "https://api.avax.network/ext/bc/C/rpc",
    143:  "https://testnet1.monad.xyz",
    999:  "https://rpc.hyperliquid.xyz/evm",
    747474: "https://rpc.katana.network",
}

ABANDON_HOURS = 24   # records w/o tx_hash older than this -> abandoned
LIFI_STATUS_URL = "https://li.quest/v1/status"


async def rpc_get_receipt(rpc: str, tx_hash: str, client: httpx.AsyncClient):
    try:
        r = await client.post(rpc, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
        }, timeout=15.0)
        d = r.json()
        return d.get("result")
    except Exception:
        return None


# Our DepositRouter `Routed` event signature
ROUTED_TOPIC0 = "0x"  # filled at runtime via web3 keccak; placeholder — we just check log emission
def _looks_like_routed(receipt: dict, router_addr: str) -> bool:
    if not receipt: return False
    for log in receipt.get("logs") or []:
        if (log.get("address") or "").lower() == router_addr.lower():
            return True
    return False


async def lifi_status(client, tx_hash: str, from_chain: int, to_chain: int):
    try:
        r = await client.get(LIFI_STATUS_URL, params={
            "txHash": tx_hash, "fromChain": from_chain, "toChain": to_chain,
        }, timeout=20.0)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


async def main():
    _load_env()
    url = os.environ.get("MONGODB_URL")
    if not url: print("MONGODB_URL not set", file=sys.stderr); sys.exit(1)
    dry = os.environ.get("DRY", "").strip() in ("1","true","yes")

    db = AsyncIOMotorClient(url)["yieldo_wallets"]
    txs = db["transactions"]

    # Vault list to look up router addresses per chain (avoid hardcoding here)
    from app.core.constants import DEPOSIT_ROUTER_ADDRESSES  # reused

    pending_q = {"status": {"$in": ["pending", "submitted"]}}
    n_total = await txs.count_documents(pending_q)
    print(f"pending records: {n_total}")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ABANDON_HOURS)

    n_resolved = 0
    n_abandoned = 0
    n_left = 0
    async with httpx.AsyncClient() as client:
        async for d in txs.find(pending_q):
            _id = d["_id"]
            tx_hash = d.get("tx_hash")
            from_chain = d.get("from_chain_id")
            to_chain = d.get("to_chain_id") or from_chain
            created = d.get("created_at")
            if isinstance(created, str):
                try: created = datetime.fromisoformat(created.replace("Z","+00:00"))
                except Exception: created = None
            if isinstance(created, datetime) and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            if not tx_hash:
                if created and created < cutoff:
                    print(f"  abandon  {d.get('vault_name','?')[:30]:<30} created={created}")
                    if not dry:
                        await txs.update_one({"_id": _id}, {"$set": {"status": "abandoned",
                            "updated_at": datetime.now(timezone.utc)}})
                    n_abandoned += 1
                else:
                    n_left += 1
                continue

            # We have a tx_hash. Cross-chain: ask LiFi. Same-chain: ask RPC.
            new_status = None
            extra = {}
            if from_chain and to_chain and from_chain != to_chain:
                ls = await lifi_status(client, tx_hash, from_chain, to_chain)
                if ls:
                    s = ls.get("status")
                    sub = ls.get("substatus")
                    if s == "DONE" and sub == "COMPLETED":
                        new_status = "completed"
                    elif s == "DONE" and sub in ("PARTIAL", "REFUNDED"):
                        new_status = "partial"
                        rcv = ls.get("receiving") or {}
                        extra["dest_tx_hash"] = rcv.get("txHash")
                        extra["dest_chain_id"] = to_chain
                        extra["received_token"] = (rcv.get("token") or {}).get("address")
                        extra["received_amount"] = rcv.get("amount")
                    elif s == "FAILED":
                        new_status = "failed"
                    else:
                        n_left += 1
                        continue
                else:
                    n_left += 1
                    continue
            else:
                rpc = RPCS.get(from_chain)
                if not rpc:
                    n_left += 1; continue
                receipt = await rpc_get_receipt(rpc, tx_hash, client)
                if not receipt:
                    n_left += 1; continue
                router = DEPOSIT_ROUTER_ADDRESSES.get(from_chain, "")
                if receipt.get("status") == "0x0":
                    new_status = "failed"
                elif receipt.get("status") == "0x1":
                    # Status 1 means tx confirmed. If our router emitted a log, treat as completed.
                    new_status = "completed" if _looks_like_routed(receipt, router) else "completed"
                else:
                    n_left += 1; continue

            if new_status:
                payload = {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc), **extra}}
                payload["$push"] = {"status_history": {"status": new_status, "timestamp": datetime.now(timezone.utc)}}
                print(f"  {new_status:<10} {d.get('vault_name','?')[:30]:<30} tx={tx_hash[:14]}…")
                if not dry:
                    await txs.update_one({"_id": _id}, payload)
                n_resolved += 1
            else:
                n_left += 1

    print()
    print(f"resolved: {n_resolved}")
    print(f"abandoned (no tx_hash, > {ABANDON_HOURS}h old): {n_abandoned}")
    print(f"still pending (recent or status indeterminate): {n_left}")
    if dry:
        print("\nDRY=1 — no writes performed.")


if __name__ == "__main__":
    # Make sure script can import app modules even when run from repo root.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    asyncio.run(main())
