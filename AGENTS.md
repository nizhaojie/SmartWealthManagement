# 智能财富管家系统

## Agent skills

### Issue tracker

本仓库没有 git remote，环境中也没有 `gh` / `glab`。Issues 与 specs 以 markdown 文件存放在 `.scratch/<feature-slug>/`：

- `spec.md` — 一个 feature 的完整 spec，头部用 `Status:` 标注 triage label
- `issues/NN-<slug>.md` — 从 spec 拆出的可独立实现的 issue

### Domain docs

Single-context：根目录 `CONTEXT.md`（领域词汇表，纯 glossary，不含实现细节）+ `docs/adr/`（架构决策记录）。

写 spec、issue 与代码时一律使用 `CONTEXT.md` 的规范用词，并遵守 `docs/adr/` 中已确立的决定。发现需要推翻某条 ADR 时，新增一条记录原因，不要静默偏离。

### 开发顺序

`docs/roadmap.md` 按竖切顺序排列，第一刀是客服链路端到端。
