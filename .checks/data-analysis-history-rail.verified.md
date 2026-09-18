# 数据分析 · 历史查询移入壳层右侧栏 Verification

**Verdict**: PASS
**Profile**: light
**Diff range**: 工作区未提交改动（本仓库这一轮没有 commit，`HEAD..working tree`）
**Round**: 1 - full
**Verifier**: independent sub-agent (author != verifier)

> **工具限制，先说清楚**：本次核验子代理只拿到只读检索工具（`search_file` / `search_content` / `read_file` / `read_lints` / `lsp`），**没有 shell 也没有写文件的能力**。因此：
> - 逐条断言的定位与复述、`Swept` 既有约束的核对、`Landing` 的独立判断 —— 由子代理完成（那部分是独立结论）。
> - 跑 proof、读 `git diff`、落盘本文件 —— 由编排者补做（见 `## Gate`）。**「proof 由核验者亲手跑」这一层没有达成**，记为首要 gap，没有含糊过去。

## Checks

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | `/data-analysis` 注入右侧检查器；条目只在栏内，内容区没有这张卡 | `pnpm --filter @wealth/internal test -- src/analytics/analyticsHistoryRail.spec.ts src/shell/inspectorSlot.spec.ts -t "…7 条交替…" --reporter=verbose` → 该用例 ✓ 333ms | `analyticsHistoryRail.spec.ts:106`；`assert` 在 `:109` 三栏类名、`:110` 栏内条目文案、`:112` 内容区条目数为 0。实现 `DataAnalysisWorkspace.vue:78` `useInspector(...)`；模板 `:141`/`:143` 只剩详情与结果 | PASS |
| C2 | 点击历史记录在主区展示该条的问题/状态/生成查询/行数 | 同上 → ✓ 70ms | `:115`；`:122-124` problem 文案等于 `HISTORY[0].question`、`:125` 状态为「成功」、`:126-128` SQL 含 `GROUP BY risk_level`、`:129` 含「5 行」 | PASS |
| C3 | 点击历史记录不改写提问框 | 同上 → ✓ 62ms | `:132`；`:135` 预置与条目问题不同的 `"我正在输入的问题"`，`:139` 点击后仍等于该值 | PASS |
| C4 | 提问成功后不再展示先前选中的历史记录 | 同上 → ✓ 143ms | `:142`；`:145` 选中后有详情、`:152` 新结果已渲染、`:153` 详情消失。实现 `DataAnalysisWorkspace.vue:62` 提问成功即复位 | PASS |
| C5 | 历史拉取失败且列表为空时栏内说明加载失败 | 同上 → ✓ 51ms | `:156`；`:160` 文案含「加载失败」、`:161` `history-empty` 不存在。实现 `AnalyticsHistoryPanel.vue:23` 仅在 `!history.length && failed` 时渲染 | PASS |
| C6 | 点击示例问题仍写回提问框 | 同上 → ✓ 55ms | `:164`；`:169` 输入框值等于 `EXAMPLE`。实现 `DataAnalysisWorkspace.vue:130` / `:73-75` | PASS |
| C7 | 离开数据分析页后第三栏收回（回归） | 同上 → ✓ 847ms | `inspectorSlot.spec.ts:90`；`:95` profile→true、`:98` data-analysis→true、`:101` knowledge→false、`:102` `.app-shell__inspector` 不存在 | PASS |

一次调用内 7 条命名用例逐条出现在输出中并各自通过，`Tests 7 passed | 1 skipped (8)`；唯一 skipped 是未进入过滤器的旧用例。`--passWithNoTests` 的空命中陷阱已被排除：7 个名字都真的跑了。

`read_lints` 对 6 个相关文件报 0 条诊断；`pnpm --filter @wealth/internal typecheck` 退出码 0；`pnpm --filter @wealth/internal test` 全量 13 个测试文件通过。

## 未跑 / 不适用的步骤

| 步骤 | 为什么没跑 |
| --- | --- |
| 第 1 步 binding 源对照 | `ui` profile 专属；清单未把任何设计稿标为 binding（`AnalyticsQueryAudit` 是数据契约，已在 `Swept` 核对，不是 UI binding） |
| `Coverage` join、`Test policy` 行 | `standard` / `ui` 专属；清单没有这两节 |
| 故障注入 | `standard` / `ui` 专属 |

## Swept 既有约束复核

| 行 | 结论 |
| --- | --- |
| 「后端 `list_query_history` 已按登录员工过滤」 | 成立 —— `backend/app/analytics/service.py:142` `where(AnalyticsQueryAudit.employee_id == employee.id)` |
| 「栏沿用 `/api/internal/analytics/history`」 | 成立 —— `analytics/api.ts:19`，且 `AnalyticsHistoryPanel.vue` 全文没有任何请求 |
| 「留痕行只有 question / generated_sql / status / row_count / truncated / error_code / create_time」 | 成立 —— `backend/app/db/models.py:826-836`；`AnalyticsHistoryDetail.vue` 只画这些字段，没有伪造结果集 |
| 「选中态由页面持有，栏只上抛」 | 结论成立（栏零赋值，仅 `emit('select')`），但措辞不精确 —— 见 Gaps #2 |

## Landing 复核

**「既有测试 `inspectorSlot.spec.ts` 断言 `/data-analysis` 不注入检查器，本次随需求一起改」——判定：反映新需求，不是为变绿而弱化。**

依据（`inspectorSlot.spec.ts`）：

- 新断言 `:86` `expect(hasInspector(app)).toBe(true)` 之外还**追加**了 `:87` `expect(app.get('[data-testid="history-empty"]').text()).toContain("还没有历史查询")` —— 不只是翻转真假，还绑定了本次新增的栏内文案，是正向强化。
- 同一用例对既有页面的断言一条没动、一条没删：`:63` 落地页 false、`:66` profile true、`:71` advisory true、`:74` risk true、`:78` work-orders true、`:82` knowledge false。覆盖只增不减。
- C7 用例 `:90` 把 `/data-analysis` 纳入「注入页」序列（`:98`），与「历史查询常驻第三栏」的需求一致。

**点击不写回提问框这条能否捕获回归 ——判定：能。** `:135` 预置的值与条目问题不同，若实现退回 `question.value = entry.question`，`:139` 必红。

**是否有 proof 命中本次没碰过的测试 —— 没有。** C1–C6 全在本次新增文件里；C7 所在文件的 `:97-98` 正是本次新增的行为。

## Gaps

1. **【首要，工具导致】proof 由编排者代跑，不是核验者亲手跑。** 子代理无 shell，无法执行 runner、也无法读 `git diff`。「测试通过」这一结论的证据来自编排者的一次批量调用（7/7 逐条 ✓，已排除 `--passNoTests` 空命中），核验者只独立确认了「用例存在 + 断言断的就是清单写的值 + 行号可引」。要闭环需在具备 shell 的核验环境重跑。
2. **【精度缺口，清单措辞】** `Swept` 写「选中态只有一处写（页面）」不精确：`selectedHistoryId` 在页面内有**两处**赋值 —— `DataAnalysisWorkspace.vue:85`（点选）与 `:62`（提问后复位）；栏组件确为零写。结论不受影响，但措辞应写成「页面是唯一 owner」。
3. **【流程】无法把 range 表达成 `<base>..<head>`。** 本轮没有 commit（遵循「未经明确要求不提交」），改动全部在工作区，含 3 个新增未跟踪文件。

## Gate

`pnpm --filter @wealth/internal test -- src/analytics/analyticsHistoryRail.spec.ts src/shell/inspectorSlot.spec.ts -t "<C1..C7 交替>" --reporter=verbose` - 7 passed, 0 failed, 1 skipped

`pnpm --filter @wealth/internal test` - 13 test files passed

`pnpm --filter @wealth/internal typecheck` - exit 0
