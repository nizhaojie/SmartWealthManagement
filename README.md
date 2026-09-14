# 智能财富管家系统

pnpm workspace：`apps/customer`、`apps/internal`、`packages/shared`。后端在 `backend/`，不进 workspace。

## 启动

```bash
docker compose up -d
```

后端（首次）：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

迁移与测试数据（可重复执行，开发库 `wealth`；测试走独立库 `wealth_test`）：

```bash
cd backend
python -m app.db.setup
```

`pnpm dev` 启动后端前会再跑一次上述命令。

测试账号密码统一为 `Test@1234`。客户：`wangc1`–`qianc5`（风险承受等级 C1–C5）；员工：`advisor1`（理财顾问）、`manager1`（客户经理）、`risk1`（风控专员）。

一条命令起后端与客户端：

```bash
pnpm install
pnpm dev
```

- 客户端：http://localhost:5173
- Swagger：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

未配置 LLM key 时，后端以 `fake` provider 启动。环境变量说明见 `backend/.env.example`。
