<script setup lang="ts">
import { computed } from "vue";
import { currentEmployee } from "../auth/store";
import KnowledgeWorkspace from "../knowledge/KnowledgeWorkspace.vue";
import ModuleForbidden from "./ModuleForbidden.vue";
import ModulePlaceholder from "./ModulePlaceholder.vue";
import { useCurrentModule } from "./useCurrentModule";

// Role gating happens here rather than in the router guard so a denied
// module keeps its own URL and the shell chrome, instead of redirecting
// away to a generic forbidden route.
const module = useCurrentModule();
const allowed = computed(() => {
  if (!module.value || !currentEmployee.value) {
    return false;
  }
  return module.value.roles.includes(currentEmployee.value.employee_role);
});
</script>

<template>
  <ModuleForbidden v-if="module && !allowed" :module="module" />
  <KnowledgeWorkspace v-else-if="module?.id === 'knowledge'" />
  <ModulePlaceholder v-else-if="module" :module="module" />
</template>
