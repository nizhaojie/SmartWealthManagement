<script setup lang="ts">
import { useSlots } from "vue";
import type { AppShellNavItem } from "./nav";

defineProps<{
  navItems: AppShellNavItem[];
  activeKey?: string;
}>();

const emit = defineEmits<{
  select: [key: string];
  logout: [];
}>();

const slots = useSlots();
</script>

<template>
  <div class="app-shell">
    <aside class="app-shell__aside">
      <div class="app-shell__brand">
        <slot name="brand" />
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
          <span>{{ item.label }}</span>
        </button>
      </nav>
    </aside>
    <div class="app-shell__main">
      <header class="app-shell__topbar">
        <div v-if="slots.topbar" class="app-shell__topbar-start">
          <slot name="topbar" />
        </div>
        <div class="app-shell__topbar-end">
          <slot name="user" />
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
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  height: 100vh;
  font-family: var(--wm-font-family);
  color: var(--wm-text-primary);
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

/* 侧边栏：白底卡片面 + 右侧 1px 细线（细线属令牌纪律声明的极少数例外） */
.app-shell__aside {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: var(--wm-sidebar-width);
  background-color: var(--wm-bg-card);
  border-right: 1px solid var(--wm-border);
}

.app-shell__brand {
  padding: var(--wm-space-4) var(--wm-space-5);
  font-weight: 600;
  color: var(--wm-text-primary);
}

.app-shell__nav {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  flex: 1;
  overflow-y: auto;
  padding: 0 var(--wm-space-2) var(--wm-space-4);
}

.app-shell__nav-item {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
  padding: var(--wm-space-2) var(--wm-space-3);
  border: none;
  border-radius: var(--wm-radius-sm);
  background: transparent;
  color: var(--wm-text-secondary);
  font-size: inherit;
  text-align: left;
  cursor: pointer;
}

.app-shell__nav-item:hover {
  background-color: var(--wm-bg-page);
  color: var(--wm-text-primary);
}

.app-shell__nav-item[aria-current="page"] {
  background-color: var(--wm-color-primary-tint);
  color: var(--wm-color-primary);
  font-weight: 600;
}

.app-shell__nav-icon {
  width: var(--wm-space-4);
  height: var(--wm-space-4);
  flex-shrink: 0;
}

/* 主列：顶栏 + 内容 */
.app-shell__main {
  display: flex;
  flex-direction: column;
  flex: 1;
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
  padding: var(--wm-space-1) var(--wm-space-2);
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-card);
  color: var(--wm-text-secondary);
  cursor: pointer;
}

.app-shell__logout:hover {
  color: var(--wm-text-primary);
  border-color: var(--wm-text-muted);
}

.app-shell__content {
  flex: 1;
  overflow-y: auto;
  padding: var(--wm-space-5);
  background-color: var(--wm-bg-page);
}
</style>
