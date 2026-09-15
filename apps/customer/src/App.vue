<script setup lang="ts">
import ChatPage from "./chat/ChatPage.vue";
import LoginPage from "./auth/LoginPage.vue";
import { isAuthenticated, logout } from "./auth/store";
</script>

<template>
  <LoginPage v-if="!isAuthenticated" />
  <div v-else>
    <el-button @click="logout">登出</el-button>
    <ChatPage />
  </div>
</template>
