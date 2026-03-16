-- Add rag_collections column to orders table
-- Run once: docker exec -i ptm-mysql mysql -u ptm_user -pptm_dev_pass_2026 ptm_platform < scripts/migrate_orders_rag_collections.sql
-- (If column already exists, the ALTER will error — safe to ignore)

-- RAG collection selection (JSON array of collection IDs; NULL = use all active)
ALTER TABLE orders
  ADD COLUMN rag_collections JSON NULL AFTER report_options;
