<script setup lang="ts">
import { PanelCard } from "@wealth/shared";
import type { ModuleDefinition } from "./modules";

defineProps<{ module: ModuleDefinition }>();
</script>

<template>
  <PanelCard :title="module.label">
    <p>该模块尚未实现。</p>
    <p>{{ module.description }}</p>
  </PanelCard>
</template>
