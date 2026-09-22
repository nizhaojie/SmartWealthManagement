import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
// BACKEND_PYTHON 指定解释器（如 conda 环境的 python.exe）；未设置时退回 backend/.venv。
const envPython = process.env.BACKEND_PYTHON;
const winPython = join(backend, ".venv", "Scripts", "python.exe");
const nixPython = join(backend, ".venv", "bin", "python");
const python =
  envPython && existsSync(envPython) ? envPython : existsSync(winPython) ? winPython : nixPython;

// --demo：确定性回放模式（ADR-0008）。预置问答走回放，不发起任何对外部
// 服务的调用，演示不依赖 LLM、Milvus、Neo4j、Redis 的健康状态。
const demo = process.argv.includes("--demo");
if (demo) {
  process.env.DEMO_REPLAY = "1";
  console.log("[dev-backend] DEMO_REPLAY=1 —— 回放模式：预置问答确定性回放，不发起外部调用");
}

// 依赖预检：pyproject.toml 的 dependencies 是运行期依赖的唯一来源，但解释器是
// 环境级的（conda 环境 wealth-backend / backend/.venv 都先建好后装依赖）。不预检的话，
// 新加的依赖要等到 import 那一刻才报 ModuleNotFoundError。缺什么补什么，失败即止。
const deps = spawnSync(python, ["-m", "scripts.check_deps", "--install"], {
  stdio: "inherit",
  cwd: backend,
  env: process.env,
});
if (deps.status !== 0) {
  process.exit(deps.status ?? 1);
}

const setup = spawnSync(python, ["-m", "app.db.setup"], {
  stdio: "inherit",
  cwd: backend,
  env: process.env,
});
if (setup.status !== 0) {
  process.exit(setup.status ?? 1);
}

const child = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"],
  { stdio: "inherit", cwd: backend, env: process.env },
);

child.on("exit", (code) => {
  process.exit(code ?? 1);
});
