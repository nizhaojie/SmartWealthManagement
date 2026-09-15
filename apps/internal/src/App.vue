<script setup lang="ts">
import { onMounted, ref } from "vue";
import LoginPage from "./auth/LoginPage.vue";
import { isAuthenticated } from "./auth/store";
import { fetchHealth, type HealthSnapshot } from "./api/health";

const snapshot = ref<HealthSnapshot | null>(null);
const error = ref(false);

onMounted(async () => {
  try {
    snapshot.value = await fetchHealth();
  } catch {
    error.value = true;
  }
});
</script>

<template>
  <LoginPage v-if="!isAuthenticated" />
  <el-card v-else>
    <h1>内部工作台</h1>
    <p v-if="error">无法获取健康状态</p>
    <p v-else-if="snapshot">后端状态：{{ snapshot.status }}</p>
    <p v-else>加载中…</p>
  </el-card>
</template>
