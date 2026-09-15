<script setup lang="ts">
import { ref } from "vue";
import AssetsPage from "./assets/AssetsPage.vue";
import ChatPage from "./chat/ChatPage.vue";
import LoginPage from "./auth/LoginPage.vue";
import ProductScreeningPage from "./products/ProductScreeningPage.vue";
import RiskAssessmentWorkspace from "./risk-assessment/RiskAssessmentWorkspace.vue";
import { isAuthenticated, logout } from "./auth/store";

type CustomerView = "chat" | "risk-assessment" | "products" | "assets";

const currentView = ref<CustomerView>("chat");
</script>

<template>
  <LoginPage v-if="!isAuthenticated" />
  <div v-else>
    <nav>
      <el-button name="nav-chat" @click="currentView = 'chat'">智能客服</el-button>
      <el-button name="nav-risk-assessment" @click="currentView = 'risk-assessment'">风险测评</el-button>
      <el-button name="nav-products" @click="currentView = 'products'">产品筛选</el-button>
      <el-button name="nav-assets" @click="currentView = 'assets'">我的资产</el-button>
      <el-button name="logout" @click="logout">登出</el-button>
    </nav>
    <ChatPage v-if="currentView === 'chat'" />
    <RiskAssessmentWorkspace v-else-if="currentView === 'risk-assessment'" />
    <AssetsPage v-else-if="currentView === 'assets'" />
    <ProductScreeningPage v-else />
  </div>
</template>
