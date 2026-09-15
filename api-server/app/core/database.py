from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# SQLite is used only by isolated tests and does not accept QueuePool sizing
# arguments. The production MySQL connection retains its existing pool policy.
_engine_options = {
    "echo": settings.DEBUG,
    "pool_recycle": 3600,
    "pool_pre_ping": True,
}
if not str(settings.DATABASE_URL).startswith("sqlite"):
    _engine_options.update({"pool_size": 20, "max_overflow": 10})

engine = create_async_engine(settings.DATABASE_URL, **_engine_options)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
