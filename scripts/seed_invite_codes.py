"""Seed an initial batch of Creator invite codes. Run once.

Usage:
    venv/Scripts/python.exe scripts/seed_invite_codes.py
"""
import asyncio
import os
from app.services import database
from app.config import get_settings


SEED_CODES = [
    "YIELDO2026",
    "MORPHO",
    "MIDAS",
    "EARLY",
    "HYPERBEAT",
    "LAGOON",
    "VEDA",
    "GAUNTLET",
    "STEAKHOUSE",
    "FOUNDING01",
    "FOUNDING02",
    "FOUNDING03",
]


async def main():
    settings = get_settings()
    if not settings.mongodb_url:
        print("MONGODB_URL not set")
        return
    await database.connect(settings.mongodb_url)
    inserted = await database.add_invite_codes(SEED_CODES, note="initial seed")
    print(f"Inserted {inserted} new invite codes (duplicates ignored)")
    await database.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
