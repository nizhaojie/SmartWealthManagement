<script setup lang="ts">
import type { ModuleDefinition } from "./modules";

defineProps<{ module: ModuleDefinition }>();
</script>

<template>
  <el-card>
    <h2 role="alert">无权访问</h2>
    <p>你当前的角色无权访问「{{ module.label }}」模块。</p>
  </el-card>
</template>
