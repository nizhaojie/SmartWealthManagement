# 02 — 线程 store 与清空对话

**What to build:** 一轮问答不再是「一个被覆盖的结果」，而是一条可累积、活过刷新的线程。线程存 Pinia 并持久化到 `sessionStorage`，登出与重新登录清空；页头给一个「清空对话」作为换话题的出口——因为这次改动关掉了员工今天唯一的重置手段（刷新即新会话）。

**Blocked by:** 01 — 会话标识改由登录凭证承载

**Status:** ready-for-agent

- [ ] 在 `apps/internal/src/analytics/` 内新建线程 store（Pinia，**不进 `packages/shared`**）：消息形状为 `{id, role, …}`，动作覆盖开启一轮 / 写入结果 / 失败收尾
- [ ] `sessionStorage` 持久化，键按员工隔离，沿用 internal 既有的 `wealth-internal-` 前缀风格
- [ ] 序列化上限：每轮结果行沿用后端 200 行上限，线程只保留最近 **20 轮**；被截掉的更早轮次在界面上显示为「更早的一轮已从本页移除」
- [ ] 登出与重新登录都清空线程（挂到既有登出路径，不新起机制）
- [ ] 页头「清空对话」按钮：会话里有内容时二次确认；确认后清 store + `sessionStorage`，并生成新 UUID 随请求覆盖
- [ ] **「清空对话」不触碰审计留痕**——留痕是逐次查询的合规记录，不受界面动作影响
- [ ] 断言：线程经 `sessionStorage` 往返后内容一致（重新挂载后不变形）
- [ ] 断言：登出后线程与 `sessionStorage` 都被清掉
- [ ] 断言：清空之后的下一次请求带上了新的会话标识（验请求体）

**实现落点：** `apps/internal/src/analytics/`（store）、`apps/internal/src/auth/`（登出路径接线）、`DataAnalysisWorkspace.vue`（页头按钮）。

**验收：** 连问两轮后刷新页面，两轮问答都还在；点「清空对话」后主区回到空态，且紧接着的提问不再带着清空前的上下文。历史查询抽屉里的留痕一条未少。
