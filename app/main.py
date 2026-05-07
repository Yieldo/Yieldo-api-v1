from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from app.routes import vaults, quote, status, info, partners, kols, deposits, users, withdraw, positions, scores, intel, applications, admin
from app.services.vault import load_vaults, get_all_vaults_raw, start_registry_audit_thread
from app.services import database, min_deposit, status_resolver, withdraw_resolver
from app.config import get_settings
import asyncio


# Edge-cache hints — Cloudflare honors `Cache-Control` with `s-maxage` to
# cache origin responses without us having to set up cache rules in their UI.
# Each entry is (path-prefix, s-maxage-secs, swr-secs).
#
# Tuning:
# - Read-heavy public endpoints get short s-maxage so admin toggles + new
#   indexer data still propagate within a tight window.
# - Score-history is mostly historical → can cache longer.
# - Mutating endpoints (POST/PATCH) and user-specific paths (positions,
#   deposits, withdraw, admin/me/vaults) NEVER get cached — they bypass.
_EDGE_CACHE_RULES = (
    # (prefix, s-maxage, stale-while-revalidate)
    ("/v1/vaults",            30,  60),    # list + detail; admin toggles propagate ≤30s
    ("/v1/intel/feed",        30,  60),
    ("/v1/intel/high",        30,  60),
    ("/v1/intel/notable",     30,  60),
    ("/v1/intel/activity",    30,  60),
    ("/v1/scores/history",   120, 300),    # historical; safely cacheable longer
    ("/v1/scores/timeseries",120, 300),
    ("/v1/scores/leaderboard",60, 120),
    ("/v1/scores/movers",     60, 120),
    ("/health",              300, 300),    # static {"status":"ok"} — cache hard
)
# Path prefixes that must NEVER be edge-cached (user-specific or mutates state).
_NO_CACHE_PREFIXES = (
    "/v1/admin",
    "/v1/quote",
    "/v1/withdraw",
    "/v1/positions",
    "/v1/deposits",
    "/v1/users",
    "/v1/applications",
    "/v1/kols",
    "/v1/creators",
    "/v1/partners",
    "/v1/status",
)


class EdgeCacheMiddleware(BaseHTTPMiddleware):
    """Tags safe GET responses with Cache-Control so Cloudflare can cache
    them at the edge. Per-request profile observed: a `/health` round-trip
    is 235ms cold-network even though the handler is 2ms locally — the
    network IS the slowness. Edge caching on read-heavy endpoints means
    most user requests skip the origin entirely.
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Only cache idempotent GETs with successful payloads.
        if request.method != "GET" or response.status_code != 200:
            return response
        path = request.url.path
        # Auth-bearing requests are user-specific; never cache.
        if request.headers.get("authorization"):
            return response
        # Explicit no-cache prefixes win over any rule below.
        for p in _NO_CACHE_PREFIXES:
            if path.startswith(p):
                response.headers.setdefault("Cache-Control", "no-store")
                return response
        # Apply the longest matching prefix rule.
        match = None
        for prefix, s_maxage, swr in _EDGE_CACHE_RULES:
            if path.startswith(prefix) and (match is None or len(prefix) > len(match[0])):
                match = (prefix, s_maxage, swr)
        if match:
            _, s_maxage, swr = match
            # public + s-maxage means: browsers may not cache (no max-age),
            # but Cloudflare WILL cache for s-maxage seconds. SWR lets stale
            # responses serve while a background fetch refreshes.
            response.headers["Cache-Control"] = f"public, s-maxage={s_maxage}, stale-while-revalidate={swr}"
            response.headers["Vary"] = "Accept-Encoding"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_vaults()
    # Diff vaults.json vs the public/indexer registry so address drift surfaces
    # in logs the moment the API boots — instead of when a user hits "Deposit"
    # and gets "Vault not found".
    start_registry_audit_thread()
    # Warm the per-vault min-deposit cache in parallel so the first /v1/vaults
    # response doesn't pay the 87-RPC cold-start. Runs in a background thread
    # so it doesn't block startup if RPCs are slow.
    import threading
    threading.Thread(
        target=min_deposit.warm_cache,
        args=(get_all_vaults_raw(),),
        daemon=True,
    ).start()
    settings = get_settings()
    if settings.mongodb_url:
        await database.connect(settings.mongodb_url, settings.indexer_mongodb_url or None)
        # Backfill ref_codes for any existing users that predate the feature.
        try:
            await database.backfill_user_ref_codes()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"ref_code backfill failed: {e}")
        # Seed user docs for historical depositors who never did SIWE login,
        # so every address in `transactions` has a matching `users` row.
        try:
            await database.backfill_users_from_transactions()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"users-from-txs backfill failed: {e}")
        # Background loop that converges every pending tx (any vault, any chain,
        # any flow) to its real status within ~60s — independent of frontend
        # polling. Without this, a user who closes the tab between sending and
        # mining sees "Pending" forever.
        resolver_task = asyncio.create_task(status_resolver.run_loop())
        withdraw_resolver_task = asyncio.create_task(withdraw_resolver.run_loop())
    else:
        resolver_task = None
        withdraw_resolver_task = None
    yield
    if resolver_task:
        resolver_task.cancel()
    if withdraw_resolver_task:
        withdraw_resolver_task.cancel()
    await database.disconnect()


app = FastAPI(
    title="Yieldo API",
    description="Cross-chain deposit aggregator for ERC-4626 and custom yield vaults",
    version="1.0.0",
    lifespan=lifespan,
    servers=[
        {"url": "https://api.yieldo.xyz", "description": "Production"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(EdgeCacheMiddleware)

app.include_router(vaults.router)
app.include_router(quote.router)
app.include_router(status.router)
app.include_router(info.router)
app.include_router(partners.router)
app.include_router(kols.router, prefix="/v1/creators", tags=["creators"])
app.include_router(kols.router, prefix="/v1/kols", tags=["kols"], include_in_schema=False)
app.include_router(deposits.router)
app.include_router(users.router)
app.include_router(withdraw.router)
app.include_router(positions.router)
app.include_router(scores.router)
app.include_router(intel.router)
app.include_router(applications.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
