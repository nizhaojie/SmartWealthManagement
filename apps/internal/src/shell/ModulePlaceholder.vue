<script setup lang="ts">
import { SectionCard } from "@wealth/shared";
import type { ModuleDefinition } from "./modules";

defineProps<{ module: ModuleDefinition }>();
</script>

<template>
  <SectionCard :title="module.label">
    <p>该模块尚未实现。</p>
    <p>{{ module.description }}</p>
  </SectionCard>
</template>
