<script setup lang="ts">
import { computed } from "vue";
import AdvisoryWorkspace from "../advisory/AdvisoryWorkspace.vue";
import DataAnalysisWorkspace from "../analytics/DataAnalysisWorkspace.vue";
import { currentEmployee } from "../auth/store";
import KnowledgeWorkspace from "../knowledge/KnowledgeWorkspace.vue";
import ProfileWorkspace from "../profile/ProfileWorkspace.vue";
import RiskMonitoringWorkspace from "../risk/RiskMonitoringWorkspace.vue";
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
  <DataAnalysisWorkspace v-else-if="module?.id === 'data-analysis'" />
  <ProfileWorkspace v-else-if="module?.id === 'profile'" />
  <AdvisoryWorkspace v-else-if="module?.id === 'advisory'" />
  <RiskMonitoringWorkspace v-else-if="module?.id === 'risk-monitoring'" />
  <ModulePlaceholder v-else-if="module" :module="module" />
</template>
