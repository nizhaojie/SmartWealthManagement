<script setup lang="ts">
import { PanelCard } from "@wealth/shared";
import type { ModuleDefinition } from "./modules";

defineProps<{ module: ModuleDefinition }>();
</script>

<template>
  <PanelCard title="无权访问">
    <p role="alert">你当前的角色无权访问「{{ module.label }}」模块。</p>
  </PanelCard>
</template>
