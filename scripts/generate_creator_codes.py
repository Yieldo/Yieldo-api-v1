"""Generate N unique creator invite codes, write them to MongoDB, and dump
them to a CSV file for distribution.

One-time use is enforced by `database.add_invite_codes()` + `consume_invite_code()`:
  - Each row defaults to `used: False`
  - Once a creator applies with the code, `consume_invite_code()` marks it
    `used: True` with the redeemer's wallet address; subsequent attempts fail.

Usage (on the API VPS):
  cd /home/elliot37/Yieldo-api-v1
  source .env
  ./venv/bin/python scripts/generate_creator_codes.py 100

  # codes printed to stdout AND saved to scripts/creator_codes_<timestamp>.csv
"""
import asyncio
import os
import secrets
import sys
from datetime import datetime

from app.services import database
from app.config import get_settings


# Alphabet that avoids confusable characters (0/O, 1/I/l) so codes are
# easy to read aloud, type from a paper sticky note, and copy without typos.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10  # 32^10 ≈ 1.1 × 10^15 — collision probability for 100 codes is ~5e-12
PREFIX = "YDO-"   # Branded so creators know it's legit


def gen_code() -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    # Insert a hyphen halfway through for readability: YDO-XXXXX-YYYYY
    half = CODE_LENGTH // 2
    return f"{PREFIX}{body[:half]}-{body[half:]}"


async def main(n: int):
    settings = get_settings()
    uri = settings.mongodb_url or os.environ.get("MONGODB_URL") or os.environ.get("mongodb_url")
    if not uri:
        print("ERROR: MONGODB_URL not set in environment")
        sys.exit(1)
    await database.connect(uri)

    # Generate locally-unique codes (paranoid — collision is astronomically
    # unlikely but the dedup is free).
    seen = set()
    codes = []
    while len(codes) < n:
        c = gen_code()
        if c in seen:
            continue
        seen.add(c)
        codes.append(c)

    inserted = await database.add_invite_codes(codes, note=f"batch-{datetime.now().strftime('%Y%m%d')}")
    await database.disconnect()

    # Persist a CSV so the codes survive even if the user closes the terminal.
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"creator_codes_{ts}.csv")
    with open(out_path, "w") as f:
        f.write("code,used,batch\n")
        for c in codes:
            f.write(f"{c},false,batch-{ts}\n")

    print(f"\n=== Generated {len(codes)} codes — {inserted} written to DB ===\n")
    for c in codes:
        print(c)
    print(f"\nSaved to: {out_path}")
    print("Each code is single-use; redemption marks it consumed in `creator_invite_codes`.")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    asyncio.run(main(n))
