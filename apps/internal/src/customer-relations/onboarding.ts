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
