<script setup lang="ts">
import { onMounted, ref } from "vue";
import { fetchHealth, type HealthSnapshot } from "../api/health";

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
  <el-card>
    <h1>系统健康状态</h1>
    <p v-if="error">无法获取健康状态</p>
    <template v-else-if="snapshot">
      <p>总体：{{ snapshot.status === "ok" ? "正常" : "降级" }}</p>
      <ul>
        <li v-for="(item, name) in snapshot.dependencies" :key="name">
          {{ name }}：{{ item.ok ? "连通" : "断开" }}
        </li>
      </ul>
      <p>生成模型：{{ snapshot.llm_provider }}</p>
    </template>
    <p v-else>加载中…</p>
  </el-card>
</template>
