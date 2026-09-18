import { ref } from "vue";
import { defineStore } from "pinia";

/**
 * 全局「当前客户」——它是 UI 状态（右侧检查器在看谁），不是领域概念。
 *
 * 命名纪律：不得叫「风险关注」。`CONTEXT.md` 里 **风险关注** 是精确的领域术语
 * （一个 Agent 留给其他 Agent 的提示记录），`GET /api/internal/risk-focus` 已占用该名字。
 */
export const useCurrentCustomerStore = defineStore("currentCustomer", () => {
  const currentCustomerId = ref<number | null>(null);

  function setCustomer(customerId: number | null): void {
    currentCustomerId.value = customerId;
  }

  function clear(): void {
    currentCustomerId.value = null;
  }

  return { currentCustomerId, setCustomer, clear };
});
