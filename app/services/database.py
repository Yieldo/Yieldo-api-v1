import logging
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db = None


async def connect(url: str):
    global _client, _db
    try:
        _client = AsyncIOMotorClient(url)
        _db = _client["yieldo_wallets"]
        await _ensure_indexes()
        logger.info("MongoDB connected")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        _client = None
        _db = None


async def disconnect():
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB disconnected")


async def _ensure_indexes():
    if _db is None:
        return
    try:
        quotes = _db["quotes"]
        await quotes.create_index("user_address")
        await quotes.create_index("vault_id")
        await quotes.create_index("created_at")

        transactions = _db["transactions"]
        await transactions.create_index("user_address")
        await transactions.create_index("vault_id")
        await transactions.create_index("created_at")
        await transactions.create_index("status")
        await transactions.create_index("tx_hash")

        # Partner indexes
        partners = _db["partners"]
        await partners.create_index("address", unique=True)
        await partners.create_index("api_key_hash")

        nonces = _db["partner_nonces"]
        await nonces.create_index("address")
        await nonces.create_index("created_at", expireAfterSeconds=300)

        sessions = _db["partner_sessions"]
        await sessions.create_index("token_hash")
        await sessions.create_index("expires_at", expireAfterSeconds=0)

        ptx = _db["partner_transactions"]
        await ptx.create_index("partner_address")
        await ptx.create_index("user_address")
        await ptx.create_index("created_at")

        pusers = _db["partner_users"]
        await pusers.create_index([("partner_address", 1), ("user_address", 1)], unique=True)

        # KOL indexes
        kols = _db["kols"]
        await kols.create_index("address", unique=True)
        await kols.create_index("handle", unique=True)

        kol_nonces = _db["kol_nonces"]
        await kol_nonces.create_index("address")
        await kol_nonces.create_index("created_at", expireAfterSeconds=300)

        kol_sessions = _db["kol_sessions"]
        await kol_sessions.create_index("token_hash")
        await kol_sessions.create_index("expires_at", expireAfterSeconds=0)

        kol_referrals = _db["kol_referrals"]
        await kol_referrals.create_index("kol_address")
        await kol_referrals.create_index("user_address")
        await kol_referrals.create_index("created_at")

        kol_users = _db["kol_users"]
        await kol_users.create_index([("kol_address", 1), ("user_address", 1)], unique=True)
        # User indexes
        users = _db["users"]
        await users.create_index("address", unique=True)

        user_nonces = _db["user_nonces"]
        await user_nonces.create_index("address")
        await user_nonces.create_index("created_at", expireAfterSeconds=300)

        user_sessions = _db["user_sessions"]
        await user_sessions.create_index("token_hash")
        await user_sessions.create_index("expires_at", expireAfterSeconds=0)

    except Exception as e:
        logger.error(f"MongoDB index creation failed: {e}")


async def save_quote(request_dict: dict, response_dict: dict) -> Optional[str]:
    if _db is None:
        return None
    try:
        doc = {
            "request": request_dict,
            "response": response_dict,
            "user_address": request_dict.get("user_address"),
            "vault_id": request_dict.get("vault_id"),
            "quote_type": response_dict.get("quote_type"),
            "created_at": datetime.now(timezone.utc),
        }
        result = await _db["quotes"].insert_one(doc)
        return str(result.inserted_id)
    except Exception as e:
        logger.error(f"Failed to save quote: {e}")
        return None


async def save_transaction(
    request_dict: dict,
    response_dict: dict,
    vault_name: str = "",
    referrer: str = "",
    referrer_handle: str = "",
    quote_type: str = "",
) -> Optional[str]:
    if _db is None:
        return None
    try:
        now = datetime.now(timezone.utc)
        tracking = response_dict.get("tracking", {})
        doc = {
            "request": request_dict,
            "response": response_dict,
            "user_address": request_dict.get("user_address"),
            "vault_id": request_dict.get("vault_id"),
            "vault_name": vault_name,
            "from_chain_id": request_dict.get("from_chain_id"),
            "to_chain_id": tracking.get("to_chain_id"),
            "from_token": request_dict.get("from_token"),
            "from_amount": request_dict.get("from_amount"),
            "referrer": referrer or request_dict.get("referrer", ""),
            "referrer_handle": referrer_handle,
            "quote_type": quote_type,
            "status": "pending",
            "tx_hash": None,
            "lifi_explorer": tracking.get("lifi_explorer"),
            "bridge": tracking.get("bridge"),
            "status_history": [{"status": "pending", "timestamp": now}],
            "created_at": now,
            "updated_at": now,
        }
        result = await _db["transactions"].insert_one(doc)
        return str(result.inserted_id)
    except Exception as e:
        logger.error(f"Failed to save transaction: {e}")
        return None


async def update_transaction_status(
    tx_hash: str,
    from_chain_id: int,
    new_status: str,
    extra_fields: Optional[dict] = None,
):
    if _db is None:
        return
    try:
        now = datetime.now(timezone.utc)
        update: dict = {
            "$set": {
                "status": new_status,
                "tx_hash": tx_hash,
                "updated_at": now,
            },
            "$push": {
                "status_history": {"status": new_status, "timestamp": now},
            },
        }
        if extra_fields:
            update["$set"].update(extra_fields)

        await _db["transactions"].update_one(
            {"tx_hash": tx_hash, "from_chain_id": from_chain_id},
            update,
            upsert=True,
        )
    except Exception as e:
        logger.error(f"Failed to update transaction status: {e}")


async def get_user_deposits(address: str, limit: int = 50, skip: int = 0) -> list[dict]:
    if _db is None:
        return []
    cursor = _db["transactions"].find(
        {"user_address": address.lower()},
        {
            "_id": 0,
            "request": 0,
            "response": 0,
        },
    ).sort("created_at", -1).skip(skip).limit(limit)
    return await cursor.to_list(limit)


async def get_user_deposit_summary(address: str) -> dict:
    if _db is None:
        return {}
    addr = address.lower()
    coll = _db["transactions"]
    total = await coll.count_documents({"user_address": addr})
    completed = await coll.count_documents({"user_address": addr, "status": "completed"})
    failed = await coll.count_documents({"user_address": addr, "status": "failed"})
    pending = await coll.count_documents({"user_address": addr, "status": {"$in": ["pending", "submitted"]}})
    return {
        "total_deposits": total,
        "completed": completed,
        "failed": failed,
        "pending": pending,
    }


# ========== Partner / Wallet Provider ==========

async def save_nonce(address: str, nonce: str):
    if _db is None:
        return
    await _db["partner_nonces"].insert_one({
        "address": address.lower(),
        "nonce": nonce,
        "created_at": datetime.now(timezone.utc),
    })


async def get_and_delete_nonce(address: str) -> Optional[str]:
    if _db is None:
        return None
    doc = await _db["partner_nonces"].find_one_and_delete(
        {"address": address.lower()},
        sort=[("created_at", -1)],
    )
    return doc["nonce"] if doc else None


async def create_partner(
    address: str, name: str, website: str, contact_email: str,
    description: str, api_key_hash: str, api_secret_hash: str,
    api_key_prefix: str,
) -> dict:
    if _db is None:
        return {}
    now = datetime.now(timezone.utc)
    doc = {
        "address": address.lower(),
        "name": name,
        "website": website,
        "contact_email": contact_email,
        "description": description,
        "fee_enabled": True,
        "fee_collector_address": address.lower(),
        "webhook_url": "",
        "enrolled_vaults": [],
        "api_key_hash": api_key_hash,
        "api_secret_hash": api_secret_hash,
        "api_key_prefix": api_key_prefix,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    await _db["partners"].insert_one(doc)
    return doc


async def get_partner_by_address(address: str) -> Optional[dict]:
    if _db is None:
        return None
    return await _db["partners"].find_one({"address": address.lower()})


async def get_partner_by_api_key(api_key_hash: str) -> Optional[dict]:
    if _db is None:
        return None
    return await _db["partners"].find_one({
        "api_key_hash": api_key_hash,
        "status": "active",
    })


async def update_partner(address: str, fields: dict):
    if _db is None:
        return
    fields["updated_at"] = datetime.now(timezone.utc)
    await _db["partners"].update_one(
        {"address": address.lower()},
        {"$set": fields},
    )


async def rotate_partner_keys(address: str, api_key_hash: str, api_secret_hash: str, api_key_prefix: str):
    if _db is None:
        return
    await update_partner(address, {
        "api_key_hash": api_key_hash,
        "api_secret_hash": api_secret_hash,
        "api_key_prefix": api_key_prefix,
    })


async def save_session(token_hash: str, address: str, expires_at: datetime) -> None:
    if _db is None:
        return
    await _db["partner_sessions"].insert_one({
        "token_hash": token_hash,
        "address": address.lower(),
        "created_at": datetime.now(timezone.utc),
        "expires_at": expires_at,
    })


async def get_session(token_hash: str) -> Optional[dict]:
    if _db is None:
        return None
    now = datetime.now(timezone.utc)
    return await _db["partner_sessions"].find_one({
        "token_hash": token_hash,
        "expires_at": {"$gt": now},
    })


async def delete_sessions(address: str):
    if _db is None:
        return
    await _db["partner_sessions"].delete_many({"address": address.lower()})


async def save_partner_transaction(
    partner_address: str, user_address: str, vault_id: str,
    from_chain_id: int, from_amount: str, quote_type: str,
    fee_amount: str = "0",
):
    if _db is None:
        return
    now = datetime.now(timezone.utc)
    await _db["partner_transactions"].insert_one({
        "partner_address": partner_address.lower(),
        "user_address": user_address.lower(),
        "vault_id": vault_id,
        "from_chain_id": from_chain_id,
        "from_amount": from_amount,
        "quote_type": quote_type,
        "status": "pending",
        "fee_amount": fee_amount,
        "created_at": now,
    })
    # Track unique user
    try:
        await _db["partner_users"].update_one(
            {"partner_address": partner_address.lower(), "user_address": user_address.lower()},
            {
                "$set": {"last_seen": now},
                "$setOnInsert": {"first_seen": now},
                "$inc": {"total_deposits": 1},
            },
            upsert=True,
        )
    except Exception:
        pass


async def get_partner_dashboard(address: str) -> dict:
    if _db is None:
        return {}
    addr = address.lower()
    coll = _db["partner_transactions"]
    users_coll = _db["partner_users"]

    from datetime import timedelta
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    total = await coll.count_documents({"partner_address": addr})
    successful = await coll.count_documents({"partner_address": addr, "status": {"$in": ["completed", "pending"]}})
    failed = await coll.count_documents({"partner_address": addr, "status": "failed"})
    txns_7d = await coll.count_documents({"partner_address": addr, "created_at": {"$gte": week_ago}})
    total_users = await users_coll.count_documents({"partner_address": addr})
    users_7d = await users_coll.count_documents({"partner_address": addr, "last_seen": {"$gte": week_ago}})

    # Sum volume and fees
    pipeline = [
        {"$match": {"partner_address": addr}},
        {"$group": {
            "_id": None,
            "total_volume": {"$sum": {"$toLong": "$from_amount"}},
            "total_fees": {"$sum": {"$toLong": "$fee_amount"}},
        }},
    ]
    agg = await coll.aggregate(pipeline).to_list(1)
    vol = str(agg[0]["total_volume"]) if agg else "0"
    fees = str(agg[0]["total_fees"]) if agg else "0"

    return {
        "total_transactions": total,
        "successful_transactions": successful,
        "failed_transactions": failed,
        "total_volume": vol,
        "total_users": total_users,
        "total_fee_earned": fees,
        "transactions_7d": txns_7d,
        "users_7d": users_7d,
    }


async def get_partner_transactions(address: str, limit: int = 50, skip: int = 0) -> list[dict]:
    if _db is None:
        return []
    cursor = _db["partner_transactions"].find(
        {"partner_address": address.lower()},
        {"_id": 0},
    ).sort("created_at", -1).skip(skip).limit(limit)
    return await cursor.to_list(limit)


# ========== KOL ==========

async def save_kol_nonce(address: str, nonce: str):
    if _db is None:
        return
    await _db["kol_nonces"].insert_one({
        "address": address.lower(),
        "nonce": nonce,
        "created_at": datetime.now(timezone.utc),
    })


async def get_and_delete_kol_nonce(address: str) -> Optional[str]:
    if _db is None:
        return None
    doc = await _db["kol_nonces"].find_one_and_delete(
        {"address": address.lower()},
        sort=[("created_at", -1)],
    )
    return doc["nonce"] if doc else None


async def create_kol(
    address: str, handle: str, name: str, bio: str, twitter: str,
) -> dict:
    if _db is None:
        return {}
    now = datetime.now(timezone.utc)
    doc = {
        "address": address.lower(),
        "handle": handle.lower(),
        "name": name,
        "bio": bio,
        "twitter": twitter,
        "fee_collector_address": address.lower(),
        "enrolled_vaults": [],
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    await _db["kols"].insert_one(doc)
    return doc


async def get_kol_by_address(address: str) -> Optional[dict]:
    if _db is None:
        return None
    return await _db["kols"].find_one({"address": address.lower()})


async def get_kol_by_handle(handle: str) -> Optional[dict]:
    if _db is None:
        return None
    return await _db["kols"].find_one({"handle": handle.lower()})


async def get_kol_by_referrer(addr: str) -> Optional[dict]:
    """Find a KOL whose main address OR fee_collector_address matches. Used by quote
    flow to resolve on-chain referrer back to its KOL record for fee_enabled lookup."""
    if _db is None:
        return None
    a = addr.lower()
    return await _db["kols"].find_one({"$or": [{"address": a}, {"fee_collector_address": a}]})


async def save_withdraw(*, user: str, vault_id: str, vault_name: str, shares: str, asset: str, mode: str, chain_id: int) -> Optional[str]:
    if _db is None:
        return None
    doc = {
        "user": user.lower(), "vault_id": vault_id, "vault_name": vault_name,
        "shares": shares, "asset": asset.lower(), "mode": mode, "chain_id": chain_id,
        "status": "pending", "created_at": datetime.now(timezone.utc),
    }
    result = await _db["withdrawals"].insert_one(doc)
    return str(result.inserted_id)


async def mark_withdraw_request_submitted(tracking_id: str, *, req_hash: str, protocol_request_id: str, escrow: str, tx_hash: str):
    if _db is None:
        return
    from bson import ObjectId
    await _db["withdrawals"].update_one(
        {"_id": ObjectId(tracking_id)},
        {"$set": {
            "req_hash": req_hash, "protocol_request_id": protocol_request_id,
            "escrow_address": escrow, "tx_hash": tx_hash, "status": "submitted",
            "submitted_at": datetime.now(timezone.utc),
        }},
    )


async def mark_withdraw_claimed(req_hash: str, tx_hash: str):
    if _db is None:
        return
    await _db["withdrawals"].update_one(
        {"req_hash": req_hash},
        {"$set": {"status": "claimed", "claim_tx": tx_hash, "claimed_at": datetime.now(timezone.utc)}},
    )


async def get_withdraw_by_req_hash(req_hash: str) -> Optional[dict]:
    if _db is None:
        return None
    return await _db["withdrawals"].find_one({"req_hash": req_hash.lower()})


async def get_user_withdraw_requests(user_address: str) -> list[dict]:
    if _db is None:
        return []
    docs = await _db["withdrawals"].find(
        {"user": user_address.lower(), "mode": "async"},
    ).sort("created_at", -1).to_list(length=200)
    for d in docs:
        d["id"] = str(d.pop("_id"))
        for k in ("created_at", "submitted_at", "claimed_at"):
            if k in d and isinstance(d[k], datetime):
                d[k] = d[k].isoformat()
    return docs


async def update_kol(address: str, fields: dict):
    if _db is None:
        return
    fields["updated_at"] = datetime.now(timezone.utc)
    await _db["kols"].update_one(
        {"address": address.lower()},
        {"$set": fields},
    )


async def save_kol_session(token_hash: str, address: str, expires_at: datetime) -> None:
    if _db is None:
        return
    await _db["kol_sessions"].insert_one({
        "token_hash": token_hash,
        "address": address.lower(),
        "created_at": datetime.now(timezone.utc),
        "expires_at": expires_at,
    })


async def get_kol_session(token_hash: str) -> Optional[dict]:
    if _db is None:
        return None
    now = datetime.now(timezone.utc)
    return await _db["kol_sessions"].find_one({
        "token_hash": token_hash,
        "expires_at": {"$gt": now},
    })


async def delete_kol_sessions(address: str):
    if _db is None:
        return
    await _db["kol_sessions"].delete_many({"address": address.lower()})


async def get_kol_dashboard(address: str) -> dict:
    if _db is None:
        return {}
    addr = address.lower()
    coll = _db["kol_referrals"]
    users_coll = _db["kol_users"]

    from datetime import timedelta
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    total = await coll.count_documents({"kol_address": addr})
    total_users = await users_coll.count_documents({"kol_address": addr})
    referrals_7d = await coll.count_documents({"kol_address": addr, "created_at": {"$gte": week_ago}})
    users_7d = await users_coll.count_documents({"kol_address": addr, "last_seen": {"$gte": week_ago}})

    pipeline = [
        {"$match": {"kol_address": addr}},
        {"$group": {
            "_id": None,
            "total_volume": {"$sum": {"$toLong": "$from_amount"}},
            "total_earnings": {"$sum": {"$toLong": "$fee_amount"}},
        }},
    ]
    agg = await coll.aggregate(pipeline).to_list(1)
    vol = str(agg[0]["total_volume"]) if agg else "0"
    earnings = str(agg[0]["total_earnings"]) if agg else "0"

    return {
        "total_referrals": total,
        "total_volume": vol,
        "total_earnings": earnings,
        "total_users": total_users,
        "referrals_7d": referrals_7d,
        "users_7d": users_7d,
    }


async def get_kol_referrals(address: str, limit: int = 50, skip: int = 0) -> list[dict]:
    if _db is None:
        return []
    cursor = _db["kol_referrals"].find(
        {"kol_address": address.lower()},
        {"_id": 0},
    ).sort("created_at", -1).skip(skip).limit(limit)
    return await cursor.to_list(limit)


# ========== Users ==========

async def save_user_nonce(address: str, nonce: str):
    if _db is None:
        return
    await _db["user_nonces"].insert_one({
        "address": address.lower(),
        "nonce": nonce,
        "created_at": datetime.now(timezone.utc),
    })


async def get_and_delete_user_nonce(address: str) -> Optional[str]:
    if _db is None:
        return None
    doc = await _db["user_nonces"].find_one_and_delete(
        {"address": address.lower()},
        sort=[("created_at", -1)],
    )
    return doc["nonce"] if doc else None


async def get_or_create_user(address: str) -> dict:
    """Auto-register user on first login, or return existing."""
    if _db is None:
        return {}
    addr = address.lower()
    now = datetime.now(timezone.utc)
    existing = await _db["users"].find_one({"address": addr})
    if existing:
        await _db["users"].update_one(
            {"address": addr},
            {"$set": {"last_login": now}},
        )
        existing["last_login"] = now
        return existing
    doc = {
        "address": addr,
        "status": "active",
        "created_at": now,
        "last_login": now,
    }
    await _db["users"].insert_one(doc)
    return doc


async def get_user_by_address(address: str) -> Optional[dict]:
    if _db is None:
        return None
    return await _db["users"].find_one({"address": address.lower()})


async def save_user_session(token_hash: str, address: str, expires_at: datetime) -> None:
    if _db is None:
        return
    await _db["user_sessions"].insert_one({
        "token_hash": token_hash,
        "address": address.lower(),
        "created_at": datetime.now(timezone.utc),
        "expires_at": expires_at,
    })


async def get_user_session(token_hash: str) -> Optional[dict]:
    if _db is None:
        return None
    now = datetime.now(timezone.utc)
    return await _db["user_sessions"].find_one({
        "token_hash": token_hash,
        "expires_at": {"$gt": now},
    })


async def delete_user_sessions(address: str):
    if _db is None:
        return
    await _db["user_sessions"].delete_many({"address": address.lower()})


async def delete_all_users():
    """Drop all user data — users, sessions, nonces."""
    if _db is None:
        return
    await _db["users"].delete_many({})
    await _db["user_sessions"].delete_many({})
    await _db["user_nonces"].delete_many({})
