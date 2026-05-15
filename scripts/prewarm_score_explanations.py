#!/usr/bin/env python3
"""Pre-warm the AI sub-score explanation cache for today.

Iterates every vault that has a recent score_snapshot, generates an
explanation for each of the 4 dimensions (capital/performance/risk/trust),
and writes the result to the `score_explanations` cache so user-facing
requests are guaranteed to hit the cache instead of triggering a fresh
Claude CLI call.

Pacing: 2 seconds between CLI invocations. With ~100 vaults × 4 dimensions
that's ~13 minutes total — gentle enough to never approach the Max plan's
per-5h ceiling.

Cron entry (run on the VPS as elliot37, after score_snapshots have settled):
    15 2 * * * /home/elliot37/Yieldo-api-v1/venv/bin/python -m scripts.prewarm_score_explanations >> /home/elliot37/Yieldo-api-v1/logs/prewarm.log 2>&1

The script uses a file lock so an overlapping run (e.g. cron fired while the
last one is still going) silently exits instead of doubling CLI load.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make `app.*` imports work when invoked as a module from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.services import database  # noqa: E402
from app.services import score_explainer  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("prewarm")

DIMENSIONS = ("capital", "performance", "risk", "trust")
PACE_SECONDS = 2.0
# Only pre-warm vaults that have a snapshot in the last 48h — older ones are
# either deprecated or have indexer issues; the explainer would fall back to
# template anyway, which the cron would just bake into the cache.
SNAPSHOT_FRESHNESS_HOURS = 48

LOCK_PATH = Path("/tmp/yieldo_prewarm_explanations.lock")


async def _list_active_vaults(indexer_db) -> list[str]:
    """Return a deduped list of vault_ids that have a score_snapshot newer
    than `SNAPSHOT_FRESHNESS_HOURS`. Order is stable: newest snapshot first
    so the most-likely-to-be-viewed vaults get pre-warmed first."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=SNAPSHOT_FRESHNESS_HOURS)
    pipeline = [
        {"$match": {"ts": {"$gte": cutoff}}},
        {"$group": {"_id": "$vault_id", "ts": {"$max": "$ts"}}},
        {"$sort": {"ts": -1}},
    ]
    rows = await indexer_db["score_snapshots"].aggregate(pipeline).to_list(length=None)
    return [r["_id"] for r in rows if r.get("_id")]


def _acquire_lock() -> bool:
    """Atomic-ish lock so overlapping cron runs don't double up. Cheap
    O_EXCL trick — race window is microseconds and the worst case is one
    extra run, which the script handles fine."""
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            mtime = LOCK_PATH.stat().st_mtime
            age_sec = time.time() - mtime
            # If the lock is stale (>4h old — way longer than a normal run),
            # take it over.
            if age_sec > 4 * 3600:
                logger.warning("Stale lock (%.0fs old) — taking it over", age_sec)
                LOCK_PATH.unlink(missing_ok=True)
                return _acquire_lock()
        except FileNotFoundError:
            return _acquire_lock()
        return False


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("Failed to release lock: %s", e)


async def _warm_one(vault_id: str, dimension: str, dry_run: bool) -> str:
    """Returns one of: 'cached', 'generated', 'template', 'error'."""
    try:
        cached = await score_explainer.check_cache(vault_id, dimension)
    except Exception as e:
        logger.warning("check_cache failed %s/%s: %s", vault_id, dimension, e)
        return "error"
    if cached is not None:
        return "cached"
    if dry_run:
        return "would-generate"
    try:
        out = await score_explainer.generate_fresh(vault_id, dimension)
        return "generated" if out.get("source") == "claude_cli" else "template"
    except LookupError:
        # Vault disappeared between aggregation and generation — fine.
        return "error"
    except Exception as e:
        logger.warning("generate_fresh failed %s/%s: %s", vault_id, dimension, e)
        return "error"


async def main(dry_run: bool, limit: int | None) -> int:
    if not _acquire_lock():
        logger.info("Another prewarm run is already in progress — exiting")
        return 0
    try:
        settings = get_settings()
        if not settings.mongodb_url:
            logger.error("MONGODB_URL is not configured")
            return 2
        await database.connect(
            settings.mongodb_url,
            settings.indexer_mongodb_url or None,
        )
        indexer_db = database.get_indexer_db()
        if indexer_db is None:
            logger.error("Indexer DB unavailable — cannot list vaults")
            return 2

        vault_ids = await _list_active_vaults(indexer_db)
        if limit is not None:
            vault_ids = vault_ids[:limit]
        logger.info("Pre-warming %d vaults × %d dimensions", len(vault_ids), len(DIMENSIONS))

        counts = {"cached": 0, "generated": 0, "template": 0, "error": 0, "would-generate": 0}
        t0 = time.time()
        for i, vid in enumerate(vault_ids, 1):
            for dim in DIMENSIONS:
                result = await _warm_one(vid, dim, dry_run)
                counts[result] = counts.get(result, 0) + 1
                # Pace only when we actually fired a CLI call; cache hits
                # don't need a delay.
                if result in ("generated", "template"):
                    await asyncio.sleep(PACE_SECONDS)
            if i % 10 == 0:
                logger.info(
                    "  ... %d/%d vaults — gen=%d cached=%d tmpl=%d err=%d",
                    i, len(vault_ids),
                    counts["generated"], counts["cached"], counts["template"], counts["error"],
                )

        dt = time.time() - t0
        logger.info(
            "Done in %.1fs — generated=%d cached=%d template=%d errors=%d would_generate=%d",
            dt, counts["generated"], counts["cached"], counts["template"],
            counts["error"], counts["would-generate"],
        )
        return 0
    finally:
        await database.disconnect()
        _release_lock()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pre-warm score-explanation cache")
    ap.add_argument("--dry-run", action="store_true",
                    help="Walk vaults and report what would be generated; no CLI calls.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Optional cap on number of vaults (smoke-test runs).")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run, limit=args.limit)))
