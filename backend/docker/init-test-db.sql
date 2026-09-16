CREATE DATABASE IF NOT EXISTS wealth_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON wealth_test.* TO 'wealth_app'@'%';

-- 数据分析 Agent 的受限执行账号（ADR-0010）。
-- 此处只创建账号；对视图的 SELECT 授权要求视图已存在，
-- 由 app.db.analytics_account.setup_analytics_account 在迁移之后执行。
CREATE USER IF NOT EXISTS 'wealth_analytics'@'%' IDENTIFIED BY 'wealth_analytics_pw';

FLUSH PRIVILEGES;
