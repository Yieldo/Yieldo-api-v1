"""Keep only YIELDO2026; delete every other invite code.

Usage:
    venv/Scripts/python.exe scripts/prune_invite_codes.py
"""
import asyncio
from app.services import database
from app.config import get_settings


KEEP = {"YIELDO2026"}


async def main():
    settings = get_settings()
    if not settings.mongodb_url:
        print("MONGODB_URL not set")
        return
    await database.connect(settings.mongodb_url)
    coll = database._db["creator_invite_codes"]
    before = await coll.count_documents({})
    result = await coll.delete_many({"code": {"$nin": list(KEEP)}})
    after = await coll.count_documents({})
    remaining = await coll.find({}, {"_id": 0, "code": 1, "used": 1}).to_list(length=None)
    print(f"Before: {before} | Deleted: {result.deleted_count} | After: {after}")
    print(f"Remaining: {remaining}")
    await database.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
