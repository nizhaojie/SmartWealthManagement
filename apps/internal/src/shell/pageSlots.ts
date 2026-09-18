import {
  inject,
  onMounted,
  onUnmounted,
  provide,
  shallowRef,
  watchEffect,
  type Component,
  type InjectionKey,
  type ShallowRef,
} from "vue";

/**
 * 页面往壳里注入内容的两个通道（右侧检查器、顶栏页面级操作）。
 *
 * 壳负责把 AppShell 的插槽渲染出来，但「哪个页面注入什么」只有页面自己知道——
 * 风控的筛选摘要就活在风控页自己的 state 里。因此用 provide/inject 把注册入口交给
 * 页面：页面在 setup 里声明自己那一段，壳按需渲染。没有页面注入时 inspector 为空，
 * AppShell 据此自动塌成两栏（三栏与否只有一个来源）。
 *
 * 不放进 Pinia：这是「当前路由那一个页面」的局部状态，塞进全局 store 只会多一份
 * 需要手动清理的全局态。
 */
export type PageSlotEntry = {
  component: Component;
  props?: Record<string, unknown>;
};

export type PageSlots = {
  inspector: ShallowRef<PageSlotEntry | null>;
  topbarActions: ShallowRef<PageSlotEntry | null>;
  setInspector: (entry: PageSlotEntry | null) => void;
  setTopbarActions: (entry: PageSlotEntry | null) => void;
};

const PAGE_SLOTS: InjectionKey<PageSlots> = Symbol("internal-page-slots");

export function providePageSlots(): PageSlots {
  const inspector = shallowRef<PageSlotEntry | null>(null);
  const topbarActions = shallowRef<PageSlotEntry | null>(null);

  const slots: PageSlots = {
    inspector,
    topbarActions,
    setInspector(entry) {
      inspector.value = entry;
    },
    setTopbarActions(entry) {
      topbarActions.value = entry;
    },
  };

  provide(PAGE_SLOTS, slots);
  return slots;
}

function usePageSlot(
  channel: "inspector" | "topbarActions",
  source: () => PageSlotEntry | null,
): void {
  const slots = inject(PAGE_SLOTS, null);
  if (!slots) {
    // 页面被单独挂载（组件测试）时没有壳，注入静默跳过。
    return;
  }
  const apply = channel === "inspector" ? slots.setInspector : slots.setTopbarActions;

  let stop: (() => void) | null = null;
  onMounted(() => {
    // post flush：等这一次渲染落定再写壳的状态，避免在渲染过程中改别人的响应式数据。
    stop = watchEffect(() => apply(source()), { flush: "post" });
  });
  onUnmounted(() => {
    stop?.();
    apply(null);
  });
}

/** 注入右侧检查器。`source` 返回 null 表示这个页面没有检查器（第三栏塌成两栏）。 */
export function useInspector(source: () => PageSlotEntry | null): void {
  usePageSlot("inspector", source);
}

/** 注入顶栏右侧的页面级操作。 */
export function useTopbarActions(source: () => PageSlotEntry | null): void {
  usePageSlot("topbarActions", source);
}
