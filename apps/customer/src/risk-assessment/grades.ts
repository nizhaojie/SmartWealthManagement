import type { RiskLevel } from "./types";

export const RISK_LEVEL_LABELS: Record<RiskLevel, string> = {
  C1: "保守型",
  C2: "稳健型",
  C3: "平衡型",
  C4: "进取型",
  C5: "激进型",
};

export const RISK_LEVEL_MEANINGS: Record<RiskLevel, string> = {
  C1: "您更看重本金安全和随时取用，能接受的波动很低。",
  C2: "您可以接受很小的波动，更看重稳健增值与可控回撤。",
  C3: "您希望收益与波动取得平衡，能接受中等程度的起伏。",
  C4: "您愿意为更高收益承担较大波动，投资期限也偏长。",
  C5: "您更关注长期收益，可以承受明显回撤。",
};
