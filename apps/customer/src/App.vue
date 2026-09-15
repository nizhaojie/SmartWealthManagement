<script setup lang="ts">
import { ref } from "vue";
import ChatPage from "./chat/ChatPage.vue";
import LoginPage from "./auth/LoginPage.vue";
import RiskAssessmentWorkspace from "./risk-assessment/RiskAssessmentWorkspace.vue";
import { isAuthenticated, logout } from "./auth/store";

type CustomerView = "chat" | "risk-assessment";

const currentView = ref<CustomerView>("chat");
</script>

<template>
  <LoginPage v-if="!isAuthenticated" />
  <div v-else>
    <nav>
      <el-button name="nav-chat" @click="currentView = 'chat'">智能客服</el-button>
      <el-button name="nav-risk-assessment" @click="currentView = 'risk-assessment'">风险测评</el-button>
      <el-button name="logout" @click="logout">登出</el-button>
    </nav>
    <ChatPage v-if="currentView === 'chat'" />
    <RiskAssessmentWorkspace v-else />
  </div>
</template>
