"""Clear ALL old wallet/creator application records.

Deletes from both:
  - `creator_applications` (legacy collection from /v1/creators/apply)
  - `applications` (new unified collection — wallet + creator)

Use case: starting fresh after switching to the new SIWE-gated flow. Test
entries and pre-flow applications are wiped so the review queue is clean.

Usage:
    venv/Scripts/python.exe scripts/clear_old_applications.py
"""
import asyncio
from app.services import database
from app.config import get_settings


async def main():
    settings = get_settings()
    if not settings.mongodb_url:
        print("MONGODB_URL not set")
        return
    await database.connect(settings.mongodb_url)

    legacy_count = await database._db["creator_applications"].count_documents({})
    new_count = await database._db["applications"].count_documents({})

    print(f"Before:")
    print(f"  legacy creator_applications: {legacy_count}")
    print(f"  new applications:            {new_count}")

    if legacy_count == 0 and new_count == 0:
        print("\nNothing to delete. Done.")
        await database.disconnect()
        return

    r1 = await database._db["creator_applications"].delete_many({})
    r2 = await database._db["applications"].delete_many({})

    print(f"\nDeleted:")
    print(f"  creator_applications: {r1.deleted_count}")
    print(f"  applications:         {r2.deleted_count}")

    print(f"\nAfter:")
    print(f"  legacy creator_applications: {await database._db['creator_applications'].count_documents({})}")
    print(f"  new applications:            {await database._db['applications'].count_documents({})}")

    await database.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
