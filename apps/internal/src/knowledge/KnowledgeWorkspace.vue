<script setup lang="ts">
import { ref } from "vue";
import { PageHeader } from "@wealth/shared";
import DocumentManagerPanel from "./DocumentManagerPanel.vue";
import RetrievalLabPanel from "./RetrievalLabPanel.vue";

// 一个模块两件事：文档的进出（管理）与检索质量（试验）。不注入检查器 → 第三栏塌成两栏。
const activeTab = ref("documents");
</script>

<template>
  <div class="knowledge">
    <PageHeader title="知识库管理" :breadcrumb="['知识库管理']" />

    <el-tabs v-model="activeTab" class="knowledge__tabs">
      <el-tab-pane label="文档管理" name="documents">
        <DocumentManagerPanel />
      </el-tab-pane>
      <el-tab-pane label="检索试验" name="lab" lazy>
        <RetrievalLabPanel />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.knowledge {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.knowledge__tabs :deep(.el-tabs__header) {
  margin-bottom: var(--wm-space-4);
}
</style>
