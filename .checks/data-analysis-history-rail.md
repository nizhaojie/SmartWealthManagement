# 数据分析 · 历史查询移入壳层右侧栏

Sources:

- 会话（本轮三条要求）— 历史查询移入工作台壳层常驻右侧栏；点击历史条目展示该条记录；点击不再把问题写回提问框
- `.scratch/data-analysis-agent/issues/03-result-interpretation-and-query-ui.md` — 「历史查询可查看与重用」，本次把「可查看」落成一条记录详情
- `apps/internal/src/shell/pageSlots.ts` — 右侧栏的注入通道，以及「页面持有 state、以 props 注入、inject 组件不自己取数」的既有约定
- `backend/app/db/models.py::AnalyticsQueryAudit` — **binding**：留痕行只有 question / generated_sql / status / row_count / truncated / error_code / create_time，没有结果集与解读。栏内与详情能画什么由它决定

## Out of scope

- 结果集回放（columns / rows / interpretation）— 留痕表不持久化它们。要看只能重跑，重跑产出的是「新查询」不是「历史记录」，而且会再写一条留痕。不新增列、不做迁移、不加接口
- 新增后端接口 — `GET /api/internal/analytics/history` 已返回详情所需的全部字段
- 窄屏（<1200px）下历史查询的可达性 — 沿用 AppShell 既有塌陷规则（第三栏不渲染），不另做一套布局
- 历史列表的搜索 / 筛选 / 分页 — 未被要求

## Landing

改动只落在 `apps/internal/src/analytics/`（工作区改造 + 两个新组件 + 一份新用例）与 `apps/internal/src/shell/inspectorSlot.spec.ts`；历史数据仍由页面拉取，栏只接 props、只上抛选中项——沿用 `pageSlots.ts` 的既有约定，不新增 store、不新增接口、不新增依赖。

| One-way door | Literal shape | Alternative rejected |
| --- | --- | --- |
| `/data-analysis` 开始注入右侧检查器 | `useInspector(() => ({ component: AnalyticsHistoryPanel, props: { history, selectedId, failed, onSelect } }))` | 在内容区自绘一条右栏——与壳层第三栏重复，且要自己再实现一遍 <1200px 塌陷，两处规则会各漂各的 |
| 点击条目展示的是留痕行本身，不是一个结果 | `PanelCard title="历史记录"` 渲染 question / status / row_count / truncated / error_code / create_time / generated_sql | 重跑该问题拿结果来填——那不是历史记录，且每次点击都多写一条留痕；在 336px 栏内放生成的查询——窄栏装行宽内容 |
| 点击条目只做选中，不再写回提问框 | 条目 `@click` → `emit('select', id)` | 保留既有的 `reuseQuestion(entry.question)`，或「既写回又展示」——用户明确否决 |
| 历史拉取失败在栏内单独成态 | `failed` 为真且列表为空 → `data-testid="history-error"` 显示「加载失败」 | 沿用既有的「拉不到就静默留着」，栏空着说「还没有历史查询」——第三栏里这句话是错的 |

- 既有测试 `apps/internal/src/shell/inspectorSlot.spec.ts` 断言 `/data-analysis` **不**注入检查器，编码的是旧设计；本次随需求一起改（C1、C7），改动在 diff 里可见
- Nothing else in this change is hard to reverse

## Checks

### S1 - 历史查询常驻右侧栏并可查看记录 · 9 files · ~30 KB · ~8k

**C1** - `/data-analysis` 注入右侧检查器，历史查询条目只出现在栏内，内容区不再有这张卡
Proof: `pnpm --filter @wealth/internal test -- src/analytics/analyticsHistoryRail.spec.ts -t "历史查询常驻右侧栏并列出记录"`

**C2** - 点击某条历史记录，主区展示该条的问题、状态、生成的查询与返回行数
Proof: `pnpm --filter @wealth/internal test -- src/analytics/analyticsHistoryRail.spec.ts -t "点击历史记录在主区展示该条记录"`

**C3** - 点击历史记录不改写提问框
Proof: `pnpm --filter @wealth/internal test -- src/analytics/analyticsHistoryRail.spec.ts -t "点击历史记录不改写提问框"`

**C4** - 提问成功后不再展示先前选中的历史记录
Proof: `pnpm --filter @wealth/internal test -- src/analytics/analyticsHistoryRail.spec.ts -t "提问后收起已选中的历史记录"`

**C5** - 历史拉取失败且列表为空时，栏内显示加载失败而不是「还没有历史查询」
Proof: `pnpm --filter @wealth/internal test -- src/analytics/analyticsHistoryRail.spec.ts -t "历史拉取失败时栏内说明加载失败"`

**C6** - 点击示例问题仍写回提问框（回归：`reuseQuestion` 未随历史条目一起被删）
Proof: `pnpm --filter @wealth/internal test -- src/analytics/analyticsHistoryRail.spec.ts -t "点击示例问题仍写回提问框"`

**C7** - 离开数据分析页后第三栏收回（回归）
Proof: `pnpm --filter @wealth/internal test -- src/shell/inspectorSlot.spec.ts -t "离开注入检查器的页面后第三栏收回"`

## Swept

- validation: 不适用 — 本次不新增任何输入字段
- failure modes: C5 — 历史拉取失败；C2 覆盖「选中的记录已被列表刷掉」时不渲染详情（`selectedRecord` 为空即不渲染）
- idempotency: 不适用 — 选中/收起无副作用，点击条目不发任何写请求（C3 顺带证明没有写回）
- authorization: 不改动 — 栏沿用 `/api/internal/analytics/history`，后端 `list_query_history` 已按登录员工过滤
- concurrency: 不适用 — 无并发写；栏是纯展示，选中态只有一处写（页面）
- data lifecycle: 不适用 — 不新增持久化，留痕表不动
- dependency failure: C5
- state transitions: C4（新提问 → 收起已选记录）、C3（点击条目 → 不再改提问）
- observability: 不适用 — 无新增日志或埋点要求

## Handoff

一个批次，不需要 handoff：S1 是唯一切片，~30 KB ≈ 8k tokens，远低于 150k 预算。
