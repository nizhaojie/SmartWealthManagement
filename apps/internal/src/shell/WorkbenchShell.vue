<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { AppShell, type AppShellNavItem } from "@wealth/shared";
import { currentEmployee, logout } from "../auth/store";
import { getModule, visibleModules } from "./modules";
import { iconForModule } from "./moduleIcons";
import { useCurrentModule } from "./useCurrentModule";

const router = useRouter();

const navItems = computed<AppShellNavItem[]>(() =>
  (currentEmployee.value ? visibleModules(currentEmployee.value.employee_role) : []).map(
    (module) => ({
      key: module.id,
      label: module.label,
      icon: iconForModule(module.id),
    }),
  ),
);
const currentModule = useCurrentModule();

function onSelect(key: string) {
  const module = getModule(key);
  if (module) {
    void router.push(module.path);
  }
}
</script>

<template>
  <AppShell
    :nav-items="navItems"
    :active-key="currentModule?.id"
    @select="onSelect"
    @logout="logout"
  >
    <template #brand>内部工作台</template>
    <template #topbar-left>
      <el-breadcrumb separator="/">
        <el-breadcrumb-item>工作台</el-breadcrumb-item>
        <el-breadcrumb-item v-if="currentModule">{{ currentModule.label }}</el-breadcrumb-item>
      </el-breadcrumb>
    </template>
    <template #topbar-right>
      <span v-if="currentEmployee" class="workbench-shell__identity">
        {{ currentEmployee.real_name }} · {{ currentEmployee.employee_role }}
      </span>
    </template>
    <router-view />
  </AppShell>
</template>

<style scoped>
.workbench-shell__identity {
  color: var(--wm-text-secondary);
}
</style>
