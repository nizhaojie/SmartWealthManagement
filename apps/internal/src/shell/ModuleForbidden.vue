<script setup lang="ts">
import { SectionCard } from "@wealth/shared";
import type { ModuleDefinition } from "./modules";

defineProps<{ module: ModuleDefinition }>();
</script>

<template>
  <SectionCard title="无权访问">
    <p role="alert">你当前的角色无权访问「{{ module.label }}」模块。</p>
  </SectionCard>
</template>
