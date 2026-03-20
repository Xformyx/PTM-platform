import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import articles, auth, events, health, llm, orders, rag, system
from app.config import get_settings
from app.core.database import engine, Base
from app.core.logging import setup_logging
from app.core.security import hash_password
from app.models.user import User

settings = get_settings()
logger = setup_logging()


async def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    result = await conn.execute(text(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        f"AND TABLE_NAME = '{table}' AND COLUMN_NAME = '{column}'"
    ))
    row = result.fetchone()
    if row and row[0] == 0:
        await conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN {definition}"))
        logger.info(f"Migration: added {table}.{column}")


async def _run_migrations(conn) -> None:
    """Apply incremental schema changes that create_all won't handle."""
    await _add_column_if_missing(
        conn, "users", "must_change_password",
        "must_change_password TINYINT(1) NOT NULL DEFAULT 0"
    )
    await _add_column_if_missing(
        conn, "orders", "run_by_user_id",
        "run_by_user_id INT NULL, ADD CONSTRAINT fk_orders_run_by FOREIGN KEY (run_by_user_id) REFERENCES users(id) ON DELETE SET NULL"
    )


async def _seed_admin(session: AsyncSession) -> None:
    """Create a default admin user if no users exist."""
    result = await session.execute(select(User).limit(1))
    if result.scalar_one_or_none() is not None:
        return
    admin = User(
        email="admin@ptm.local",
        password_hash=hash_password("admin1234"),
        name="Admin",
        role="admin",
        must_change_password=False,
    )
    session.add(admin)
    await session.commit()
    logger.info("Created default admin user: admin@ptm.local / admin1234")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PTM Analysis Platform API Server starting...")
    logger.info(f"Environment: {settings.APP_ENV}")
    logger.info(f"Auth enabled: {settings.AUTH_ENABLED}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await _run_migrations(conn)
        except Exception as e:
            logger.warning(f"Migration note: {e}")
    logger.info("Database tables ensured")

    async with AsyncSession(engine) as session:
        await _seed_admin(session)

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
app.include_router(auth.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(rag.router, prefix="/api")
app.include_router(llm.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(articles.router, prefix="/api")
