<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { currentEmployee } from "../auth/store";
import { visibleModules } from "./modules";
import { iconForModule } from "./moduleIcons";

// 静态模块导航落地页：只渲染登录者可见模块的入口卡片，
// 不聚合任何业务数据（见 frontend-restyle spec「外壳与落地页」）。
const router = useRouter();

const modules = computed(() =>
  currentEmployee.value ? visibleModules(currentEmployee.value.employee_role) : []
);

function enter(path: string) {
  void router.push(path);
}
</script>

<template>
  <div class="landing">
    <h2 class="landing__title">请选择一个模块开始工作</h2>
    <div v-if="modules.length > 0" class="landing__grid">
      <button
        v-for="module in modules"
        :key="module.id"
        type="button"
        class="module-entry"
        @click="enter(module.path)"
      >
        <span class="module-entry__icon">
          <component :is="iconForModule(module.id)" />
        </span>
        <span class="module-entry__label">{{ module.label }}</span>
        <span class="module-entry__description">{{ module.description }}</span>
      </button>
    </div>
    <!-- 空态是正常页面而非错误：与占位模块同一原则 -->
    <p v-else class="landing__empty">当前账号没有可见模块，请联系管理员开通模块权限。</p>
  </div>
</template>

<style scoped>
.landing__title {
  margin: 0 0 var(--wm-space-5);
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--wm-text-primary);
}

.landing__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--wm-space-4);
}

.module-entry {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--wm-space-2);
  padding: var(--wm-space-5);
  /* 1px 细线:令牌纪律声明的极少数例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-card);
  box-shadow: var(--wm-shadow-card);
  text-align: left;
  cursor: pointer;
}

.module-entry:hover {
  box-shadow: var(--wm-shadow-overlay);
}

.module-entry__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--wm-space-6);
  height: var(--wm-space-6);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-color-primary-tint);
  color: var(--wm-color-primary);
}

.module-entry__icon svg {
  width: var(--wm-space-4);
  height: var(--wm-space-4);
}

.module-entry__label {
  font-weight: 600;
  color: var(--wm-text-primary);
}

.module-entry__description {
  color: var(--wm-text-muted);
  font-size: 0.9rem;
  line-height: 1.5;
}

.landing__empty {
  margin: 0;
  padding: var(--wm-space-6);
  /* 1px 细线:令牌纪律声明的极少数例外 */
  border: 1px dashed var(--wm-border);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-card);
  color: var(--wm-text-muted);
}
</style>
