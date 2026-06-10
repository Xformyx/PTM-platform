"""
Persistent cache for Phase B LLM sub-task results.

캐시 키: MD5(gene__position__ptm_type__task_name__pmid_hash)
 - pmid_hash : MD5(sorted PMID 목록을 쉼표로 이은 문자열)
 - task_name : abstract | kinase | functional | fulltext | validation | regulation

Subset matching (v2):
  논문 수 변경 시 캐시를 재활용할 수 있도록, pmid_list 컬럼에 실제 PMID 목록을 저장한다.
  정확한 키 매치가 없을 때 get_cached_best_match()로 폴백하면, 요청 PMID의 부분집합으로
  분석된 기존 캐시 중 가장 많은 논문을 사용한 결과를 반환한다.

  예) 3편([A,B,C])으로 캐시된 결과가 있고, 5편([A,B,C,D,E])으로 요청 시
      → 기존 3편 캐시 히트 (D,E는 새 논문으로 LLM 생략)

Uses the shared SQLAlchemy engine from common.db_engine.
캐시 실패는 항상 silently ignore — 캐시가 없어도 파이프라인은 정상 동작한다.
"""

import hashlib
import json
import logging
import os

from sqlalchemy import text

from common.db_engine import get_engine as _engine

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS: int = int(os.getenv("PHASE_B_CACHE_TTL_DAYS", "30"))


# ──────────────────────────────────────────────────────────────────────────────
# 키 생성 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

def _pmid_hash(pmids: list) -> str:
    """PMIDs 목록을 정렬·연결한 MD5 (16자리)."""
    joined = ",".join(sorted(str(p) for p in pmids if p))
    return hashlib.md5(joined.encode()).hexdigest()[:16]


def _pmid_set(pmids: list) -> set:
    return {str(p) for p in pmids if p}


def make_cache_key(gene: str, position: str, ptm_type: str, task_name: str, pmids: list) -> str:
    ph = _pmid_hash(pmids)
    raw = f"{gene}__{position}__{ptm_type}__{task_name}__{ph}"
    return hashlib.md5(raw.encode()).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────────────────

def get_cached(gene: str, position: str, ptm_type: str, task_name: str, pmids: list) -> dict | None:
    """정확한 PMID 조합으로 캐시 조회. 미스 시 None 반환."""
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


def get_cached_best_match(
    gene: str, position: str, ptm_type: str, task_name: str, pmids: list
) -> dict | None:
    """
    요청 PMID의 부분집합(subset)으로 분석된 기존 캐시 중 가장 많은 논문을 사용한 결과 반환.

    논문 수를 변경했을 때 기존 캐시를 재활용하기 위한 폴백 조회.
    pmid_list 컬럼이 NULL인 구형 캐시 엔트리는 건너뛴다.
    """
    if not pmids:
        return None
    requested = _pmid_set(pmids)
    try:
        engine = _engine()
        ttl_clause = ""
        params: dict = {"gene": gene, "pos": position, "ptm_type": ptm_type, "task": task_name}
        if CACHE_TTL_DAYS > 0:
            ttl_clause = " AND updated_at >= DATE_SUB(NOW(), INTERVAL :ttl DAY)"
            params["ttl"] = CACHE_TTL_DAYS

        sql = text(
            "SELECT result_json, pmid_list FROM phase_b_cache "
            "WHERE gene = :gene AND position = :pos AND ptm_type = :ptm_type "
            "  AND task_name = :task AND pmid_list IS NOT NULL"
            + ttl_clause +
            " ORDER BY updated_at DESC LIMIT 50"
        )
        with engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        best_result = None
        best_count = 0
        for row in rows:
            try:
                cached_pmids = set(json.loads(row[1]))
            except Exception:
                continue
            if cached_pmids and cached_pmids == requested and len(cached_pmids) > best_count:
                best_result = json.loads(row[0])
                best_count = len(cached_pmids)

        if best_result is not None:
            logger.info(
                f"[PhaseB-Cache EXACT HIT] {gene} {position} / {task_name} "
                f"— matched {best_count} articles from cache"
            )
        return best_result
    except Exception as e:
        logger.debug(f"[PhaseB-Cache] best_match failed ({gene}/{task_name}): {e}")
        return None


def set_cached(
    gene: str, position: str, ptm_type: str, task_name: str, pmids: list, result: dict
) -> None:
    """
    결과를 캐시에 저장한다. 이미 있으면 갱신.
    빈 결과({})는 저장하지 않는다.
    pmid_list에 실제 PMID 목록을 JSON 배열로 저장 (subset matching용).
    """
    if not result:
        return
    key = make_cache_key(gene, position, ptm_type, task_name, pmids)
    try:
        ph = _pmid_hash(pmids)
        pmid_list_json = json.dumps(sorted(str(p) for p in pmids if p))
        result_json = json.dumps(result, ensure_ascii=False, default=str)
        engine = _engine()
        sql = text(
            "INSERT INTO phase_b_cache "
            "  (cache_key, gene, position, ptm_type, task_name, pmid_hash, pmid_list, result_json) "
            "VALUES "
            "  (:key, :gene, :pos, :ptm_type, :task, :pmid_hash, :pmid_list, :result_json) "
            "ON DUPLICATE KEY UPDATE "
            "  result_json = VALUES(result_json), "
            "  pmid_list   = VALUES(pmid_list), "
            "  updated_at  = NOW()"
        )
        with engine.connect() as conn:
            conn.execute(sql, {
                "key": key, "gene": gene, "pos": position, "ptm_type": ptm_type,
                "task": task_name, "pmid_hash": ph,
                "pmid_list": pmid_list_json, "result_json": result_json,
            })
            conn.commit()
        logger.debug(f"[PhaseB-Cache WRITE] {gene} {position} / {task_name} (key={key[:8]}…)")
    except Exception as e:
        logger.debug(f"[PhaseB-Cache] set failed ({gene}/{task_name}): {e}")
