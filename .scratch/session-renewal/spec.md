# 会话续期：access token 过期不再把人踢下线

Status: done

## Problem Statement

两个前端登录后停留约 15 分钟就会被送回登录页。触发条件与操作无关——人是坐在页面上没动，还是正在翻页，都一样；到点后下一个接口调用就把人踢出去。

## Root cause

后端本就设计成短时效 access token + 长时效 refresh token（`backend/app/settings.py:62-63`：access 15 分钟、refresh 7 天），并提供了 `/api/customer/auth/refresh` 与 `/api/internal/auth/refresh` 两个端点。

前端只用了前一半：`LoginResult` 只取 `access_token` / `refresh_token`，两个 `auth/api.ts` 只有 `login` / `logout`，**全仓没有任何一处调用 refresh**。于是 401 一路走到 `handleExpiredSession` / `clearTokens`，令牌被清 → `isAuthenticated` 变假 → `App.vue` 的 `watch` 把人送回登录页。

`frontend-rebuild` 的 spec 把这记作「后端已实现、前端未接入」的缺口，但没有 slice 认领它，就一直没有落地。

## Solution

把 401 从「会话结束」改成两段式：**先续期、再重发一次；续不到才算会话结束**。

| 层次 | 改动 |
|---|---|
| `packages/shared/src/http.ts` | 新增可选钩子 `renewTokens?: () => Promise<boolean>`。401 时若钩子返回 true，则用重新读取的令牌重发一次原请求；返回 false 才调 `onUnauthorized`。并发 401 共享同一个在途 Promise，只续期一次。重发后仍 401 不再续期（不配钩子时行为与从前完全一致）。 |
| `packages/shared/src/tokenStore.ts` | 新增 `setAccessToken()`：只换 access token 并保留 refresh token。整对 `setTokens` 覆盖会把手里还没过期的 refresh token 抹掉，15 分钟后无人可续。未登录时忽略。 |
| `apps/*/src/api/http.ts` | 各自新增 `renewSession()`：用 refresh token 打本域 `/auth/refresh`，成功则 `setAccessToken` 并返回 true。**不清令牌**——收场方式仍由唯一的失效点 `onUnauthorized` 决定，避免两处各清一次。续期请求走一个不挂续期钩子、也不挂失效回调的裸客户端，否则刷新失败会递归回同一段逻辑。 |
| `apps/customer/src/chat/api.ts` | SSE 通道绕过了 http 客户端，401 得自己处理：先 `renewSession()`，成功则重连一次，失败才 `handleExpiredSession()`。 |

身份域边界不变（ADR-0009 护栏 2）：两端的续期各打各自域的端点、读写各自的 localStorage key；`renewSession` 由 `renewalClient` 发出且不带 Bearer，refresh token 的受众校验在后端。续期发生在同一条会话内，不产生新会话，`CONTEXT.md` 与 `docs/adr/` 无需改动。

## Testing Decisions

- `packages/shared/src/http.test.ts`：续期成功→重发且带上新令牌、续期失败→只失效一次、重发后仍 401→收手、并发 401→只续期一次、无钩子→行为不变、非 401→不触发续期。
- `packages/shared/src/tokenStore.test.ts`：`setAccessToken` 保留 refresh token；无会话时忽略。
- `apps/customer/src/api/http.spec.ts`、`apps/internal/src/api/http.spec.ts`：两个身份域各验一遍「401 → 打本域 refresh → 重发原请求」，且 refresh 请求体带的是本域 refresh token。
- `apps/customer/src/chat/api.spec.ts`：流式通道 401 → 续期 → 重连并带上新令牌；原「刷新凭证也过期」用例补上全局 fetch 替身，用例不再真的出网。

## Out of Scope

- **主动续期**（到期前定时刷新、按 `expires_in` 预判）。失败一次 + 重发一次的代价是每 15 分钟一次额外往返，不值得为此引入定时器与第二处状态。
- **修改 token 时效或后端任何代码**。后端机制本来就是完整的，缺的只是前端这一环。
- 已知遗留（**与本次改动无关，改动前后同样失败**）：`apps/internal/src/analytics/analyticsHistoryRail.spec.ts` 有 3 个用例断言 `textarea[name='question']`，而 `DataAnalysisWorkspace.vue:101-106` 的 `el-input` 没有 `type="textarea"`（placeholder 里却写着「Ctrl + Enter 提交」，像是丢了类型）。要修得先定「组件该是文本框还是文本域」，另开一份记录。
