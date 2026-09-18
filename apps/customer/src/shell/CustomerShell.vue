<script setup lang="ts">
import { computed } from "vue";
import { ChatDotRound, Coin, Filter, Odometer } from "@element-plus/icons-vue";
import { useRoute, useRouter } from "vue-router";
import { AppShell, type AppShellNavItem } from "@wealth/shared";
import { useAuthStore } from "../stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const navItems: AppShellNavItem[] = [
  { key: "chat", label: "智能对话", name: "nav-chat", icon: ChatDotRound },
  { key: "risk-assessment", label: "风险测评", name: "nav-risk-assessment", icon: Odometer },
  { key: "products", label: "产品筛选", name: "nav-products", icon: Filter },
  { key: "assets", label: "我的资产", name: "nav-assets", icon: Coin },
];

const activeKey = computed(() => (typeof route.name === "string" ? route.name : ""));
// 顶栏左侧的页面标题：壳不认识模块名，key → 标题的映射留在应用里。
const activeLabel = computed(
  () => navItems.find((item) => item.key === activeKey.value)?.label ?? "",
);

function onSelect(key: string): void {
  void router.push(`/${key}`);
}

async function onLogout(): Promise<void> {
  // 登出请求失败也要走：令牌在 store 的 finally 里已经清掉，
  // 把人留在原页面只会让他看着一个必然报错的界面。
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
    brand-subtitle="Wealth Copilot"
    @select="onSelect"
    @logout="onLogout"
  >
    <template #brand>智能财富管家</template>
    <template #topbar-left>
      <span class="shell__crumb">{{ activeLabel }}</span>
    </template>

    <template #topbar-right>
      <span v-if="auth.currentUsername" class="shell__identity" data-testid="current-customer">
        {{ auth.currentUsername }}
      </span>
    </template>

    <div class="shell__content">
      <router-view />
    </div>
  </AppShell>
</template>

<style scoped>
/* 客户侧两栏：不提供 inspector 插槽（壳据此渲染两栏），主区限宽居中。
   客户看不到预警等级与处置动作——客户可见视图的边界。 */
.shell__content {
  max-width: var(--wm-content-max-width);
  margin: 0 auto;
}

.shell__crumb {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--wm-text-primary);
}

/* 登出按钮左侧的当前用户名（客户登录时填写的账号）：弱化到 muted，不抢页面标题的视线 */
.shell__identity {
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  white-space: nowrap;
}
</style>
