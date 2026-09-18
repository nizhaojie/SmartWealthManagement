<script setup lang="ts">
import { useSlots } from "vue";
import type { AppShellNavItem } from "./nav";

defineProps<{
  navItems: AppShellNavItem[];
  activeKey?: string;
  /** 品牌区副标题（02 的 "Wealth Copilot" 位）。 */
  brandSubtitle?: string;
}>();

const emit = defineEmits<{
  select: [key: string];
  logout: [];
}>();

// 三栏与否只有一个来源：调用方是否提供了 inspector 插槽。
// 不再额外接收 variant —— 插槽与 prop 两个来源一旦不一致，第三栏就会时有时无。
const slots = useSlots();
</script>

<template>
  <div class="app-shell" :class="{ 'app-shell--with-inspector': Boolean(slots.inspector) }">
    <aside class="app-shell__sidebar">
      <div class="app-shell__brand">
        <slot name="brand" />
        <span v-if="brandSubtitle" class="app-shell__brand-subtitle">{{ brandSubtitle }}</span>
      </div>

      <nav class="app-shell__nav" aria-label="主导航">
        <button
          v-for="item in navItems"
          :key="item.key"
          type="button"
          class="app-shell__nav-item"
          :name="item.name"
          :aria-current="item.key === activeKey ? 'page' : undefined"
          @click="emit('select', item.key)"
        >
          <component :is="item.icon" v-if="item.icon" class="app-shell__nav-icon" />
          <span class="app-shell__nav-label">{{ item.label }}</span>
          <em v-if="item.badge" class="app-shell__nav-badge">{{ item.badge }}</em>
        </button>
      </nav>

      <div v-if="slots['sidebar-footer']" class="app-shell__sidebar-footer">
        <slot name="sidebar-footer" />
      </div>
    </aside>

    <div class="app-shell__main">
      <header class="app-shell__topbar">
        <div class="app-shell__topbar-start">
          <slot name="topbar-left" />
        </div>
        <div class="app-shell__topbar-end">
          <slot name="topbar-right" />
          <!-- 登出是壳层职责：任何应用、任何角色、任何路由下都必须可见可用 -->
          <button type="button" class="app-shell__logout" name="logout" @click="emit('logout')">
            登出
          </button>
        </div>
      </header>
      <main class="app-shell__content">
        <slot />
      </main>
    </div>

    <aside v-if="slots.inspector" class="app-shell__inspector" aria-label="辅助面板">
      <slot name="inspector" />
    </aside>
  </div>
</template>

<style scoped>
/* 两栏与三栏只差检查器那一列；窄屏收窄来自令牌层的媒体查询。
   分栏的 1px 细线与控件描边同属令牌纪律声明的极少数例外（令牌里没有 1px 这一档）。 */
.app-shell {
  display: grid;
  grid-template-columns: var(--wm-sidebar-width) minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  height: 100vh;
  font-family: var(--wm-font-family);
  color: var(--wm-text-primary);
}

.app-shell--with-inspector {
  grid-template-columns: var(--wm-sidebar-width) minmax(0, 1fr) var(--wm-inspector-width);
}

.app-shell,
.app-shell *,
.app-shell *::before,
.app-shell *::after {
  box-sizing: border-box;
}

.app-shell button {
  font-family: inherit;
}

/* 侧栏：白面 + 右侧 1px 细线（细线属令牌纪律声明的极少数例外） */
.app-shell__sidebar {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
  min-height: 0;
  overflow-y: auto;
  padding: var(--wm-space-5) var(--wm-space-4);
  background-color: var(--wm-bg-sidebar);
  border-right: 1px solid var(--wm-border);
}

.app-shell__brand {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  flex-shrink: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--wm-text-primary);
}

.app-shell__brand-subtitle {
  font-size: 0.65rem;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--wm-text-muted);
}

.app-shell__nav {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.app-shell__nav-item {
  display: flex;
  align-items: center;
  gap: var(--wm-space-3);
  padding: var(--wm-space-2) var(--wm-space-3);
  border: 1px solid transparent;
  border-radius: var(--wm-radius-sm);
  background: transparent;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  text-align: left;
  cursor: pointer;
}

.app-shell__nav-item:hover {
  background-color: var(--wm-bg-page);
  color: var(--wm-text-primary);
}

/* 激活项是淡染底：底上的文字必须走 primary-strong，primary 本身只有 3.61:1 */
.app-shell__nav-item[aria-current="page"] {
  background-color: var(--wm-color-primary-tint);
  color: var(--wm-color-primary-strong);
  font-weight: 600;
}

.app-shell__nav-icon {
  width: var(--wm-space-4);
  height: var(--wm-space-4);
  flex-shrink: 0;
}

.app-shell__nav-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-shell__nav-badge {
  margin-left: auto;
  padding: 0 var(--wm-space-2);
  border-radius: var(--wm-radius-pill);
  /* 淡底用 danger 的半透明 alpha（02 的 --danger-soft 是同一手法），不写死底色 */
  background-color: color-mix(in srgb, var(--wm-color-danger) 12%, transparent);
  color: var(--wm-color-danger);
  font-size: 0.7rem;
  font-style: normal;
  font-weight: 700;
  line-height: 1.6;
}

.app-shell__sidebar-footer {
  flex-shrink: 0;
}

/* 主列：顶栏 + 内容 */
.app-shell__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.app-shell__topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--wm-space-4);
  height: var(--wm-topbar-height);
  flex-shrink: 0;
  padding: 0 var(--wm-space-5);
  background-color: var(--wm-bg-card);
  border-bottom: 1px solid var(--wm-border-hairline);
}

.app-shell__topbar-start {
  display: flex;
  align-items: center;
  min-width: 0;
}

.app-shell__topbar-end {
  display: flex;
  align-items: center;
  gap: var(--wm-space-3);
  margin-left: auto;
}

.app-shell__logout {
  padding: var(--wm-space-1) var(--wm-space-3);
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-card);
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  cursor: pointer;
}

.app-shell__logout:hover {
  color: var(--wm-text-primary);
  border-color: var(--wm-text-muted);
}

.app-shell__content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--wm-space-5);
  background-color: var(--wm-bg-page);
}

/* 右侧检查器：与侧栏同底，左侧 1px 细线 */
.app-shell__inspector {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
  min-height: 0;
  overflow-y: auto;
  padding: var(--wm-space-5) var(--wm-space-4);
  background-color: var(--wm-bg-sidebar);
  border-left: 1px solid var(--wm-border);
}

/* 唯一的塌陷规则（spec「布局常量」）：第三栏在窄屏不再占列，检查器随之不渲染 */
@media (max-width: 1199px) {
  .app-shell--with-inspector {
    grid-template-columns: var(--wm-sidebar-width) minmax(0, 1fr);
  }

  .app-shell__inspector {
    display: none;
  }
}

/* 载入浮现：壳自身的区块各出现一次，不做逐项 nth-child 错峰延迟 */
@media (prefers-reduced-motion: no-preference) {
  .app-shell__brand,
  .app-shell__sidebar-footer,
  .app-shell__topbar-start,
  .app-shell__topbar-end {
    animation: wbRise 0.55s var(--wm-ease-rise) backwards;
  }

  .app-shell__nav-item {
    animation: wbFade 0.5s var(--wm-ease-rise) backwards;
  }

  .app-shell__inspector > * {
    animation: wbRise 0.55s var(--wm-ease-rise) backwards;
  }
}
</style>
