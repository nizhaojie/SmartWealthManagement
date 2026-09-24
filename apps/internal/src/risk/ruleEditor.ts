// 规则编辑器表单的派生逻辑：全部由 `GET /schema` 的载荷推出来，组件里不留第二份清单。
//
// 放在组件外面是因为这几件事都有「一处口径、两个使用者」的性质：字段换了算子下拉要收敛、
// 算子换了阈值输入框要变形、时间窗算子才要窗长。它们能单独测，就不必每次挂载一整个
// Element Plus 表格去验一遍。
import type { RiskRuleSchema, RuleFieldSpec, RuleOperatorSpec } from "./types";

/** 阈值键的呈现文案：后端的键名是 `value` / `min` / `max`，界面上要说人话。 */
const THRESHOLD_KEY_LABELS: Record<string, string> = {
  value: "阈值",
  min: "下限",
  max: "上限",
};

export function thresholdKeyLabel(key: string): string {
  return THRESHOLD_KEY_LABELS[key] ?? key;
}

export function fieldSpec(
  schema: RiskRuleSchema | null,
  fieldKey: string,
): RuleFieldSpec | null {
  return schema?.fields.find((field) => field.key === fieldKey) ?? null;
}

function operatorSpec(
  schema: RiskRuleSchema | null,
  operatorKey: string,
): RuleOperatorSpec | null {
  return schema?.operators.find((operator) => operator.key === operatorKey) ?? null;
}

/**
 * 选了字段之后能配的算子：取该字段声明的允许清单，按算子的注册顺序排。
 *
 * 顺序按注册表而不是允许清单——注册表是后端的呈现顺序，允许清单只是「哪些可用」。
 */
export function operatorChoices(
  schema: RiskRuleSchema | null,
  fieldKey: string,
): RuleOperatorSpec[] {
  const allowed = fieldSpec(schema, fieldKey)?.allowed_operators ?? [];
  if (!schema) return [];
  return schema.operators.filter((operator) => allowed.includes(operator.key));
}

/** 阈值输入框的键名：`gte` 一个（`value`），`between` 两个（`min` / `max`）。 */
export function thresholdKeys(schema: RiskRuleSchema | null, operatorKey: string): string[] {
  return operatorSpec(schema, operatorKey)?.threshold_keys ?? [];
}

/** 时间窗算子才出现窗长输入框；其余算子不出现，提交时置 NULL。 */
export function usesWindowHours(schema: RiskRuleSchema | null, operatorKey: string): boolean {
  return operatorSpec(schema, operatorKey)?.scope === "window";
}

/** 字段的物理值域，作为阈值输入框旁的提示；没有值域的字段（产品标识）给 null。 */
export function valueRangeHint(schema: RiskRuleSchema | null, fieldKey: string): string | null {
  return fieldSpec(schema, fieldKey)?.value_range?.text ?? null;
}

/**
 * 待提交的阈值：按当前算子的键名取值，多余的键一律丢掉。
 *
 * 草稿里会留着上一个算子的键（从 `between` 换回 `gte` 之后 `min` / `max` 还在对象里）。
 * 丢掉它们是因为后端按算子的形状校验：`gte` 收到 `min` 只会被拒成「阈值形状未通过」，
 * 而人已经看不见那个输入框了，无从改起。
 */
export function thresholdPayload(
  schema: RiskRuleSchema | null,
  operatorKey: string,
  draft: Record<string, string>,
): Record<string, string> {
  const payload: Record<string, string> = {};
  for (const key of thresholdKeys(schema, operatorKey)) {
    payload[key] = (draft[key] ?? "").trim();
  }
  return payload;
}
