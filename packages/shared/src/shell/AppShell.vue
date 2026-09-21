<script setup lang="ts">
import { onMounted, onUpdated, ref, useSlots } from "vue";
import type { AppShellNavItem } from "./nav";

defineProps<{
  navItems: AppShellNavItem[];
  activeKey?: string;
  /** 品牌区副标题（02 的 "Wealth Copilot" 位）。 */
  brandSubtitle?: string;
  /** 左栏折叠成图标条；受控，状态留在调用方，本组件不落地。 */
  sidebarCollapsed?: boolean;
  /** 第三栏完全隐藏；纯受控 prop，壳内无触发，开关在应用顶栏。 */
  inspectorCollapsed?: boolean;
}>();

const emit = defineEmits<{
  select: [key: string];
  logout: [];
  "update:sidebarCollapsed": [collapsed: boolean];
}>();

// 三栏与否只有一个来源：调用方是否提供了 inspector 插槽。
// 不再额外接收 variant —— 插槽与 prop 两个来源一旦不一致，第三栏就会时有时无。
const slots = useSlots();

// 品牌是纯文字插槽（无 logo 资源），折叠态显示首字符方块：从插槽渲染出的文本里
// 取首字符。onUpdated 兜底——品牌文字若被调用方动态改换，首字符跟着走。
const brandRef = ref<HTMLElement | null>(null);
const brandInitial = ref("");
function syncBrandInitial(): void {
  const text = brandRef.value?.textContent?.trim() ?? "";
  brandInitial.value = text.charAt(0);
}
onMounted(syncBrandInitial);
onUpdated(syncBrandInitial);
</script>

<template>
  <div
    class="app-shell"
    :class="{
      'app-shell--with-inspector': Boolean(slots.inspector),
      'app-shell--sidebar-collapsed': sidebarCollapsed,
      'app-shell--inspector-collapsed': inspectorCollapsed,
    }"
  >
    <aside class="app-shell__sidebar">
      <div class="app-shell__brand">
        <span ref="brandRef" class="app-shell__brand-text">
          <slot name="brand" />
        </span>
        <span v-if="sidebarCollapsed" class="app-shell__brand-initial" aria-hidden="true">
          {{ brandInitial }}
        </span>
        <span v-if="brandSubtitle && !sidebarCollapsed" class="app-shell__brand-subtitle">
          {{ brandSubtitle }}
        </span>
      </div>

      <nav class="app-shell__nav" aria-label="主导航">
        <el-tooltip
          v-for="item in navItems"
          :key="item.key"
          :content="item.label"
          placement="right"
          :disabled="!sidebarCollapsed"
        >
          <button
            type="button"
            class="app-shell__nav-item"
            :name="item.name"
            :aria-current="item.key === activeKey ? 'page' : undefined"
            :aria-label="item.label"
            @click="emit('select', item.key)"
          >
            <span class="app-shell__nav-icon-wrap">
              <component :is="item.icon" v-if="item.icon" class="app-shell__nav-icon" />
              <span
                v-if="item.badge && sidebarCollapsed"
                class="app-shell__nav-badge-dot"
                aria-hidden="true"
              />
            </span>
            <span v-if="!sidebarCollapsed" class="app-shell__nav-label">{{ item.label }}</span>
            <em v-if="item.badge && !sidebarCollapsed" class="app-shell__nav-badge">
              {{ item.badge }}
            </em>
          </button>
        </el-tooltip>
      </nav>

      <div v-if="slots['sidebar-footer']" class="app-shell__sidebar-footer">
        <slot name="sidebar-footer" />
      </div>

      <button
        type="button"
        class="app-shell__collapse-toggle"
        :aria-label="sidebarCollapsed ? '展开侧栏' : '折叠侧栏'"
        :aria-expanded="!sidebarCollapsed"
        @click="emit('update:sidebarCollapsed', !sidebarCollapsed)"
      >
        <svg class="app-shell__collapse-icon" viewBox="0 0 16 16" aria-hidden="true" fill="none">
          <path
            d="M9 4 5 8l4 4"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M13 4 9 8l4 4"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
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

    <aside
      v-if="slots.inspector && !inspectorCollapsed"
      class="app-shell__inspector"
      aria-label="辅助面板"
    >
      <slot name="inspector" />
    </aside>
  </div>
</template>

<style scoped>
/* 两栏与三栏只差检查器那一列；窄屏收窄来自令牌层的媒体查询。
   分栏的 1px 细线与控件描边同属令牌纪律声明的极少数例外（令牌里没有 1px 这一档）。
   第一列宽度走本地变量 --app-shell-sidebar-width：默认取令牌，折叠态换成 collapsed 令牌，
   让两栏/三栏两种 grid 形态与 <1200px 塌陷共用同一处宽度来源。 */
.app-shell {
  --app-shell-sidebar-width: var(--wm-sidebar-width);
  display: grid;
  grid-template-columns: var(--app-shell-sidebar-width) minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  height: 100vh;
  font-family: var(--wm-font-family);
  color: var(--wm-text-primary);
}

.app-shell--with-inspector {
  grid-template-columns: var(--app-shell-sidebar-width) minmax(0, 1fr) var(--wm-inspector-width);
}

/* 折叠态：第一列换成图标条宽度，其它列不变量。 */
.app-shell--sidebar-collapsed {
  --app-shell-sidebar-width: var(--wm-sidebar-width-collapsed);
}

/* 检查器折叠：grid 回到两列，与 <1200px 塌陷同形态，但由状态而非媒体查询驱动。 */
.app-shell--inspector-collapsed {
  grid-template-columns: var(--app-shell-sidebar-width) minmax(0, 1fr);
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

/* 折叠态收窄水平留白，给图标条腾出居中空间 */
.app-shell--sidebar-collapsed .app-shell__sidebar {
  padding: var(--wm-space-5) var(--wm-space-2);
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

.app-shell--sidebar-collapsed .app-shell__brand {
  align-items: center;
}

/* 折叠态隐藏完整品牌文字（仍留在 DOM，供首字符读取） */
.app-shell--sidebar-collapsed .app-shell__brand-text {
  display: none;
}

.app-shell__brand-initial {
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--wm-space-6);
  height: var(--wm-space-6);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-color-primary-tint);
  color: var(--wm-color-primary-strong);
  font-size: 0.9rem;
  font-weight: 700;
  flex-shrink: 0;
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

/* 折叠态：只留图标，居中排布，去掉横向留白与间距 */
.app-shell--sidebar-collapsed .app-shell__nav-item {
  justify-content: center;
  gap: 0;
  padding: var(--wm-space-2);
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

/* 图标外包一层相对定位，角标小圆点锚在图标右上角 */
.app-shell__nav-icon-wrap {
  position: relative;
  display: inline-flex;
  flex-shrink: 0;
}

.app-shell__nav-badge-dot {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--wm-color-danger);
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

/* 触发条：侧栏最底部占满宽度的细按钮，双箭头；aria-expanded 反映侧栏展开态 */
.app-shell__collapse-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  padding: var(--wm-space-2) 0;
  border: none;
  border-top: 1px solid var(--wm-border-hairline);
  background: transparent;
  color: var(--wm-text-muted);
  cursor: pointer;
}

.app-shell__collapse-toggle:hover {
  color: var(--wm-text-primary);
}

.app-shell__collapse-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

/* 折叠态下双箭头翻转，指向「展开」方向 */
.app-shell--sidebar-collapsed .app-shell__collapse-icon {
  transform: rotate(180deg);
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

/* 唯一的塌陷规则（spec「布局常量」）：第三栏在窄屏不再占列，检查器随之不渲染。
   手动折叠（inspector-collapsed）与这条窄屏自动隐藏正交：叠加不冲突。 */
@media (max-width: 1199px) {
  .app-shell--with-inspector {
    grid-template-columns: var(--app-shell-sidebar-width) minmax(0, 1fr);
  }

  .app-shell__inspector {
    display: none;
  }
}

/* 折叠/展开的宽度过渡：只在系统允许动效时进行，沿用既有动效纪律 */
@media (prefers-reduced-motion: no-preference) {
  .app-shell {
    transition: grid-template-columns 0.25s var(--wm-ease-rise);
  }

  .app-shell__collapse-icon {
    transition: transform 0.25s var(--wm-ease-rise);
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
