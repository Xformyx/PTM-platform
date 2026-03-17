-- Expand ENUM values for rag_collections table
-- Run: docker exec -i ptm-mysql mysql -u ptm_user -pptm_dev_pass_2026 ptm_platform < scripts/migrate_rag_enum_expand.sql
--
-- This migration adds 'domain' and 'project' to the tier column,
-- and 'section_aware' to the chunk_strategy column.
-- Safe to run multiple times (idempotent via MODIFY COLUMN).

-- 1. Expand tier ENUM: add 'domain', 'project'
ALTER TABLE rag_collections
  MODIFY COLUMN tier ENUM('cell_type','ptm_type','pathway','general','domain','project') NOT NULL;

-- 2. Expand chunk_strategy ENUM: add 'section_aware'
ALTER TABLE rag_collections
  MODIFY COLUMN chunk_strategy ENUM('fixed','semantic','recursive','section_aware') DEFAULT 'recursive';

-- Verify
SELECT COLUMN_NAME, COLUMN_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'rag_collections'
  AND COLUMN_NAME IN ('tier', 'chunk_strategy');
