-- Extend order_code from VARCHAR(20) to VARCHAR(64) to support longer project names
-- Run: mysql -u ptm_user -p ptm_platform < scripts/migrate_order_code_length.sql

ALTER TABLE orders MODIFY COLUMN order_code VARCHAR(64) NOT NULL;
