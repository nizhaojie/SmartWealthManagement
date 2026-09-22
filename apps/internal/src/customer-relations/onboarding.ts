/**
 * 开户表单的取值域。这里逐条对齐后端 `app/customer_onboarding.py` 的校验：
 * 前端先拦一道是为了把错误显示在字段下方，不是为了替代后端——它仍然会再校验一次。
 */

/** 客户分层的规范写法（CONTEXT「客户分层」）：不引入 mockup 的「金牌 / 资深」那类不存在的分级。 */
export const CUSTOMER_LEVELS = ["普通", "金卡", "白金", "钻石", "私行"] as const;

export const ANNUAL_INCOME_RANGES = [
  "无收入",
  "10万以下",
  "10-30万",
  "30-50万",
  "50-100万",
  "100万以上",
] as const;

export const INVESTMENT_EXPERIENCES = [
  "无",
  "0-1年",
  "1-3年",
  "3-5年",
  "5-10年",
  "10年以上",
] as const;

/** 目标配置的资产大类，与画像页的对比图同一套类别。 */
export const TARGET_ALLOCATION_CATEGORIES = ["现金", "债券", "混合", "股票", "另类"] as const;

export const ID_NUMBER_PATTERN = /^\d{17}[0-9Xx]$/;
export const PHONE_PATTERN = /^\d{11}$/;
export const MIN_PASSWORD_LENGTH = 8;

/**
 * 目标配置是**比例**，因此合计必须为 100——判据与后端
 * `app/customer_profile/target_allocation.py` 是同一份，这里先拦一道只是为了把错误
 * 显示在字段旁边。合计 180 是矛盾；合计 50 会被投顾方案里的「100 减去其余」把差额
 * 记到被侧重的类别上，客户拿到的配置建议就与自己的意愿无关了。
 */
export const TARGET_ALLOCATION_TOTAL = 100;

/** 五项全为 0 视为「没有填」——目标配置是可选项。 */
export function targetAllocationTotal(allocation: Record<string, number>): number {
  const sum = TARGET_ALLOCATION_CATEGORIES.reduce(
    (total, category) => total + (allocation[category] ?? 0),
    0,
  );
  // 输入框给的是 JS 浮点数（33.33 + 33.33 + 33.34 不等于 100），按百分位对齐再比。
  return Math.round(sum * 100) / 100;
}

export function targetAllocationError(allocation: Record<string, number>): string | null {
  const total = targetAllocationTotal(allocation);
  if (total === 0) return null;
  if (total !== TARGET_ALLOCATION_TOTAL) {
    // 与后端 `target_allocation.SUM_MESSAGE` 逐字一致：同一条规则不该有两种说法——
    // 前端先拦一道，后端还会再拦一次，用户看到的必须是同一句话。
    return `目标配置的各类占比合计必须为 ${TARGET_ALLOCATION_TOTAL}%（当前 ${total}%）`;
  }
  return null;
}
