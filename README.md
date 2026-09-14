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

一条命令起后端与客户端：

```bash
pnpm install
pnpm dev
```

- 客户端：http://localhost:5173
- Swagger：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

未配置 LLM key 时，后端以 `fake` provider 启动。环境变量说明见 `backend/.env.example`。
