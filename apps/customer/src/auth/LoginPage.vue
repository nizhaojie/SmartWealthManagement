<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { PanelCard } from "@wealth/shared";
import { login } from "./store";

const router = useRouter();

const username = ref("");
const password = ref("");
const errorMessage = ref("");
const submitting = ref(false);

async function onSubmit() {
  errorMessage.value = "";
  submitting.value = true;
  try {
    await login(username.value, password.value);
    await router.push({ name: "chat" });
  } catch {
    errorMessage.value = "账号或密码错误";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <PanelCard title="客户登录" class="login-card">
    <form @submit.prevent="onSubmit">
      <el-form-item label="账号">
        <el-input v-model="username" name="username" />
      </el-form-item>
      <el-form-item label="密码">
        <el-input v-model="password" name="password" type="password" />
      </el-form-item>
      <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
      <el-button type="primary" native-type="submit" :loading="submitting">登录</el-button>
    </form>
  </PanelCard>
</template>

<style scoped>
/* 登录卡独立于 AppShell 页面流，居中窄卡即可 */
.login-card {
  max-width: 420px;
  margin: var(--wm-space-6) auto;
}
</style>
