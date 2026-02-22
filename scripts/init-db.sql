-- PTM Platform Database Initialization
-- This runs automatically on first MySQL container startup

SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;

-- The database is created by Docker MYSQL_DATABASE env var.
-- Tables are created by SQLAlchemy on API server startup.
-- This file is for any additional initialization if needed.

-- Grant privileges
GRANT ALL PRIVILEGES ON ptm_platform.* TO 'ptm_user'@'%';
FLUSH PRIVILEGES;
