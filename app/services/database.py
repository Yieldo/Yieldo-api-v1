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
        _db = _client["yieldo"]
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
