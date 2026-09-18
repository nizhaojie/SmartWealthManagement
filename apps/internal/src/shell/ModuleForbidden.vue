<script setup lang="ts">
// 角色不足时的落点：保留当前 URL 与外壳，只把主区换成一句说明——不做重定向，
// 让人看得见自己「在哪」以及为什么这里打不开。
import { PanelCard } from "@wealth/shared";
import type { ModuleDefinition } from "./modules";

defineProps<{ module: ModuleDefinition }>();
</script>

<template>
  <PanelCard :title="module.label">
    <p class="forbidden" role="alert" data-testid="module-forbidden">
      你当前的角色无权访问「{{ module.label }}」模块。
    </p>
  </PanelCard>
</template>

<style scoped>
.forbidden {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.9rem;
  line-height: 1.75;
}
</style>
