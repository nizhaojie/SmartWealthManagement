import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { formatViolation, scanTextForViolations } from "./business-semantics-guard.mjs";

const SCAN_EXTENSIONS = new Set([".ts", ".tsx", ".vue", ".js", ".mjs"]);

export function collectSourceFiles(rootDir) {
  const files = [];
  const stack = [rootDir];
  while (stack.length > 0) {
    const current = stack.pop();
    for (const name of readdirSync(current)) {
      const full = join(current, name);
      if (statSync(full).isDirectory()) {
        stack.push(full);
      } else if (SCAN_EXTENSIONS.has(extname(name))) {
        files.push(full);
      }
    }
  }
  return files;
}

export function findViolationsInDir(rootDir) {
  const violations = [];
  for (const file of collectSourceFiles(rootDir)) {
    const text = readFileSync(file, "utf8");
    violations.push(...scanTextForViolations(text, relative(rootDir, file)));
  }
  return violations;
}

function main() {
  const scriptDir = fileURLToPath(new URL(".", import.meta.url));
  const targetDir = process.argv[2] ? resolve(process.cwd(), process.argv[2]) : join(scriptDir, "..", "src");
  const violations = findViolationsInDir(targetDir);

  if (violations.length === 0) {
    console.log("[check-boundary] packages/shared 未检出业务语义标识，构建继续。");
    return;
  }

  console.error("[check-boundary] 构建中断：packages/shared 中检出业务语义标识（违反 ADR-0003）。");
  console.error("shared 只允许放与业务语义无关的东西：HTTP 客户端、响应拆包、错误码映射、格式化函数、主题令牌、图表壳。\n");
  for (const violation of violations) {
    console.error(formatViolation(violation));
  }
  console.error("\n请把上面这些概念移回 backend 或对应的 app，shared 不承载它们。");
  process.exitCode = 1;
}

const isMainModule = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMainModule) {
  main();
}
