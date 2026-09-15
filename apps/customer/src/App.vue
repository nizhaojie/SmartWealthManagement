<script setup lang="ts">
import LoginPage from "./auth/LoginPage.vue";
import { isAuthenticated, logout } from "./auth/store";
import HealthPage from "./health/HealthPage.vue";
</script>

<template>
  <LoginPage v-if="!isAuthenticated" />
  <div v-else>
    <el-button @click="logout">登出</el-button>
    <HealthPage />
  </div>
</template>
