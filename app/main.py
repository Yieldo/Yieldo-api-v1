from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import vaults, quote, status, info, partners, kols, deposits, users, withdraw, positions
from app.services.vault import load_vaults, get_all_vaults_raw
from app.services import database, min_deposit
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_vaults()
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
        await database.connect(settings.mongodb_url)
        # Backfill ref_codes for any existing users that predate the feature.
        try:
            await database.backfill_user_ref_codes()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"ref_code backfill failed: {e}")
    yield
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


@app.get("/health")
async def health():
    return {"status": "ok"}
