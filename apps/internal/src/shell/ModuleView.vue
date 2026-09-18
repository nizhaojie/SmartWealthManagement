<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import AdvisoryWorkspace from "../advisory/AdvisoryWorkspace.vue";
import DataAnalysisWorkspace from "../analytics/DataAnalysisWorkspace.vue";
import CustomerRelationsPage from "../customer-relations/CustomerRelationsPage.vue";
import KnowledgeWorkspace from "../knowledge/KnowledgeWorkspace.vue";
import ProfileWorkspace from "../profile/ProfileWorkspace.vue";
import RiskMonitoringWorkspace from "../risk/RiskMonitoringWorkspace.vue";
import { useAuthStore } from "../stores/auth";
import WorkOrdersPage from "../work-orders/WorkOrdersPage.vue";
import ModuleForbidden from "./ModuleForbidden.vue";
import { getModule } from "./modules";

const route = useRoute();
const auth = useAuthStore();

const moduleDefinition = computed(() => getModule(route.meta.moduleId));

// 角色门控只有这一处：按 modules.ts 的 roles 判定。角色不足时保留 URL 与外壳、
// 渲染 ModuleForbidden，不做重定向。
const allowed = computed(() => {
  const module = moduleDefinition.value;
  const role = auth.currentEmployee?.employee_role;
  return Boolean(module && role && module.roles.includes(role));
});
</script>

<template>
  <ModuleForbidden v-if="moduleDefinition && !allowed" :module="moduleDefinition" />
  <KnowledgeWorkspace v-else-if="moduleDefinition?.id === 'knowledge'" />
  <DataAnalysisWorkspace v-else-if="moduleDefinition?.id === 'data-analysis'" />
  <ProfileWorkspace v-else-if="moduleDefinition?.id === 'profile'" />
  <AdvisoryWorkspace v-else-if="moduleDefinition?.id === 'advisory'" />
  <RiskMonitoringWorkspace v-else-if="moduleDefinition?.id === 'risk-monitoring'" />
  <WorkOrdersPage v-else-if="moduleDefinition?.id === 'work-orders'" />
  <CustomerRelationsPage v-else-if="moduleDefinition?.id === 'customer-relations'" />
</template>
