-- Phase B LLM 결과 영구 캐시 테이블
-- Run once:
--   docker exec -i ptm-mysql mysql -u ptm_user -pptm_dev_pass_2026 ptm_platform \
--     < scripts/migrate_phase_b_cache.sql

CREATE TABLE IF NOT EXISTS phase_b_cache (
    id          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    cache_key   VARCHAR(64)  NOT NULL COMMENT 'MD5(gene__position__ptm_type__task__pmid_hash)',
    gene        VARCHAR(64)  NOT NULL,
    position    VARCHAR(32)  NOT NULL,
    ptm_type    VARCHAR(64)  NOT NULL,
    task_name   VARCHAR(32)  NOT NULL COMMENT 'abstract | kinase | functional | fulltext | validation | regulation',
    pmid_hash   VARCHAR(32)  NOT NULL COMMENT 'MD5 of sorted PMID list',
    result_json LONGTEXT     NOT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_cache_key (cache_key),
    INDEX idx_gene_task (gene, position, task_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Phase B LLM sub-task results — persistent across RAG enrichment runs';
