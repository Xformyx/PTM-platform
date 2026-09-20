"""Versioned persistent derived-interpretation cache.

Exact PMID coverage plus caller-scoped context/model/prompt keys are required.
The historical best-match entry point now performs exact lookup only; smaller
prior searches cannot satisfy a larger requested evidence scope. Errors are not
stored as successful interpretations. Database failure remains a cache miss.

[OPT-T7] Redis L1 cache (TTL 1h) sits in front of MySQL for Phase B lookups.
[OPT-A2] SHA256 file hashes are cached per (path, mtime, size) to avoid
          repeated hashing of the same unchanged file across stage fingerprints.
"""

import hashlib
import json
import logging
import os
import threading

from sqlalchemy import text

from common.db_engine import get_engine as _engine

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS: int = int(os.getenv("PHASE_B_CACHE_TTL_DAYS", "30"))
_REDIS_L1_TTL: int = int(os.getenv("PHASE_B_REDIS_TTL", "3600"))  # 1 hour

# ──────────────────────────────────────────────────────────────────────────────
# [OPT-T7] Redis L1 cache layer
# ──────────────────────────────────────────────────────────────────────────────

_redis_client = None
_redis_init_lock = threading.Lock()
_redis_init_done = False


def _get_redis():
    """Lazy-init a Redis client. Returns None if Redis is unavailable."""
    global _redis_client, _redis_init_done
    if _redis_init_done:
        return _redis_client
    with _redis_init_lock:
        if _redis_init_done:
            return _redis_client
        try:
            import redis
            _url = os.getenv("REDIS_URL", "redis://redis:6379/0")
            _redis_client = redis.from_url(_url, decode_responses=True, socket_timeout=2)
            _redis_client.ping()
            logger.debug("[PhaseB-Cache] Redis L1 connected")
        except Exception as e:
            logger.debug(f"[PhaseB-Cache] Redis L1 unavailable (MySQL-only mode): {e}")
            _redis_client = None
        _redis_init_done = True
        return _redis_client


def _redis_get(key: str) -> dict | None:
    """Try Redis L1 cache. Returns None on miss or unavailability."""
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(f"pb:{key}")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _redis_set(key: str, result: dict) -> None:
    """Store in Redis L1 cache with TTL."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(f"pb:{key}", _REDIS_L1_TTL, json.dumps(result, ensure_ascii=False, default=str))
    except Exception:
        pass


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
    raw = f"interpretation.v3__{gene}__{position}__{ptm_type}__{task_name}__{ph}"
    return hashlib.md5(raw.encode()).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────────────────

def get_cached(gene: str, position: str, ptm_type: str, task_name: str, pmids: list) -> dict | None:
    """정확한 PMID 조합으로 캐시 조회. Redis L1 → MySQL L2."""
    key = make_cache_key(gene, position, ptm_type, task_name, pmids)

    # [OPT-T7] Try Redis L1 first
    l1 = _redis_get(key)
    if l1 is not None:
        logger.debug(f"[PhaseB-Cache L1-HIT] {gene} {position} / {task_name}")
        return l1

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
            logger.debug(f"[PhaseB-Cache L2-HIT] {gene} {position} / {task_name} (key={key[:8]}…)")
            _redis_set(key, result)  # Promote to L1
            return result
        return None
    except Exception as e:
        logger.debug(f"[PhaseB-Cache] get failed ({gene}/{task_name}): {e}")
        return None


def get_cached_best_match(
    gene: str, position: str, ptm_type: str, task_name: str, pmids: list
) -> dict | None:
    """Compatibility adapter requiring identical context and evidence coverage."""
    return get_cached(gene, position, ptm_type, task_name, pmids)


def set_cached(
    gene: str, position: str, ptm_type: str, task_name: str, pmids: list, result: dict
) -> None:
    """
    결과를 캐시에 저장한다. 이미 있으면 갱신.
    빈 결과({})는 저장하지 않는다.
    pmid_list에 실제 PMID 목록을 JSON 배열로 저장 (subset matching용).
    """
    if not result or result.get("error") or result.get("query_status") in {"error", "timeout", "rate_limited", "api_error", "parse_failure"}:
        return
    key = make_cache_key(gene, position, ptm_type, task_name, pmids)

    # [OPT-T7] Write to Redis L1
    _redis_set(key, result)

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


# ──────────────────────────────────────────────────────────────────────────────
# [OPT-A2] SHA256 file-hash cache (per mtime+size)
# ──────────────────────────────────────────────────────────────────────────────

_file_hash_cache: dict[tuple, str] = {}
_file_hash_lock = threading.Lock()


def _cached_file_sha256(path) -> str | None:
    """SHA256 with (mtime, size) keyed cache to avoid re-hashing unchanged files."""
    from pathlib import Path
    from ptm_shared.report_revision import file_sha256
    p = Path(path)
    if not p.is_file():
        return None
    stat = p.stat()
    cache_key = (str(p.resolve()), stat.st_mtime_ns, stat.st_size)
    with _file_hash_lock:
        cached = _file_hash_cache.get(cache_key)
    if cached is not None:
        return cached
    digest = file_sha256(p)
    with _file_hash_lock:
        _file_hash_cache[cache_key] = digest
    return digest


def stage_fingerprint(source_paths, policy, code_paths=()):
    """Content-addressed preprocessing dependency key, independent of mtimes.

    [OPT-A2] Uses _cached_file_sha256 to avoid redundant hashing when the
    same file is referenced by multiple stage fingerprints.
    """
    from pathlib import Path
    payload = {'schema_version': 'preprocessing_stage_cache.v1', 'policy': policy,
               'sources': {role: _cached_file_sha256(path) for role, path in source_paths.items()},
               'code': {Path(path).name: _cached_file_sha256(path) for path in code_paths}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def stage_cache_valid(output_dir, stage, fingerprint, filenames):
    from pathlib import Path
    from datetime import datetime, timezone
    path = Path(output_dir) / ('.stage_' + stage + '.json')
    try:
        record = json.loads(path.read_text())
        if record['fingerprint'] != fingerprint:
            return False
        if stage != 'quantification' and (datetime.now(timezone.utc).timestamp() - record['completed_at_epoch']) > 86400:
            return False
        return all(record['outputs'].get(name) == _cached_file_sha256(Path(output_dir) / name) for name in filenames)
    except (OSError, ValueError, KeyError):
        return False


def record_stage_completion(output_dir, stage, fingerprint, filenames):
    from pathlib import Path
    from datetime import datetime, timezone
    from ptm_shared.report_revision import file_sha256, _atomic_json
    _atomic_json(Path(output_dir) / ('.stage_' + stage + '.json'), {
        'schema_version': 'preprocessing_stage_cache.v1', 'fingerprint': fingerprint,
        'completed_at_epoch': datetime.now(timezone.utc).timestamp(),
        'outputs': {name: file_sha256(Path(output_dir) / name) for name in filenames}})


def preserve_stage_outputs(output_dir, filenames):
    """Move superseded generated files to content-addressed history before retry.

    Raw inputs and registered report revisions are never supplied to this helper.
    A failed producer therefore cannot leave an old file masquerading as new.
    """
    from pathlib import Path
    from ptm_shared.report_revision import file_sha256
    root = Path(output_dir).resolve()
    for filename in filenames:
        source = root / filename
        if not source.resolve().is_relative_to(root) or source.name.startswith('rev_'):
            raise ValueError('invalid_preprocessing_output_path')
        if source.is_file():
            digest = file_sha256(source)
            destination = root / '.preprocessing_history' / digest / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and file_sha256(destination) != digest:
                raise ValueError('preprocessing_history_integrity_mismatch')
            source.replace(destination)
