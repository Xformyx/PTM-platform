-- Add Cross-Talk columns to orders table
-- Run once: docker exec -i ptm-mysql mysql -u ptm_user -pptm_dev_pass_2026 ptm_platform < scripts/migrate_orders_crosstalk.sql
-- (If columns already exist, that ALTER will error — safe to ignore)

-- Secondary file paths (Cross-Talk mode)
ALTER TABLE orders
  ADD COLUMN secondary_pr_matrix_path VARCHAR(500) NULL AFTER config_xlsx_path,
  ADD COLUMN secondary_pg_matrix_path VARCHAR(500) NULL AFTER secondary_pr_matrix_path;

-- Cross-Talk & Signal Propagation JSON data
ALTER TABLE orders
  ADD COLUMN cross_talk_data JSON NULL AFTER error_message,
  ADD COLUMN signal_propagation_data JSON NULL AFTER cross_talk_data;
