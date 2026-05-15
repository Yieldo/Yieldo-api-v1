"""AI-generated plain-English explanation of why a vault has its sub-score.

Pulls the latest score_snapshots row from the indexer DB, extracts the metrics
that drive a given dimension (capital / performance / risk / trust), and asks
the local `claude` CLI (Claude Code, non-interactive) for a 1-2 sentence
explanation a non-technical user can read.

Caches per (vault_id, dimension, day_key) in the wallets DB so each unique
(vault, dimension, day) costs at most one CLI invocation. TTL'd to 14 days.

Uses the same `claude` CLI pattern as scripts/run_validator.py on the indexer
box — no Anthropic API key needed; the CLI is authenticated via the Pro/Max
subscription on the host.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import database

logger = logging.getLogger(__name__)

# How long we let the CLI think. Haiku is fast for ~60-word summaries — keep
# this tight so a stuck call doesn't park a uvicorn worker.
CLAUDE_TIMEOUT_SEC = 45

# Cached on first lookup. The CLI lives under ~/.local/bin on the AWS box;
# `which` won't find it inside systemd's minimal PATH so we hand-search the
# usual locations (mirrors run_validator.py's resolution).
_CLAUDE_BIN: Optional[str] = None


def _resolve_claude_bin() -> Optional[str]:
    global _CLAUDE_BIN
    if _CLAUDE_BIN:
        return _CLAUDE_BIN
    found = shutil.which("claude")
    if not found:
        for candidate in (
            os.path.expanduser("~/.local/bin/claude"),
            "/usr/local/bin/claude",
            "/opt/claude/bin/claude",
            "/home/elliot37/.local/bin/claude",
        ):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                found = candidate
                break
    _CLAUDE_BIN = found
    return _CLAUDE_BIN


# Pulled by dimension. Each entry lists (snapshot_path, human_label, fmt).
# snapshot_path is a dotted lookup into the score_snapshots doc; "metrics.X"
# reads from the metrics subdoc, anything else is top-level.
_DIM_FIELDS: dict[str, list[tuple[str, str, str]]] = {
    "capital": [
        ("metrics.C01_USD",  "TVL (USD)",            "money"),
        # C02_* and P08_* are stored as already-scaled percentages in the
        # snapshot (e.g. -1.04 means -1.04%), matching how the UI renders
        # them. P04 is the exception — it's a fraction (0.05 = 5%), so it
        # uses "pct" which multiplies by 100.
        ("metrics.C02_1d",   "TVL change 24h",       "pct_raw"),
        ("metrics.C02_7d",   "TVL change 7d",        "pct_raw"),
        ("metrics.C02_30d",  "TVL change 30d",       "pct_raw"),
        ("metrics.R09_top1", "Top-1 holder share",   "pct_raw"),
        ("metrics.R09_top5", "Top-5 holder share",   "pct_raw"),
        ("metrics.C07",      "Deposit type",         "passthrough"),
    ],
    "performance": [
        ("metrics.net_apy",       "Current net APY",         "pct_raw"),
        ("metrics.P01_7d",        "APY 7d avg",              "pct_raw"),
        ("metrics.P01_30d",       "APY 30d avg",             "pct_raw"),
        ("metrics.benchmark_apy", "Benchmark APY (Aave)",    "pct_raw"),
        ("metrics.P03_7d",        "APY vs benchmark (7d)",   "ratio"),
        ("metrics.P04_30d",       "APY volatility 30d",      "pct"),       # fraction (UI multiplies by 100)
        ("metrics.P08_30d",       "Max drawdown 30d",        "pct_raw"),    # already-scaled %
        ("metrics.P05",           "Sharpe ratio",            "float"),
        ("metrics.P13",           "Yield type",              "passthrough"),
    ],
    "risk": [
        ("metrics.R09_top1", "Top-1 holder share",      "pct_raw"),
        ("metrics.R09_top5", "Top-5 holder share",      "pct_raw"),
        ("metrics.C07",      "Withdrawal latency",      "passthrough"),
        ("metrics.P08_30d",  "Max drawdown 30d",        "pct_raw"),   # already-scaled %
        ("metrics.P08_90d",  "Max drawdown 90d",        "pct_raw"),   # already-scaled %
    ],
    "trust": [
        ("metrics.T01_30d",  "Capital retention 30d",   "pct_raw"),
        ("metrics.T01_365d", "Capital retention 365d",  "pct_raw"),
        ("metrics.T04",      "Avg holding period (d)",  "float"),
        ("metrics.T07",      "Holders 90d (ratio)",     "float"),
        ("metrics.T11",      "Net flow 30d",            "pct_raw"),
    ],
}

_DIM_TO_SCORE_KEY = {
    "capital": "capital_score",
    "performance": "performance_score",
    "risk": "risk_score",
    "trust": "trust_score",
}

_DIM_LABEL = {"capital": "Capital", "performance": "Performance", "risk": "Risk", "trust": "Trust"}


def _lookup(doc: dict, dotted: str) -> Any:
    cur: Any = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _fmt_value(v: Any, kind: str) -> str:
    if v is None or v == "":
        return "n/a"
    try:
        if kind == "money":
            x = float(v)
            if x >= 1e9: return f"${x/1e9:.2f}B"
            if x >= 1e6: return f"${x/1e6:.2f}M"
            if x >= 1e3: return f"${x/1e3:.1f}K"
            return f"${x:.0f}"
        if kind == "pct":
            return f"{float(v) * 100:.2f}%"
        if kind == "pct_raw":
            return f"{float(v):.2f}%"
        if kind == "ratio":
            return f"{float(v):.2f}x"
        if kind == "float":
            return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)
    return str(v)


def _build_context(snapshot: dict, dimension: str) -> tuple[str, dict[str, Any]]:
    """Returns (human-readable bullet list, raw values dict). The list goes into
    the prompt verbatim; the dict is returned alongside the explanation so
    callers can audit what the AI was shown."""
    rows: list[str] = []
    raw: dict[str, Any] = {}
    for path, label, kind in _DIM_FIELDS.get(dimension, []):
        v = _lookup(snapshot, path)
        raw[label] = v
        rows.append(f"- {label}: {_fmt_value(v, kind)}")
    flags = snapshot.get("active_flags") or []
    if flags:
        flag_labels = [
            f.get("label") or f.get("rule_id") or "flag"
            for f in flags if isinstance(f, dict)
        ]
        rows.append("- Active flags: " + ", ".join(flag_labels[:6]))
        raw["Active flags"] = flag_labels
    return "\n".join(rows), raw


def _template_fallback(vault_name: str, dimension: str, score: Optional[int], ctx_text: str) -> str:
    """Used when the `claude` CLI isn't reachable. Honest, no fake AI."""
    s = f"{score}/100" if score is not None else "n/a"
    return (
        f"{_DIM_LABEL[dimension]} score: {s}. "
        f"Driven by the metrics below — AI explanation unavailable right now."
    )


async def _call_claude_cli(vault_name: str, dimension: str, score: Optional[int], ctx_text: str) -> Optional[str]:
    """Invoke the local `claude` CLI in non-interactive mode and return the
    generated text. Returns None on missing binary, timeout, or non-zero exit.
    """
    cli = _resolve_claude_bin()
    if not cli:
        logger.warning("`claude` CLI not found on PATH; falling back to template")
        return None

    dim_label = _DIM_LABEL[dimension]
    score_str = f"{score}/100" if score is not None else "n/a"

    prompt = (
        "You are summarizing a DeFi vault's sub-score for retail users.\n"
        "Write exactly 1-2 short sentences in plain English (max ~60 words).\n"
        "Be concrete: cite the specific metric and number that most drives the score.\n"
        "Never invent numbers — only use what's provided below.\n"
        "If the score is low, lead with the worst-performing metric.\n"
        "If the score is high, lead with what the vault did well.\n"
        "Output ONLY the explanation text. No greetings, no markdown, no preamble, no quotes.\n\n"
        f"Vault: {vault_name}\n"
        f"Dimension: {dim_label} ({score_str})\n"
        f"Latest metrics:\n{ctx_text}\n\n"
        f"Explain why this vault has a {score_str} on {dim_label}."
    )

    # Lock the CLI down hard since it's reachable via a public HTTP endpoint:
    #   - `--tools ""` disables every tool (no Bash/Edit/WebFetch/etc) per the
    #     CLI's own help: 'Use "" to disable all tools'. The only thing the
    #     model can do is emit text.
    #   - We deliberately do NOT pass `--permission-mode bypassPermissions`:
    #     with no tools available there's nothing to permission-prompt about,
    #     and skipping the bypass means we never grant the CLI authority to
    #     run side-effectful actions on its own.
    #   - Prompt is sent via stdin (not as a positional arg) because
    #     `--allowed-tools` / `--disallowed-tools` / `--tools` are variadic
    #     ("<tools...>") and will gobble any positional argument that follows
    #     until the next flag — so a positional prompt would get swallowed
    #     and the CLI would error with "Input must be provided either through
    #     stdin or as a prompt argument".
    cmd = [
        cli,
        "--print",
        "--output-format", "text",
        "--model", "haiku",
        "--tools", "",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=CLAUDE_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            logger.warning("claude CLI timed out for %s/%s", vault_name, dimension)
            return None
    except Exception as e:
        logger.warning("claude CLI launch failed for %s/%s: %s", vault_name, dimension, e)
        return None

    if proc.returncode != 0:
        logger.warning(
            "claude CLI returned %s for %s/%s: %s",
            proc.returncode, vault_name, dimension, (stderr or b"")[:300].decode("utf-8", "replace"),
        )
        return None

    text = (stdout or b"").decode("utf-8", "replace").strip()
    # Strip surrounding quotes the model sometimes adds despite the instruction.
    if len(text) >= 2 and text[0] in ("\"", "'") and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text or None


def _day_key(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")


async def check_cache(vault_id: str, dimension: str) -> Optional[dict]:
    """Return the cached row if one exists for today, else None. Cheap — a
    single Mongo `find_one` keyed by composite _id. Routes call this before
    deciding whether a request needs to be rate-limited."""
    dimension = (dimension or "").lower()
    if dimension not in _DIM_FIELDS:
        raise ValueError(f"Unknown dimension: {dimension}")
    wallets_db = database.get_db() if hasattr(database, "get_db") else None
    if wallets_db is None:
        wallets_db = getattr(database, "_db", None)
    if wallets_db is None:
        return None
    cache_id = f"{vault_id}:{dimension}:{_day_key()}"
    existing = await wallets_db["score_explanations"].find_one({"_id": cache_id})
    if existing and existing.get("explanation"):
        return {
            "vault_id": vault_id,
            "dimension": dimension,
            "score": existing.get("score"),
            "explanation": existing["explanation"],
            "generated_at": existing.get("generated_at"),
            "cached": True,
            "source": existing.get("source", "cache"),
        }
    return None


async def generate_fresh(vault_id: str, dimension: str) -> dict:
    """Generate (or regenerate) the explanation for today, ignoring cache.
    Writes through to the cache on success/failure. Caller is responsible
    for rate-limiting before invoking this — every call costs one CLI run.

    Raises ValueError on bad dimension, LookupError if no snapshot exists,
    RuntimeError if the indexer DB is unreachable.
    """
    dimension = (dimension or "").lower()
    if dimension not in _DIM_FIELDS:
        raise ValueError(f"Unknown dimension: {dimension}")

    indexer_db = database.get_indexer_db()
    if indexer_db is None:
        raise RuntimeError("Indexer DB not connected")
    wallets_db = database.get_db() if hasattr(database, "get_db") else None
    if wallets_db is None:
        wallets_db = getattr(database, "_db", None)

    snapshot = await indexer_db["score_snapshots"].find_one(
        {"vault_id": vault_id}, sort=[("ts", -1)]
    )
    if not snapshot:
        raise LookupError(f"No score snapshot for {vault_id}")

    score = snapshot.get(_DIM_TO_SCORE_KEY[dimension])
    try:
        score = int(round(float(score))) if score is not None else None
    except (TypeError, ValueError):
        score = None
    vault_name = snapshot.get("name") or vault_id
    ctx_text, _ = _build_context(snapshot, dimension)

    explanation = await _call_claude_cli(vault_name, dimension, score, ctx_text)
    source = "claude_cli" if explanation else "template"
    if not explanation:
        explanation = _template_fallback(vault_name, dimension, score, ctx_text)

    now = datetime.now(timezone.utc)
    day_key = _day_key(now)
    cache_id = f"{vault_id}:{dimension}:{day_key}"
    doc = {
        "_id": cache_id,
        "vault_id": vault_id,
        "dimension": dimension,
        "day_key": day_key,
        "score": score,
        "explanation": explanation,
        "source": source,
        "generated_at": now,
    }
    if wallets_db is not None:
        try:
            await wallets_db["score_explanations"].update_one(
                {"_id": cache_id}, {"$set": doc}, upsert=True
            )
        except Exception as e:
            logger.warning("Failed to cache explanation %s: %s", cache_id, e)

    return {
        "vault_id": vault_id,
        "dimension": dimension,
        "score": score,
        "explanation": explanation,
        "generated_at": now,
        "cached": False,
        "source": source,
    }


async def get_or_generate(vault_id: str, dimension: str) -> dict:
    """Convenience wrapper: cache-or-generate without rate-limiting. Use
    `check_cache` + `generate_fresh` directly from request handlers so the
    rate limiter can run between them."""
    cached = await check_cache(vault_id, dimension)
    if cached is not None:
        return cached
    return await generate_fresh(vault_id, dimension)
