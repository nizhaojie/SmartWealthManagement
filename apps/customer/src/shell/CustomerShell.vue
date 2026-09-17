<script setup lang="ts">
import { ChatDotRound, Coin, Filter, Odometer } from "@element-plus/icons-vue";
import { useRoute, useRouter } from "vue-router";
import { AppShell, type AppShellNavItem } from "@wealth/shared";
import { logout } from "../auth/store";

const route = useRoute();
const router = useRouter();

const navItems: AppShellNavItem[] = [
  { key: "chat", label: "智能客服", name: "nav-chat", icon: ChatDotRound },
  { key: "risk-assessment", label: "风险测评", name: "nav-risk-assessment", icon: Odometer },
  { key: "products", label: "产品筛选", name: "nav-products", icon: Filter },
  { key: "assets", label: "我的资产", name: "nav-assets", icon: Coin },
];

function onSelect(key: string) {
  void router.push(`/${key}`);
}

async function onLogout() {
  await logout();
  await router.push({ name: "login" });
}
</script>

<template>
  <AppShell
    :nav-items="navItems"
    :active-key="(route.name as string) ?? ''"
    @select="onSelect"
    @logout="onLogout"
  >
    <template #brand>智能财富管家</template>
    <router-view />
  </AppShell>
</template>
