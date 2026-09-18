// 当前客户：跨页面共享的 UI 状态（画像 / 投顾助手 / 审核页 / 工单详情共用同一份）。
//
// 命名纪律：这个全局态叫「当前客户」，不得叫「风险关注」——后者是 CONTEXT.md 里的
// 领域术语（一个 Agent 留给其他 Agent 的提示记录），且已被 GET /api/internal/risk-focus 占用。
//
// 这里只存 id：客户的画像、持仓、预警分别由检查器自己的三个请求拉取，
// 不把接口返回的业务对象囤进 store（那会让缓存失效变成新的隐式耦合）。
import { ref } from "vue";
import { defineStore } from "pinia";

export const useCurrentCustomerStore = defineStore("currentCustomer", () => {
  const currentCustomerId = ref<string | null>(null);

  function setCustomer(customerId: string): void {
    currentCustomerId.value = customerId;
  }

  function clear(): void {
    currentCustomerId.value = null;
  }

  return { currentCustomerId, setCustomer, clear };
});
