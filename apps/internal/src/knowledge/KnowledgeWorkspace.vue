<script setup lang="ts">
import KnowledgePage from "./KnowledgePage.vue";
import RetrievalLab from "./RetrievalLab.vue";
</script>

<template>
  <el-tabs>
    <el-tab-pane label="文档管理">
      <KnowledgePage />
    </el-tab-pane>
    <el-tab-pane label="检索试验" lazy>
      <RetrievalLab />
    </el-tab-pane>
  </el-tabs>
</template>
