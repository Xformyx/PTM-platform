-- Add receptor_inference_data column to orders table (v9.20)
-- Run once on the server:
--   docker exec -i ptm-mysql mysql -u ptm_user -pptm_dev_pass_2026 ptm_platform < scripts/migrate_orders_receptor_inference.sql
-- (If column already exists, the ALTER will error — safe to ignore)

ALTER TABLE orders
  ADD COLUMN receptor_inference_data JSON NULL
  AFTER kinase_analysis_data;
