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
    if not _db:
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
    except Exception as e:
        logger.error(f"MongoDB index creation failed: {e}")


async def save_quote(request_dict: dict, response_dict: dict) -> Optional[str]:
    if not _db:
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


async def save_transaction(request_dict: dict, response_dict: dict) -> Optional[str]:
    if not _db:
        return None
    try:
        now = datetime.now(timezone.utc)
        doc = {
            "request": request_dict,
            "response": response_dict,
            "user_address": request_dict.get("user_address"),
            "vault_id": request_dict.get("vault_id"),
            "from_chain_id": request_dict.get("from_chain_id"),
            "to_chain_id": response_dict.get("tracking", {}).get("to_chain_id"),
            "status": "pending",
            "tx_hash": None,
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
    if not _db:
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


# ========== Partner / Wallet Provider ==========

async def save_nonce(address: str, nonce: str):
    if not _db:
        return
    await _db["partner_nonces"].insert_one({
        "address": address.lower(),
        "nonce": nonce,
        "created_at": datetime.now(timezone.utc),
    })


async def get_and_delete_nonce(address: str) -> Optional[str]:
    if not _db:
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
    if not _db:
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
    if not _db:
        return None
    return await _db["partners"].find_one({"address": address.lower()})


async def get_partner_by_api_key(api_key_hash: str) -> Optional[dict]:
    if not _db:
        return None
    return await _db["partners"].find_one({
        "api_key_hash": api_key_hash,
        "status": "active",
    })


async def update_partner(address: str, fields: dict):
    if not _db:
        return
    fields["updated_at"] = datetime.now(timezone.utc)
    await _db["partners"].update_one(
        {"address": address.lower()},
        {"$set": fields},
    )


async def rotate_partner_keys(address: str, api_key_hash: str, api_secret_hash: str, api_key_prefix: str):
    if not _db:
        return
    await update_partner(address, {
        "api_key_hash": api_key_hash,
        "api_secret_hash": api_secret_hash,
        "api_key_prefix": api_key_prefix,
    })


async def save_session(token_hash: str, address: str, expires_at: datetime) -> None:
    if not _db:
        return
    await _db["partner_sessions"].insert_one({
        "token_hash": token_hash,
        "address": address.lower(),
        "created_at": datetime.now(timezone.utc),
        "expires_at": expires_at,
    })


async def get_session(token_hash: str) -> Optional[dict]:
    if not _db:
        return None
    now = datetime.now(timezone.utc)
    return await _db["partner_sessions"].find_one({
        "token_hash": token_hash,
        "expires_at": {"$gt": now},
    })


async def delete_sessions(address: str):
    if not _db:
        return
    await _db["partner_sessions"].delete_many({"address": address.lower()})


async def save_partner_transaction(
    partner_address: str, user_address: str, vault_id: str,
    from_chain_id: int, from_amount: str, quote_type: str,
    fee_amount: str = "0",
):
    if not _db:
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
    if not _db:
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
    if not _db:
        return []
    cursor = _db["partner_transactions"].find(
        {"partner_address": address.lower()},
        {"_id": 0},
    ).sort("created_at", -1).skip(skip).limit(limit)
    return await cursor.to_list(limit)


# ========== KOL ==========

async def save_kol_nonce(address: str, nonce: str):
    if not _db:
        return
    await _db["kol_nonces"].insert_one({
        "address": address.lower(),
        "nonce": nonce,
        "created_at": datetime.now(timezone.utc),
    })


async def get_and_delete_kol_nonce(address: str) -> Optional[str]:
    if not _db:
        return None
    doc = await _db["kol_nonces"].find_one_and_delete(
        {"address": address.lower()},
        sort=[("created_at", -1)],
    )
    return doc["nonce"] if doc else None


async def create_kol(
    address: str, handle: str, name: str, bio: str, twitter: str,
) -> dict:
    if not _db:
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
    if not _db:
        return None
    return await _db["kols"].find_one({"address": address.lower()})


async def get_kol_by_handle(handle: str) -> Optional[dict]:
    if not _db:
        return None
    return await _db["kols"].find_one({"handle": handle.lower()})


async def update_kol(address: str, fields: dict):
    if not _db:
        return
    fields["updated_at"] = datetime.now(timezone.utc)
    await _db["kols"].update_one(
        {"address": address.lower()},
        {"$set": fields},
    )


async def save_kol_session(token_hash: str, address: str, expires_at: datetime) -> None:
    if not _db:
        return
    await _db["kol_sessions"].insert_one({
        "token_hash": token_hash,
        "address": address.lower(),
        "created_at": datetime.now(timezone.utc),
        "expires_at": expires_at,
    })


async def get_kol_session(token_hash: str) -> Optional[dict]:
    if not _db:
        return None
    now = datetime.now(timezone.utc)
    return await _db["kol_sessions"].find_one({
        "token_hash": token_hash,
        "expires_at": {"$gt": now},
    })


async def delete_kol_sessions(address: str):
    if not _db:
        return
    await _db["kol_sessions"].delete_many({"address": address.lower()})


async def get_kol_dashboard(address: str) -> dict:
    if not _db:
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
    if not _db:
        return []
    cursor = _db["kol_referrals"].find(
        {"kol_address": address.lower()},
        {"_id": 0},
    ).sort("created_at", -1).skip(skip).limit(limit)
    return await cursor.to_list(limit)
