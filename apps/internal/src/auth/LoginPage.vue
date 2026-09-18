<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ApiError } from "@wealth/shared";
import type { FormInstance, FormRules } from "element-plus";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const auth = useAuthStore();

const formRef = ref<FormInstance | null>(null);
const form = reactive({ username: "", password: "" });

// 校验交给 el-form 的 rules，错误就地显示在字段下方——不用 toast。
const rules: FormRules = {
  username: [{ required: true, message: "请输入账号", trigger: "blur" }],
  password: [{ required: true, message: "请输入密码", trigger: "blur" }],
};

const errorMessage = ref("");
const submitting = ref(false);

async function onSubmit(): Promise<void> {
  errorMessage.value = "";
  if (!formRef.value) {
    return;
  }
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) {
    return;
  }

  submitting.value = true;
  try {
    // 登录 = 换令牌 + GET /api/internal/auth/me 拿到身份；任一步失败都是登录失败。
    await auth.login(form.username, form.password);
    await router.push({ path: "/" });
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError && error.code === 401
        ? "账号或密码错误"
        : "登录失败，请稍后重试";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="login">
    <section class="login__brand">
      <div class="login__logo" aria-hidden="true">内</div>
      <h1 class="login__brand-title">智能财富管家</h1>
      <p class="login__brand-subtitle">Internal Workbench</p>
      <ul class="login__points">
        <li>知识库、受限数据分析与客户画像，一个工作台内切换</li>
        <li>投顾内容经理财顾问审核放行后，才允许送达客户</li>
        <li>风控预警由风控专员处置，每次流转都留下理由</li>
      </ul>
    </section>

    <section class="login__panel">
      <div class="login__card">
        <header class="login__card-head">
          <h2 class="login__card-title">员工登录</h2>
          <p class="login__card-desc">
            可见模块由员工角色决定。登录后按你的角色进入内部工作台。
          </p>
        </header>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          class="login__form"
          @submit.prevent="onSubmit"
        >
          <el-form-item label="账号" prop="username">
            <el-input
              v-model="form.username"
              name="username"
              autocomplete="username"
              placeholder="请输入员工账号"
            />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              name="password"
              type="password"
              show-password
              autocomplete="current-password"
              placeholder="请输入密码"
            />
          </el-form-item>

          <p v-if="errorMessage" class="login__error" role="alert" data-testid="login-error">
            {{ errorMessage }}
          </p>

          <el-button
            type="primary"
            native-type="submit"
            class="login__submit"
            :loading="submitting"
          >
            登录
          </el-button>
        </el-form>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* 整屏两栏：左品牌区 + 右登录卡，纯 CSS，无图片资源。 */
.login {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  min-height: 100vh;
  background-color: var(--wm-bg-page);
}

.login__brand {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--wm-space-3);
  padding: var(--wm-space-6);
  background-image: linear-gradient(
    160deg,
    var(--wm-color-primary) 0%,
    var(--wm-color-primary-strong) 100%
  );
  color: var(--wm-color-primary-fg);
}

.login__logo {
  display: grid;
  place-items: center;
  width: var(--wm-space-6);
  height: var(--wm-space-6);
  border-radius: var(--wm-radius-md);
  background-color: color-mix(in srgb, var(--wm-color-primary-fg) 18%, transparent);
  color: var(--wm-color-primary-fg);
  font-size: 1.1rem;
  font-weight: 700;
}

.login__brand-title {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.login__brand-subtitle {
  margin: 0;
  font-size: 0.7rem;
  font-weight: 500;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  opacity: 0.75;
}

.login__points {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin: var(--wm-space-4) 0 0;
  padding: 0;
  list-style: none;
  font-size: 0.85rem;
  line-height: 1.7;
  opacity: 0.92;
}

.login__points li::before {
  content: "·";
  margin-right: var(--wm-space-2);
  opacity: 0.6;
}

.login__panel {
  display: grid;
  place-items: center;
  padding: var(--wm-space-6);
}

.login__card {
  position: relative;
  width: 100%;
  max-width: calc(var(--wm-space-6) * 12);
  padding: var(--wm-space-6);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-card);
  box-shadow: var(--wm-shadow-card);
}

/* 02 的面板发丝渐变线（与 PanelCard 同一手法，登录卡不在壳内因此自带一条） */
.login__card::after {
  content: "";
  position: absolute;
  top: 0;
  left: var(--wm-space-4);
  right: var(--wm-space-4);
  height: 1px;
  pointer-events: none;
  background: linear-gradient(90deg, transparent, var(--wm-color-primary), transparent);
  opacity: 0.26;
}

.login__card-head {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  margin-bottom: var(--wm-space-5);
}

.login__card-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--wm-text-primary);
}

.login__card-desc {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.7;
  color: var(--wm-text-muted);
}

.login__error {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.login__submit {
  width: 100%;
}

/* 窄屏只留登录卡：唯一一条响应式规则，与令牌层的收窄规则同一量级 */
@media (max-width: 900px) {
  .login {
    grid-template-columns: minmax(0, 1fr);
  }

  .login__brand {
    display: none;
  }
}
</style>
