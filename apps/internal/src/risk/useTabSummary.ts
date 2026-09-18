import { onMounted, watchEffect } from "vue";
import type { TabSummary } from "./riskView";

/**
 * 把本页签的筛选摘要写回工作区——右侧检查器显示的就是它。
 *
 * 放在 onMounted + post flush 里：emit 若发生在渲染过程中，就等于在别人的
 * render 里改别人的响应式状态。
 */
export function useTabSummary(
  emit: (value: TabSummary) => void,
  source: () => TabSummary,
): void {
  onMounted(() => {
    watchEffect(() => emit(source()), { flush: "post" });
  });
}
