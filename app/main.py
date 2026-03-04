from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import vaults, quote, status, info
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
    description="Deposit into Morpho vaults from any chain/token via LiFi",
    version="1.0.0",
    lifespan=lifespan,
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


@app.get("/health")
async def health():
    return {"status": "ok"}
