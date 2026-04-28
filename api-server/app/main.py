import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import articles, auth, chat, events, health, llm, notifications, orders, presentation, ptmquant, rag, settings as settings_api, system
from app.config import get_settings
from app.core.database import engine, Base
from app.core.logging import setup_logging
from app.core.security import hash_password
from app.models import Notification, User

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


async def _add_index_if_missing(conn, table: str, index_name: str, columns: str) -> None:
    result = await conn.execute(text(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        f"AND TABLE_NAME = '{table}' AND INDEX_NAME = '{index_name}'"
    ))
    row = result.fetchone()
    if row and row[0] == 0:
        await conn.execute(text(f"ALTER TABLE `{table}` ADD INDEX `{index_name}` ({columns})"))
        logger.info(f"Migration: added index {table}.{index_name}")


async def _seed_system_settings(conn) -> None:
    """Insert default system settings if they don't exist yet (INSERT IGNORE)."""
    defaults = [
        # PTMQuant defaults
        ("PTMQUANT_DEFAULT_MEMORY_GB", "32",
         "PTMQuant 작업의 기본 Docker 메모리 제한 (GB). "
         "Phospho 패스는 fragment 인덱스만 ~15 GB 이상 필요하므로 32 GB 이상 권장.",
         "ptmquant", "integer"),
        ("PTMQUANT_DEFAULT_THREADS",   "4",
         "PTMQuant 작업의 기본 CPU 스레드 수 (0 = 전체 코어).",
         "ptmquant", "integer"),
        # RAG Enrichment tuning
        ("RAG_MAX_ARTICLES",         "3",    "PTM당 LLM에 전달할 최대 PubMed 논문 수 (배치 모드 기준)", "rag_enrichment", "integer"),
        ("RAG_ENABLE_KINASE",        "true", "키나제 예측 LLM 태스크 활성화 여부 (false로 설정 시 Phase B 속도 향상)", "rag_enrichment", "boolean"),
        ("RAG_ENABLE_FUNCTIONAL",    "true", "기능적 영향 분석 LLM 태스크 활성화 여부 (false로 설정 시 Phase B 속도 향상)", "rag_enrichment", "boolean"),
        ("RAG_ABSTRACT_BATCH_MODE",  "true", "여러 논문을 하나의 LLM 호출로 분석 (false: 논문당 1회 호출, 느림)", "rag_enrichment", "boolean"),
        ("RAG_ABSTRACT_MAX_TOKENS",  "4096", "Abstract 배치 분석 LLM 최대 출력 토큰 수 (줄이면 JSON 잘림 방지, 권장: 3000-4096)", "rag_enrichment", "integer"),
        ("RAG_KINASE_MAX_TOKENS",    "2000", "키나제 예측 LLM 최대 출력 토큰 수", "rag_enrichment", "integer"),
        ("RAG_FUNCTIONAL_MAX_TOKENS","3000", "기능적 영향 분석 LLM 최대 출력 토큰 수", "rag_enrichment", "integer"),
        ("RAG_PHASE_A_TIMEOUT",      "60",   "Phase A (외부 API: UniProt/KEGG/PubMed 등) 작업당 타임아웃 (초)", "rag_enrichment", "integer"),
        ("RAG_PHASE_B_TIMEOUT",      "120",  "Phase B (LLM: abstract/kinase/functional) 작업당 타임아웃 + 재시도 타임아웃 (초)", "rag_enrichment", "integer"),
    ]
    for key, value, desc, category, vtype in defaults:
        await conn.execute(text(
            "INSERT IGNORE INTO system_settings "
            "(setting_key, setting_value, description, category, value_type) "
            "VALUES (:k, :v, :d, :c, :t)"
        ), {"k": key, "v": value, "d": desc, "c": category, "t": vtype})


async def _run_migrations(conn) -> None:
    """Apply incremental schema changes that create_all won't handle."""
    await _seed_system_settings(conn)
    await _add_column_if_missing(
        conn, "users", "must_change_password",
        "must_change_password TINYINT(1) NOT NULL DEFAULT 0"
    )
    await _add_column_if_missing(
        conn, "users", "email_notifications_enabled",
        "email_notifications_enabled TINYINT(1) NOT NULL DEFAULT 1"
    )
    await _add_column_if_missing(
        conn, "orders", "run_by_user_id",
        "run_by_user_id INT NULL, ADD CONSTRAINT fk_orders_run_by FOREIGN KEY (run_by_user_id) REFERENCES users(id) ON DELETE SET NULL"
    )
    await _add_column_if_missing(
        conn, "orders", "secondary_ptm_type",
        "secondary_ptm_type VARCHAR(50) NULL"
    )
    await _add_column_if_missing(
        conn, "orders", "secondary_sample_config",
        "secondary_sample_config JSON NULL"
    )
    await _add_column_if_missing(
        conn, "orders", "kinase_analysis_data",
        "kinase_analysis_data JSON NULL"
    )
    # ptmquant_jobs: user_id FK (table created by create_all, this adds FK if missed)
    await _add_column_if_missing(
        conn, "ptmquant_jobs", "user_id",
        "user_id INT NULL, ADD CONSTRAINT fk_ptmquant_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL"
    )
    # ptmquant_jobs: enzyme / instrument / AlphaPeptDeep flags (v0.5.2)
    await _add_column_if_missing(
        conn, "ptmquant_jobs", "enzyme",
        "enzyme VARCHAR(32) NULL COMMENT 'Proteolytic enzyme (trypsin, lys-c, ...)'"
    )
    await _add_column_if_missing(
        conn, "ptmquant_jobs", "instrument",
        "instrument VARCHAR(32) NULL COMMENT 'Orbitrap preset (exploris_240, orbitrap_astral, ...)'"
    )
    await _add_column_if_missing(
        conn, "ptmquant_jobs", "predicted_library",
        "predicted_library TINYINT(1) NULL DEFAULT 0 COMMENT 'Enable AlphaPeptDeep predicted spectral library'"
    )
    await _add_column_if_missing(
        conn, "ptmquant_jobs", "transfer_learning",
        "transfer_learning TINYINT(1) NULL DEFAULT 0 COMMENT 'Fine-tune AlphaPeptDeep on pass-1 high-confidence PSMs'"
    )
    # phase_b_cache: PMID 목록 저장 컬럼 (subset matching v2)
    await _add_column_if_missing(
        conn, "phase_b_cache", "pmid_list",
        "pmid_list TEXT NULL COMMENT 'JSON array of sorted PMIDs for subset cache matching'"
    )
    # phase_b_cache: subset matching 쿼리 성능을 위한 복합 인덱스
    await _add_index_if_missing(
        conn, "phase_b_cache", "idx_phase_b_lookup",
        "gene, position, ptm_type, task_name"
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


_MYSQL_NON_RETRY_CODES = frozenset({1044, 1045, 1049, 1146})
_MYSQL_TRANSIENT_CODES = frozenset({2002, 2003, 2013})


def _is_transient_mysql_error(exc: OperationalError) -> bool:
    orig = exc.orig
    if orig is not None and getattr(orig, "args", None):
        code = orig.args[0]
        if isinstance(code, int):
            if code in _MYSQL_NON_RETRY_CODES:
                return False
            if code in _MYSQL_TRANSIENT_CODES:
                return True
    lowered = str(exc).lower()
    if "access denied" in lowered or "unknown database" in lowered:
        return False
    if "connection refused" in lowered or "can't connect" in lowered:
        return True
    return False


async def _run_database_startup() -> None:
    max_attempts = max(1, settings.DB_CONNECT_MAX_ATTEMPTS)
    delay = settings.DB_CONNECT_RETRY_INITIAL_SEC
    delay_max = settings.DB_CONNECT_RETRY_MAX_SEC

    for attempt in range(1, max_attempts + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                try:
                    await _run_migrations(conn)
                except Exception as e:
                    logger.warning(f"Migration note: {e}")
            logger.info("Database tables ensured")

            async with AsyncSession(engine) as session:
                await _seed_admin(session)
            return
        except OperationalError as e:
            if not _is_transient_mysql_error(e):
                raise
            if attempt >= max_attempts:
                logger.error("Database unavailable after %s attempts", max_attempts)
                raise
            logger.warning(
                "Database not ready (%s/%s): %s; retrying in %.1fs",
                attempt,
                max_attempts,
                e,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, delay_max)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PTM Analysis Platform API Server starting...")
    logger.info(f"Environment: {settings.APP_ENV}")
    logger.info(f"Auth enabled: {settings.AUTH_ENABLED}")

    await _run_database_startup()

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
app.include_router(notifications.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(rag.router, prefix="/api")
app.include_router(llm.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(articles.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(presentation.router, prefix="/api")
app.include_router(ptmquant.router, prefix="/api")
