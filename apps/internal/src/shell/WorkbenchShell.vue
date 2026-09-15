<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { currentEmployee, logout } from "../auth/store";
import { visibleModules } from "./modules";
import { useCurrentModule } from "./useCurrentModule";

const route = useRoute();

const modules = computed(() =>
  currentEmployee.value ? visibleModules(currentEmployee.value.employee_role) : []
);
const currentModule = useCurrentModule();
</script>

<template>
  <el-container class="workbench-shell">
    <el-aside width="220px" class="workbench-shell__aside">
      <div class="workbench-shell__brand">内部工作台</div>
      <el-menu :default-active="route.path" router background-color="#001529" text-color="#fff" active-text-color="#409eff">
        <el-menu-item v-for="module in modules" :key="module.id" :index="module.path">
          {{ module.label }}
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="workbench-shell__header">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item>工作台</el-breadcrumb-item>
          <el-breadcrumb-item v-if="currentModule">{{ currentModule.label }}</el-breadcrumb-item>
        </el-breadcrumb>
        <div class="workbench-shell__identity">
          <span v-if="currentEmployee">{{ currentEmployee.real_name }} · {{ currentEmployee.employee_role }}</span>
          <el-button size="small" name="logout" @click="logout">登出</el-button>
        </div>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.workbench-shell {
  height: 100vh;
}

.workbench-shell__aside {
  background-color: #001529;
  color: #fff;
}

.workbench-shell__brand {
  color: #fff;
  padding: 16px;
  font-weight: bold;
}

.workbench-shell__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.workbench-shell__identity {
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
