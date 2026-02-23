import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import articles, events, health, llm, orders, rag, system
from app.config import get_settings
from app.core.database import engine, Base
from app.core.logging import setup_logging

settings = get_settings()
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PTM Analysis Platform API Server starting...")
    logger.info(f"Environment: {settings.APP_ENV}")
    logger.info(f"Auth enabled: {settings.AUTH_ENABLED}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured")

    yield

    await engine.dispose()
    logger.info("API Server shutting down")


app = FastAPI(
    title="PTM Analysis Platform",
    description="Protein Post-Translational Modification Analysis Platform API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else ["http://localhost", "https://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(rag.router, prefix="/api")
app.include_router(llm.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(articles.router, prefix="/api")
