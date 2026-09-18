<script setup lang="ts">
// 页面头：面包屑 + 页面标题 + 右侧操作区。面包屑段由调用方给，组件不认识任何模块名。
import { useSlots } from "vue";

withDefaults(
  defineProps<{
    title: string;
    /** 面包屑段，按顺序渲染，最后一段是当前项。空数组则不渲染面包屑。 */
    breadcrumb?: string[];
  }>(),
  {
    breadcrumb: () => [],
  },
);

const slots = useSlots();
</script>

<template>
  <header class="page-header" data-testid="page-header">
    <nav v-if="breadcrumb.length" class="page-header__breadcrumb" aria-label="面包屑">
      <template v-for="(crumb, index) in breadcrumb" :key="`${index}-${crumb}`">
        <span v-if="index > 0" class="page-header__crumb-separator" aria-hidden="true">/</span>
        <strong v-if="index === breadcrumb.length - 1" class="page-header__crumb-current">
          {{ crumb }}
        </strong>
        <span v-else class="page-header__crumb">{{ crumb }}</span>
      </template>
    </nav>
    <div class="page-header__row">
      <h1 class="page-header__title">{{ title }}</h1>
      <div v-if="slots.actions" class="page-header__actions">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
}

.page-header__breadcrumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--wm-space-2);
  font-size: 0.8rem;
  color: var(--wm-text-muted);
}

/* 分隔符是纯装饰（aria-hidden），落在 --wm-text-placeholder 的豁免范围内 */
.page-header__crumb-separator {
  color: var(--wm-text-placeholder);
}

.page-header__crumb-current {
  color: var(--wm-text-primary);
  font-weight: 600;
}

.page-header__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--wm-space-4);
}

.page-header__title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--wm-text-primary);
}

.page-header__actions {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
  min-width: 0;
}
</style>
