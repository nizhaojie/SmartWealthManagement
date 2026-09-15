<script setup lang="ts">
import type { ModuleDefinition } from "./modules";

defineProps<{ module: ModuleDefinition }>();
</script>

<template>
  <el-card>
    <h2>{{ module.label }}</h2>
    <p>该模块尚未实现。</p>
    <p>{{ module.description }}</p>
  </el-card>
</template>
