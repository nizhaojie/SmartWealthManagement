<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { AppShell, type AppShellNavItem } from "@wealth/shared";
import { useAuthStore } from "../stores/auth";
import { iconForModule } from "./moduleIcons";
import { getModule, visibleModules } from "./modules";
import { providePageSlots } from "./pageSlots";
import RiskAlertSummaryCard from "./RiskAlertSummaryCard.vue";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

// 壳把两个注入通道交给页面；没有页面注入检查器时 AppShell 自动塌成两栏。
const pageSlots = providePageSlots();

const navItems = computed<AppShellNavItem[]>(() =>
  visibleModules(auth.currentEmployee?.employee_role).map((module) => ({
    key: module.id,
    label: module.label,
    name: `nav-${module.id}`,
    icon: iconForModule(module.id),
  })),
);

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
.shell__content {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
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
</style>
