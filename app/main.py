from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import vaults, quote, status, info, partners
from app.services.vault import load_vaults
from app.services import database
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_vaults()
    settings = get_settings()
    if settings.mongodb_url:
        await database.connect(settings.mongodb_url)
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


@app.get("/health")
async def health():
    return {"status": "ok"}
