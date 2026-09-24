<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { AppShell, type AppShellNavItem } from "@wealth/shared";
import { useAdvisoryQueueStore } from "../advisory/queueStore";
import { useAuthStore } from "../stores/auth";
import { useLayoutStore } from "../stores/layout";
import { iconForModule } from "./moduleIcons";
import { getModule, visibleModules } from "./modules";
import { providePageSlots } from "./pageSlots";
import RiskAlertSummaryCard from "./RiskAlertSummaryCard.vue";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const layout = useLayoutStore();
// 待办计数的唯一来源，与审核页卡片标题读的是同一份（见 advisory/queueStore）。
const queue = useAdvisoryQueueStore();

// 壳把两个注入通道交给页面；没有页面注入检查器时 AppShell 自动塌成两栏。
const pageSlots = providePageSlots();

// 折叠状态归 layout store 持有：AppShell 是受控组件，侧栏触发条点击后 emit
// update:sidebarCollapsed，这里用 v-model 把它接回 store 写回 localStorage。
// 检查器折叠是纯 prop（开关在顶栏），直接读 store 的布尔。
const sidebarCollapsed = computed({
  get: () => layout.sidebarCollapsed,
  set: (next: boolean) => layout.setSidebarCollapsed(next),
});

const navItems = computed<AppShellNavItem[]>(() =>
  visibleModules(auth.currentEmployee?.employee_role).map((module) => ({
    key: module.id,
    label: module.label,
    name: `nav-${module.id}`,
    icon: iconForModule(module.id),
    // 角标只挂「投顾助手」一项，而它本身只对理财顾问可见（modules.ts），
    // 因此角色隔离跟着模块可见性走，不另加判断。
    // 取数失败或计数为 0 时这里是 undefined：壳的 v-if 一并覆盖，不渲染 0。
    badge: module.id === "advisory" ? queue.pendingReviewCount : undefined,
  })),
);

// 进壳就拉一次：角标不能等到顾问点进投顾助手才出现，那正是它要避免的事。
// 之后只在审核动作成功后刷新——不加轮询，工作台开着不动时新内容不会自己冒出来。
onMounted(() => {
  void queue.refresh();
});

const currentModule = computed(() => getModule(route.meta.moduleId));
const activeKey = computed(() => currentModule.value?.id ?? "");

// 面包屑：当前模块 / 当前页面。模块首页只有一段，详情页才有第二段。
const breadcrumbs = computed<string[]>(() => {
  const module = currentModule.value;
  if (!module) return [route.meta.pageLabel ?? "工作台"];
  return route.meta.pageLabel ? [module.label, route.meta.pageLabel] : [module.label];
});

function onSelect(key: string): void {
  const module = getModule(key);
  if (module) {
    void router.push(module.path);
  }
}

async function onLogout(): Promise<void> {
  try {
    await auth.logout();
  } finally {
    await router.push({ name: "login" });
  }
}
</script>

<template>
  <AppShell
    v-model:sidebar-collapsed="sidebarCollapsed"
    :inspector-collapsed="layout.inspectorCollapsed"
    :nav-items="navItems"
    :active-key="activeKey"
    brand-subtitle="Internal Workbench"
    @select="onSelect"
    @logout="onLogout"
  >
    <template #brand>内部工作台</template>

    <template #topbar-left>
      <nav class="shell__breadcrumb" aria-label="面包屑" data-testid="breadcrumb">
        <template v-for="(crumb, index) in breadcrumbs" :key="`${index}-${crumb}`">
          <span v-if="index > 0" class="shell__crumb-separator" aria-hidden="true">/</span>
          <strong
            v-if="index === breadcrumbs.length - 1"
            class="shell__crumb-current"
            data-testid="breadcrumb-current"
          >
            {{ crumb }}
          </strong>
          <span v-else class="shell__crumb">{{ crumb }}</span>
        </template>
      </nav>
    </template>

    <template #topbar-right>
      <component
        :is="pageSlots.topbarActions.value.component"
        v-if="pageSlots.topbarActions.value"
        v-bind="pageSlots.topbarActions.value.props"
      />
      <span class="shell__identity" data-testid="current-employee">
        {{ auth.currentEmployee?.real_name }} · {{ auth.currentEmployee?.employee_role }}
      </span>
      <!-- 检查器开关只在页面注入检查器时出现；折叠是壳布局偏好，与页面是否注入是两回事。
           「检查器」这个词留在应用层，shared 只认 inspectorCollapsed 布尔。 -->
      <button
        v-if="pageSlots.inspector.value"
        type="button"
        class="shell__inspector-toggle"
        data-testid="inspector-toggle"
        :aria-expanded="!layout.inspectorCollapsed"
        @click="layout.toggleInspector()"
      >
        {{ layout.inspectorCollapsed ? "展开检查器" : "收起检查器" }}
      </button>
    </template>

    <template #sidebar-footer>
      <RiskAlertSummaryCard />
    </template>

    <template v-if="pageSlots.inspector.value" #inspector>
      <component
        :is="pageSlots.inspector.value.component"
        v-bind="pageSlots.inspector.value.props"
      />
    </template>

    <div class="shell__content">
      <router-view />
    </div>
  </AppShell>
</template>

<style scoped>
/* 内容区至少铺满 AppShell 给的可用高度。页根元素是挂在这一层下的，而这一层是
   `height: auto`——它只跟内容一样高，于是「要占满高度」的页根（数据分析的对话面板）
   拿不到可依的高度，`height: 100%` 在它这里静默解析成 auto，面板就退化成跟内容一样高。
   给一个下限即可：页根改用 `flex: 1` 吸收剩余高度，也就是内容区的整块可用高度。
   内容更高的页面照旧把它撑高（min-height 不是 height，不截断内容），外层滚动条行为不变。 */
.shell__content {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
  min-height: 100%;
}

.shell__breadcrumb {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
  font-size: 0.85rem;
  color: var(--wm-text-muted);
}

/* 分隔符是纯装饰（aria-hidden），落在 --wm-text-placeholder 的豁免范围内 */
.shell__crumb-separator {
  color: var(--wm-text-placeholder);
}

.shell__crumb-current {
  color: var(--wm-text-primary);
  font-weight: 600;
}

.shell__identity {
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  white-space: nowrap;
}

/* 检查器开关：与登出、页面级操作同源的次级按钮观感，aria-expanded 反映检查器展开态 */
.shell__inspector-toggle {
  padding: var(--wm-space-1) var(--wm-space-3);
  border: none;
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-color-primary-soft);
  color: var(--wm-color-primary);
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
}

.shell__inspector-toggle:hover {
  background-color: color-mix(in srgb, var(--wm-color-primary) 10%, white);
  color: var(--wm-color-primary-strong);
}
</style>
