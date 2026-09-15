import { computed, type ComputedRef } from "vue";
import { useRoute } from "vue-router";
import { getModule, type ModuleDefinition } from "./modules";

export function useCurrentModule(): ComputedRef<ModuleDefinition | undefined> {
  const route = useRoute();
  return computed(() => getModule(route.meta.moduleId as string | undefined));
}
