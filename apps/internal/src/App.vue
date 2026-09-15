<script setup lang="ts">
import { watch } from "vue";
import { useRouter } from "vue-router";
import { currentEmployee, isAuthenticated } from "./auth/store";

const router = useRouter();

// A passive 401 from any API call clears tokens via the http client directly
// (see api/http.ts's onUnauthorized), bypassing auth/store.ts's own session
// helpers — so this is the one place that always resets identity + redirects.
watch(isAuthenticated, (authenticated) => {
  if (!authenticated) {
    currentEmployee.value = null;
    router.push("/login");
  }
});
</script>

<template>
  <router-view />
</template>
