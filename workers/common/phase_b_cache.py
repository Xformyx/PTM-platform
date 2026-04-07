"""
Persistent cache for Phase B LLM sub-task results.

캐시 키: MD5(gene__position__ptm_type__task_name__pmid_hash)
 - pmid_hash : MD5(sorted PMID 목록을 쉼표로 이은 문자열)
 - task_name : abstract | kinase | functional | fulltext | validation | regulation

데이터베이스는 workers/common/db_update.py 와 동일한 MySQL 연결을 사용한다 (raw pymysql).
캐시 실패는 항상 silently ignore — 캐시가 없어도 파이프라인은 정상 동작한다.
"""

import hashlib
import json
import logging
import os

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+asyncmy://ptm_user:ptm_password@localhost:3306/ptm_platform",
)
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncmy", "+pymysql").replace("+aiomysql", "+pymysql")

# 캐시 유효 기간 (일). 0 이면 만료 체크 없음.
CACHE_TTL_DAYS: int = int(os.getenv("PHASE_B_CACHE_TTL_DAYS", "30"))


_ENGINE = None
_ENGINE_LOCK = __import__("threading").Lock()


def _engine():
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = create_engine(
                    SYNC_DATABASE_URL,
                    pool_pre_ping=True,
                    pool_size=2,
                    max_overflow=3,
                    pool_recycle=600,
                )
    return _ENGINE


# ──────────────────────────────────────────────────────────────────────────────
# 키 생성 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

def _pmid_hash(pmids: list) -> str:
    """PMIDs 목록을 정렬·연결한 MD5 (16자리)."""
    joined = ",".join(sorted(str(p) for p in pmids if p))
    return hashlib.md5(joined.encode()).hexdigest()[:16]


def make_cache_key(gene: str, position: str, ptm_type: str, task_name: str, pmids: list) -> str:
    ph = _pmid_hash(pmids)
    raw = f"{gene}__{position}__{ptm_type}__{task_name}__{ph}"
    return hashlib.md5(raw.encode()).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────────────────

def get_cached(gene: str, position: str, ptm_type: str, task_name: str, pmids: list) -> dict | None:
    """
    캐시에서 결과를 조회한다.
    캐시 미스 또는 오류 시 None 반환.
    """
    key = make_cache_key(gene, position, ptm_type, task_name, pmids)
    try:
        engine = _engine()
        ttl_clause = ""
        params: dict = {"key": key}
        if CACHE_TTL_DAYS > 0:
            ttl_clause = " AND updated_at >= DATE_SUB(NOW(), INTERVAL :ttl DAY)"
            params["ttl"] = CACHE_TTL_DAYS

        sql = text(f"SELECT result_json FROM phase_b_cache WHERE cache_key = :key{ttl_clause} LIMIT 1")
        with engine.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        if row:
            result = json.loads(row[0])
            logger.debug(f"[PhaseB-Cache HIT] {gene} {position} / {task_name} (key={key[:8]}…)")
            return result
        return None
    except Exception as e:
        logger.debug(f"[PhaseB-Cache] get failed ({gene}/{task_name}): {e}")
        return None


def set_cached(gene: str, position: str, ptm_type: str, task_name: str, pmids: list, result: dict) -> None:
    """
    결과를 캐시에 저장한다. 이미 있으면 갱신.
    빈 결과({})는 저장하지 않는다.
    """
    if not result:
        return
    key = make_cache_key(gene, position, ptm_type, task_name, pmids)
    try:
        ph = _pmid_hash(pmids)
        result_json = json.dumps(result, ensure_ascii=False, default=str)
        engine = _engine()
        sql = text(
            "INSERT INTO phase_b_cache "
            "  (cache_key, gene, position, ptm_type, task_name, pmid_hash, result_json) "
            "VALUES "
            "  (:key, :gene, :pos, :ptm_type, :task, :pmid_hash, :result_json) "
            "ON DUPLICATE KEY UPDATE "
            "  result_json = VALUES(result_json), updated_at = NOW()"
        )
        with engine.connect() as conn:
            conn.execute(sql, {
                "key": key, "gene": gene, "pos": position, "ptm_type": ptm_type,
                "task": task_name, "pmid_hash": ph, "result_json": result_json,
            })
            conn.commit()
        logger.debug(f"[PhaseB-Cache WRITE] {gene} {position} / {task_name} (key={key[:8]}…)")
    except Exception as e:
        logger.debug(f"[PhaseB-Cache] set failed ({gene}/{task_name}): {e}")
