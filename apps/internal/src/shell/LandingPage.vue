<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { PageHeader, PanelCard } from "@wealth/shared";
import { useAuthStore } from "../stores/auth";
import { iconForModule } from "./moduleIcons";
import { visibleModules } from "./modules";

/**
 * 落地页：只列登录者可见模块的入口卡，零业务数据聚合。
 * 无可见模块是正常页面状态（空态说明），不是错误。
 */
const router = useRouter();
const auth = useAuthStore();

const modules = computed(() => visibleModules(auth.currentEmployee?.employee_role));

function open(path: string): void {
  void router.push(path);
}
</script>

<template>
  <div class="landing">
    <PageHeader title="工作台" :breadcrumb="['工作台']" />

    <PanelCard title="请选择一个模块开始工作">
      <ul v-if="modules.length" class="landing__grid">
        <li v-for="module in modules" :key="module.id">
          <button
            type="button"
            class="landing__card"
            :name="`module-${module.id}`"
            :data-testid="`landing-${module.id}`"
            @click="open(module.path)"
          >
            <span class="landing__icon" aria-hidden="true">
              <component :is="iconForModule(module.id)" />
            </span>
            <span class="landing__label">{{ module.label }}</span>
            <span class="landing__desc">{{ module.description }}</span>
          </button>
        </li>
      </ul>
      <p v-else class="landing__empty" data-testid="no-visible-modules">
        当前账号没有可见模块，请联系管理员开通模块权限。
      </p>
    </PanelCard>
  </div>
</template>

<style scoped>
.landing {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.landing__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(calc(var(--wm-space-6) * 7), 1fr));
  gap: var(--wm-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.landing__card {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  width: 100%;
  height: 100%;
  padding: var(--wm-space-4);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-card);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease;
}

.landing__card:hover {
  border-color: var(--wm-color-primary);
}

.landing__icon {
  display: grid;
  place-items: center;
  width: var(--wm-space-6);
  height: var(--wm-space-6);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-color-primary-tint);
  /* 淡染底上的图形走 primary-strong（primary 本身在浅底上不足 4.5:1） */
  color: var(--wm-color-primary-strong);
  font-size: 1.05rem;
}

.landing__label {
  color: var(--wm-text-primary);
  font-size: 0.95rem;
  font-weight: 600;
}

.landing__desc {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
  line-height: 1.7;
}

.landing__empty {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.9rem;
  line-height: 1.75;
}
</style>
