import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const winPython = join(backend, ".venv", "Scripts", "python.exe");
const nixPython = join(backend, ".venv", "bin", "python");
const python = existsSync(winPython) ? winPython : nixPython;

const setup = spawnSync(python, ["-m", "app.db.setup"], {
  stdio: "inherit",
  cwd: backend,
});
if (setup.status !== 0) {
  process.exit(setup.status ?? 1);
}

const child = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"],
  { stdio: "inherit", cwd: backend },
);

child.on("exit", (code) => {
  process.exit(code ?? 1);
});
