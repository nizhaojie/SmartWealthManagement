import { defineComponent, h, type Component } from "vue";
import { ElButton } from "element-plus";

/**
 * 顶栏「页面级操作」的最小载体：一个按钮。
 *
 * 壳只负责把它渲染在右槽里，按钮调什么由页面接——壳不认识任何业务动作。
 * 用组件而不是渲染函数，是为了让提供者与消费方都只面对一个 Vue 组件边界。
 */
export function actionButton(options: {
  label: string;
  name: string;
  onClick: () => void;
}): Component {
  return defineComponent({
    name: `TopbarAction-${options.name}`,
    render: () =>
      h(
        ElButton,
        {
          size: "small",
          name: options.name,
          "data-testid": options.name,
          onClick: options.onClick,
        },
        () => options.label,
      ),
  });
}
