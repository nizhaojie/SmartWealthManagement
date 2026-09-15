import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

const scriptsDir = fileURLToPath(new URL(".", import.meta.url));
const checkBoundaryScript = join(scriptsDir, "check-boundary.mjs");
const realSrcDir = join(scriptsDir, "..", "src");

// 只跑真正的构建产物（CLI 子进程），断言退出码与报错文本这两样外部可观察
// 的东西——不导入内部函数，避免测试锁死实现细节（ADR-0009）。
function runCheck(targetDir) {
  return spawnSync(process.execPath, [checkBoundaryScript, targetDir], { encoding: "utf8" });
}

function withFixture(files, run) {
  const dir = mkdtempSync(join(tmpdir(), "shared-boundary-fixture-"));
  try {
    for (const [name, content] of Object.entries(files)) {
      writeFileSync(join(dir, name), content, "utf8");
    }
    return run(dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("passes on the real packages/shared/src", () => {
  const result = runCheck(realSrcDir);
  assert.equal(result.status, 0);
});

test("fails the build and names the offending identifier and line", () => {
  withFixture(
    {
      "probe.ts": 'export type AlertRecord = {\n  alertLevel: string;\n};\n',
    },
    (dir) => {
      const result = runCheck(dir);
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, /probe\.ts:2/);
      assert.match(result.stderr, /alertLevel/);
    },
  );
});

test("flags a business term regardless of casing or separator style", () => {
  withFixture(
    {
      "probe.ts": 'const a = "reviewStatus";\nconst b = "review_status";\nconst c = "REVIEW-STATUS";\nconst d = "审核状态";\n',
    },
    (dir) => {
      const result = runCheck(dir);
      assert.notEqual(result.status, 0);
      assert.equal((result.stderr.match(/probe\.ts:/g) ?? []).length, 4);
    },
  );
});

test("passes on technical vocabulary shared is allowed to hold", () => {
  withFixture(
    {
      "probe.ts": `
        export type Envelope<T> = { code: number; message: string; data: T | null; trace_id: string };
        export function formatCurrency(amount: number): string { return amount.toFixed(2); }
        export function formatDate(date: Date): string { return date.toISOString(); }
        export const themeTokens = { primaryColor: "#1f6feb", spacingUnit: 8 };
        export function createHttpClient(baseUrl: string) { return { get: () => baseUrl }; }
      `,
    },
    (dir) => {
      const result = runCheck(dir);
      assert.equal(result.status, 0);
    },
  );
});

test("does not false-positive when a term's letters merely span an unrelated identifier's word boundary", () => {
  // "workOrder" 的字符恰好能从 "networkOrderId" / "frameworkOrdering" 里拼出来，
  // 但两者的 camelCase 词边界并不对齐，不构成同一个词。
  withFixture(
    {
      "probe.ts": "export const networkOrderId = 1;\nexport const frameworkOrdering = 2;\n",
    },
    (dir) => {
      const result = runCheck(dir);
      assert.equal(result.status, 0);
    },
  );
});
